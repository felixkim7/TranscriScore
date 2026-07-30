// Minimal General MIDI soundfont loader — replaces soundfont-player, which
// was tried first and REVERTED after real testing: its dependency
// (audio-loader) decodes every note sample via the LEGACY callback-based
// AudioContext.decodeAudioData(buf, onSuccess, onError), and current Chrome
// versions primarily resolve via the Promise decodeAudioData() now returns
// instead — audio-loader's own package even flags itself deprecated for
// exactly this reason ("use native fetch() + decodeAudioData() instead").
// Those legacy callbacks can simply never fire on modern Chrome, so
// soundfont-player's instrument-loading promise hung forever with no
// rejection — confirmed directly: MidiPlayer.tsx got stuck on "불러오는 중…"
// with no error surfaced, exactly the failure mode this bug produces.
//
// This module fetches the same soundfont files (gleitz/midi-js-soundfonts,
// the same source soundfont-player used by default) directly and decodes
// with the modern Promise-based decodeAudioData() call, sidestepping the
// broken dependency entirely rather than patching around it.

const SOUNDFONT_BASE_URL = "https://gleitz.github.io/midi-js-soundfonts/FluidR3_GM";

export interface Soundfont {
  name: string;
  /** Scientific-pitch-notation note name (e.g. "C4") -> decoded AudioBuffer. */
  buffers: Map<string, AudioBuffer>;
}

/**
 * Fetch and decode a GM instrument's soundfont (e.g. "acoustic_guitar_nylon").
 *
 * The source file is JS, not JSON (`MIDI.Soundfont.acoustic_guitar_nylon = {...}`
 * with a trailing comma before the closing brace) — confirmed directly by
 * fetching a real file. Deliberately NOT eval()'d (that would execute
 * arbitrary code from a third-party URL) — instead the object-literal
 * substring is extracted and cleaned up just enough to be valid JSON
 * (strip the assignment prefix/semicolon, strip the trailing comma), then
 * parsed with JSON.parse(), which only ever produces data, never runs code.
 */
export async function loadSoundfont(audioContext: AudioContext, instrumentName: string): Promise<Soundfont> {
  const response = await fetch(`${SOUNDFONT_BASE_URL}/${instrumentName}-mp3.js`);
  if (!response.ok) {
    throw new Error(`Soundfont fetch failed for "${instrumentName}" (${response.status})`);
  }
  const source = await response.text();

  // The file starts with two unrelated "var MIDI = {};" / "MIDI.Soundfont =
  // {};" GUARD lines (confirmed directly by fetching a real file) — naively
  // taking the file's FIRST "{" grabs one of those empty guard objects, not
  // the real note data, and produces "{};" as the "object literal" (caught
  // by testing this against real data before trusting it, not assumed).
  // The real object starts specifically after "MIDI.Soundfont.<name> =".
  const assignmentMarker = `MIDI.Soundfont.${instrumentName} =`;
  const assignmentIndex = source.indexOf(assignmentMarker);
  if (assignmentIndex === -1) {
    throw new Error(`Unexpected soundfont file format for ${instrumentName}`);
  }
  const firstBrace = source.indexOf("{", assignmentIndex + assignmentMarker.length);
  const lastBrace = source.lastIndexOf("}");
  if (firstBrace === -1 || lastBrace === -1 || lastBrace < firstBrace) {
    throw new Error(`Unexpected soundfont file format for ${instrumentName}`);
  }
  const objectLiteral = source
    .slice(firstBrace, lastBrace + 1)
    // Trailing commas before a closing brace/bracket are valid in the JS
    // source but not in strict JSON — the real file has one right before
    // the final "}" (confirmed directly), so strip any of these.
    .replace(/,(\s*[}\]])/g, "$1");

  let noteToDataUri: Record<string, string>;
  try {
    noteToDataUri = JSON.parse(objectLiteral) as Record<string, string>;
  } catch {
    throw new Error(`Failed to parse soundfont data for ${instrumentName}`);
  }

  const entries = Object.entries(noteToDataUri);
  const buffers = new Map<string, AudioBuffer>();

  await Promise.all(
    entries.map(async ([noteName, dataUri]) => {
      const base64 = dataUri.slice(dataUri.indexOf(",") + 1);
      const bytes = base64ToArrayBuffer(base64);
      // Modern Promise-based call — no legacy callback arguments — this is
      // the actual fix; everything else here is just getting real audio
      // bytes into a shape decodeAudioData can consume.
      const buffer = await audioContext.decodeAudioData(bytes);
      buffers.set(noteName, buffer);
    }),
  );

  return { name: instrumentName, buffers };
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

const NOTE_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

/** MIDI note number (0-127) -> scientific pitch notation (e.g. 60 -> "C4"),
 * matching the note names used as keys in the soundfont data. */
export function midiNoteToName(midi: number): string {
  const octave = Math.floor(midi / 12) - 1;
  const name = NOTE_NAMES[midi % 12];
  return `${name}${octave}`;
}

/**
 * Play one decoded note through audioContext, starting at `when` (in the
 * same time base as audioContext.currentTime), for `duration` seconds.
 * Returns the AudioBufferSourceNode so the caller can stop it early (e.g.
 * on pause/seek) — mirrors soundfont-player's player.play()/node.stop()
 * shape closely enough that MidiTile's scheduling logic didn't need to
 * change beyond the import.
 */
export function playNote(
  audioContext: AudioContext,
  soundfont: Soundfont,
  midiNote: number,
  when: number,
  duration: number,
  gain: number,
): AudioBufferSourceNode | null {
  const buffer = soundfont.buffers.get(midiNoteToName(midiNote));
  if (!buffer) return null; // this soundfont has no sample for this exact note

  const source = audioContext.createBufferSource();
  source.buffer = buffer;

  const gainNode = audioContext.createGain();
  gainNode.gain.value = Math.max(0, Math.min(1, gain));
  source.connect(gainNode);
  gainNode.connect(audioContext.destination);

  source.start(when);
  source.stop(when + duration);
  return source;
}
