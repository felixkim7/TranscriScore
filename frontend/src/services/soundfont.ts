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

// --- Drums ---
//
// The melodic-soundfont path above (gleitz/midi-js-soundfonts) has no real GM
// drum kit -- confirmed directly, its FluidR3_GM set only has melodic
// percussion (marimba, xylophone, etc), and a community fork claiming to add
// one (dave4mpls/midi-js-soundfonts-with-drums) was checked directly and
// found broken (its "drums-mp3.js" file actually contains piano audio data
// under a misleading filename).
//
// But drum_transcription_service.py (backend) only ever emits 3 fixed GM
// percussion pitches -- settings.DRUM_VOICE_MIDI_PITCH: kick=36, snare=38,
// hihat=42 -- so this doesn't need a full 47-sound GM percussion kit, just 3
// real one-shot hits. Sourced from tidalcycles/sounds-tr808-fischer, a real
// TR-808 drum machine sample set released under CC0 1.0 (public domain
// dedication, confirmed by fetching its actual LICENSE file directly, unlike
// the broken fork checked earlier) and maintained by the same organization
// behind Dirt-Samples/Tidal Cycles, not an anonymous/unclear-provenance
// source. Each WAV was fetched and its header inspected directly (RIFF/WAVE/
// fmt, PCM, 44.1kHz) to confirm real, valid, decodable audio before trusting
// this — not assumed from the repo's file listing alone.
const DRUM_SAMPLE_BASE_URL = "https://raw.githubusercontent.com/tidalcycles/sounds-tr808-fischer/main";

const DRUM_SAMPLE_PATHS: Record<number, string> = {
  36: "bd8/BD0000.WAV", // kick
  38: "sd8/SD0000.WAV", // snare
  42: "ch8/CH.WAV", // closed hi-hat
};

export interface DrumKit {
  /** GM percussion pitch number (36/38/42) -> decoded AudioBuffer. */
  buffers: Map<number, AudioBuffer>;
}

/**
 * Fetch and decode the 3 fixed drum one-shots this project's backend ever
 * emits. Unlike loadSoundfont() (one instrument = dozens of per-note pitched
 * samples), each drum voice is exactly one fixed-pitch hit -- no note-name
 * mapping, no JS-source-as-JSON parsing, just 3 direct WAV fetches.
 */
export async function loadDrumKit(audioContext: AudioContext): Promise<DrumKit> {
  const buffers = new Map<number, AudioBuffer>();

  await Promise.all(
    Object.entries(DRUM_SAMPLE_PATHS).map(async ([pitchStr, path]) => {
      const response = await fetch(`${DRUM_SAMPLE_BASE_URL}/${path}`);
      if (!response.ok) {
        throw new Error(`Drum sample fetch failed for "${path}" (${response.status})`);
      }
      const bytes = await response.arrayBuffer();
      const buffer = await audioContext.decodeAudioData(bytes);
      buffers.set(Number(pitchStr), buffer);
    }),
  );

  return { buffers };
}

/**
 * Play one drum hit through audioContext, starting at `when`. Unlike
 * playNote() (a sampled instrument's note rings for the note's own
 * duration), a one-shot drum sample plays its own natural length regardless
 * of the transcribed note's duration -- source.stop() is deliberately NOT
 * called with a fixed end time here, since these are short percussive hits,
 * not sustained pitched notes, and cutting one off early would sound wrong.
 */
export function playDrumHit(
  audioContext: AudioContext,
  drumKit: DrumKit,
  gmPitch: number,
  when: number,
  gain: number,
): AudioBufferSourceNode | null {
  const buffer = drumKit.buffers.get(gmPitch);
  if (!buffer) return null; // not one of the 3 known drum voices

  const source = audioContext.createBufferSource();
  source.buffer = buffer;

  const gainNode = audioContext.createGain();
  gainNode.gain.value = Math.max(0, Math.min(1, gain));
  source.connect(gainNode);
  gainNode.connect(audioContext.destination);

  source.start(when);
  return source;
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
