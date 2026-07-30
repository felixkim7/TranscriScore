import { useEffect, useRef, useState } from "react";
import { Midi } from "@tonejs/midi";
import {
  loadDrumKit,
  loadSoundfont,
  playDrumHit,
  playNote,
  type DrumKit,
  type Soundfont,
} from "../services/soundfont";
import { stemMidiUrl } from "../services/api";
import { STEM_NAMES, type StemName } from "../services/types";

// GM program number -> midi-js-soundfonts instrument name (the exact 128-entry
// list services/soundfont.ts fetches from, confirmed against gleitz/midi-js-
// soundfonts/FluidR3_GM/names.json). Only the 4 programs this project's
// backend actually assigns are listed — see backend/app/services/
// transcription_service.py's STEM_LABEL_MIDI_PROGRAMS, which this table must
// stay in sync with (both were chosen from the same music21 instrument
// classes already used in musicxml_service.py, so the notated score, the
// per-stem export, and this in-browser player all agree on what each part
// should sound like).
const GM_PROGRAM_TO_SOUNDFONT_NAME: Record<number, string> = {
  0: "acoustic_grand_piano",
  24: "acoustic_guitar_nylon",
  33: "electric_bass_finger",
  53: "voice_oohs",
};

// Drums now play back too, via a dedicated 3-sample TR-808 kit (see
// services/soundfont.ts's loadDrumKit()/playDrumHit() docstrings) rather than
// the melodic-instrument soundfont path — the gleitz/midi-js-soundfonts
// source used for every other stem has no real GM drum kit (channel-10,
// note-keyed kick/snare/hihat), confirmed directly, and a community fork
// claiming to add one was checked directly and found broken (its
// "drums-mp3.js" file actually contains piano audio data under a misleading
// filename). drum_transcription_service.py (backend) only ever emits 3 fixed
// GM percussion pitches, so a small dedicated one-shot kit is a better fit
// than a full melodic soundfont anyway.
const PLAYABLE_STEMS = STEM_NAMES;

const STEM_EMOJI: Record<StemName, string> = {
  vocals: "🎤",
  drums: "🥁",
  guitar: "🎸",
  bass: "🪕",
  piano: "🎹",
  other: "🎼",
};

interface MidiPlayerProps {
  jobId: string;
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

type LoadStatus = "idle" | "loading" | "ready" | "error";

interface MidiTileProps {
  jobId: string;
  stem: StemName;
  isOpen: boolean;
  onToggle: () => void;
  audioContext: AudioContext;
}

/**
 * One stem's MIDI player tile. Unlike StemPlayer.tsx's plain <audio> (browsers
 * don't decode .mid natively -- confirmed directly, HTML5 audio only supports
 * wav/mp3/ogg), this fetches the raw MIDI bytes, parses them with @tonejs/midi
 * (gives real note/instrument/timing data), loads a matching sound source via
 * services/soundfont.ts, and schedules each note as a WebAudio event relative
 * to audioContext.currentTime.
 *
 * Two different sound sources depending on stem: pitched stems (vocals/bass/
 * guitar/piano/other) load a GM instrument soundfont, keyed by note name, and
 * play through playNote(). Drums load the small dedicated 3-sample one-shot
 * kit instead (no real GM drum kit exists in the soundfont source used for
 * everything else — see PLAYABLE_STEMS's comment), keyed by fixed GM
 * percussion pitch number, and play through playDrumHit().
 *
 * WebAudio scheduling has no native "seek" the way <audio>.currentTime does --
 * pausing/seeking here means: stop every currently-scheduled/sounding note,
 * then (for play/seek) reschedule every remaining note relative to a fresh
 * start reference. This is a coarser transport than StemPlayer's, but correct.
 */
function MidiTile({ jobId, stem, isOpen, onToggle, audioContext }: MidiTileProps) {
  const isDrums = stem === "drums";

  const [status, setStatus] = useState<LoadStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const midiRef = useRef<Midi | null>(null);
  const soundfontRef = useRef<Soundfont | null>(null);
  const drumKitRef = useRef<DrumKit | null>(null);
  const scheduledNodesRef = useRef<AudioBufferSourceNode[]>([]);
  // audioContext.currentTime when the CURRENT playback run started, minus
  // however far into the piece it started from -- lets currentTime be
  // recovered at any moment as (audioContext.currentTime - startedAtRef.current).
  const startedAtRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  const loadPromiseRef = useRef<Promise<void> | null>(null);
  const mountedRef = useRef(true);

  /**
   * Loading used to live in a useEffect keyed on [isOpen, status, ...] that
   * itself called setStatus("loading") — a real bug, not a timing fluke:
   * setting a value that's also in the effect's own dependency array makes
   * React re-run the effect right after the state update commits, which
   * immediately invoked the PREVIOUS run's cleanup (`cancelled = true`) and
   * cleared its timeout — orphaning the in-flight fetch/decode before it
   * could ever reach a success or error branch. That's exactly why the UI
   * got stuck on "불러오는 중…" with no error, even past the 15s timeout: the
   * timeout that fired belonged to an already-cancelled, invisible run.
   *
   * Fixed by moving loading out of an effect entirely and into a plain
   * function invoked directly from the tile's click handler (see
   * handleTileClick below) — one real user gesture triggers one real load,
   * with no dependency-array re-entrancy to race against.
   */
  function ensureLoaded(): Promise<void> {
    if (status === "ready") return Promise.resolve();
    if (loadPromiseRef.current) return loadPromiseRef.current;

    setStatus("loading");
    setErrorMessage("");

    const loadPromise = (async () => {
      const TIMEOUT_MS = 30000;
      let timeoutId: number | undefined;

      try {
        // Entered directly from a click handler, so resume() is associated
        // with a real user gesture and satisfies browser autoplay policy.
        if (audioContext.state === "suspended") {
          await audioContext.resume();
        }

        const loadWork = (async () => {
          const response = await fetch(stemMidiUrl(jobId, stem));
          if (!response.ok) {
            throw new Error(`MIDI not available yet (${response.status})`);
          }
          const midi = new Midi(await response.arrayBuffer());

          if (isDrums) {
            const drumKit = await loadDrumKit(audioContext);
            return { midi, soundfont: null, drumKit };
          }

          const firstTrackWithNotes = midi.tracks.find((track) => track.notes.length > 0);
          const programNumber = firstTrackWithNotes?.instrument.number ?? 0;
          const soundfontName = GM_PROGRAM_TO_SOUNDFONT_NAME[programNumber] ?? "acoustic_grand_piano";
          const soundfont = await loadSoundfont(audioContext, soundfontName);
          return { midi, soundfont, drumKit: null };
        })();

        const timeout = new Promise<never>((_, reject) => {
          timeoutId = window.setTimeout(() => {
            reject(new Error("시간 초과 (MIDI 또는 사운드 로딩 실패)"));
          }, TIMEOUT_MS);
        });

        const { midi, soundfont, drumKit } = await Promise.race([loadWork, timeout]);
        if (!mountedRef.current) return;

        midiRef.current = midi;
        soundfontRef.current = soundfont;
        drumKitRef.current = drumKit;
        setDuration(midi.duration);
        setStatus("ready");
      } catch (err: unknown) {
        if (!mountedRef.current) return;
        setStatus("error");
        setErrorMessage(err instanceof Error ? err.message : String(err));
      } finally {
        if (timeoutId !== undefined) window.clearTimeout(timeoutId);
        loadPromiseRef.current = null;
      }
    })();

    loadPromiseRef.current = loadPromise;
    return loadPromise;
  }

  function stopAllScheduled() {
    for (const node of scheduledNodesRef.current) {
      // A node whose scheduled start() time hasn't occurred yet, or one
      // that's already finished playing, can throw InvalidStateError on
      // stop() in some browsers -- this is just a "best-effort silence
      // everything" cleanup, not a case where a stop failing should surface
      // as an error to the user.
      try {
        node.stop();
      } catch {
        // ignore
      }
    }
    scheduledNodesRef.current = [];
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }

  function scheduleFrom(offsetSeconds: number) {
    const midi = midiRef.current;
    const soundfont = soundfontRef.current;
    const drumKit = drumKitRef.current;
    if (!midi || (isDrums ? !drumKit : !soundfont)) return;

    stopAllScheduled();
    const startedAt = audioContext.currentTime - offsetSeconds;
    startedAtRef.current = startedAt;

    for (const track of midi.tracks) {
      for (const note of track.notes) {
        if (note.time + note.duration <= offsetSeconds) continue; // already past
        const when = startedAt + note.time;
        const node =
          isDrums && drumKit
            ? playDrumHit(audioContext, drumKit, note.midi, when, note.velocity)
            : soundfont
              ? playNote(audioContext, soundfont, note.midi, when, note.duration, note.velocity)
              : null;
        if (node) scheduledNodesRef.current.push(node);
      }
    }

    const tick = () => {
      const elapsed = audioContext.currentTime - startedAtRef.current;
      if (elapsed >= midi.duration) {
        setCurrentTime(midi.duration);
        setIsPlaying(false);
        scheduledNodesRef.current = [];
        return;
      }
      setCurrentTime(elapsed);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }

  async function togglePlay() {
    if (status !== "ready") return;
    if (isPlaying) {
      stopAllScheduled();
      setIsPlaying(false);
      return;
    }

    // Resume again on the actual play click — the safest place to satisfy
    // browser autoplay policy even if loading happened earlier/separately.
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }

    // Resume from wherever currentTime is (0 if just loaded, or wherever a
    // previous stop/seek left off) rather than always restarting from 0.
    scheduleFrom(currentTime >= duration ? 0 : currentTime);
    setIsPlaying(true);
  }

  function handleTileClick() {
    if (!isOpen) {
      void ensureLoaded();
    }
    onToggle();
  }

  function handleSeek(value: number) {
    setCurrentTime(value);
    if (isPlaying) {
      scheduleFrom(value);
    }
  }

  useEffect(() => {
    if (!isOpen) {
      stopAllScheduled();
      setIsPlaying(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stopAllScheduled();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className={`track-tile ${isOpen ? "track-tile-open" : ""}`} data-track={stem}>
      <button
        type="button"
        className="track-circle"
        onClick={handleTileClick}
        aria-expanded={isOpen}
        aria-label={`${stem} MIDI ${isOpen ? "닫기" : "재생 열기"}`}
      >
        <span className="track-emoji" aria-hidden="true">
          {STEM_EMOJI[stem]}
        </span>
        <span className="track-name">{stem}</span>
      </button>

      {isOpen && (
        <div className="track-player">
          {status === "loading" && <span className="track-time">불러오는 중…</span>}
          {status === "error" && (
            <span className="track-time" role="alert">
              재생 불가 ({errorMessage})
            </span>
          )}
          {status === "ready" && (
            <>
              <button
                type="button"
                className="track-play-btn"
                onClick={() => void togglePlay()}
                aria-label={isPlaying ? "일시정지" : "재생"}
              >
                {isPlaying ? "⏸" : "▶"}
              </button>

              <span className="track-time">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>

              <input
                type="range"
                className="track-seek"
                min={0}
                max={duration || 0}
                step={0.1}
                value={currentTime}
                onChange={(e) => handleSeek(Number(e.target.value))}
                aria-label="재생 위치"
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function MidiPlayer({ jobId }: MidiPlayerProps) {
  const [openTrack, setOpenTrack] = useState<string | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);

  // Deliberately never closed via a mount-effect cleanup. React StrictMode
  // (see main.tsx) mounts every component twice in dev (mount -> cleanup ->
  // mount again) specifically to catch bugs like this: audioContextRef is a
  // ref, so it SURVIVES the synthetic remount (only effects re-run, not the
  // lazy `if (!audioContextRef.current)` initializer below) — an earlier
  // version closed the context in a `useEffect(() => () => ctx.close(), [])`
  // cleanup, which killed the SAME AudioContext the real, still-mounted
  // second pass kept using. Once closed, an AudioContext is permanently
  // dead: resume() stops doing anything useful and scheduled notes produce
  // no sound and no progress — confirmed as the actual cause of "loads
  // fine, play bar appears, nothing plays, time frozen" (the note-scheduling
  // code itself was correct; it was scheduling onto an already-closed
  // context). AudioContexts are cheap enough to just leave open for the
  // page's lifetime rather than chase a correct close-on-real-unmount-only
  // signal.
  if (!audioContextRef.current) {
    audioContextRef.current = new AudioContext();
  }

  function toggleTrack(key: string) {
    setOpenTrack((current) => (current === key ? null : key));
  }

  return (
    <div className="midi-player">
      <h2>Listen to transcription (MIDI)</h2>

      <div className="track-grid">
        {PLAYABLE_STEMS.map((stem) => (
          <MidiTile
            key={stem}
            jobId={jobId}
            stem={stem}
            isOpen={openTrack === stem}
            onToggle={() => toggleTrack(stem)}
            audioContext={audioContextRef.current!}
          />
        ))}
      </div>
    </div>
  );
}
