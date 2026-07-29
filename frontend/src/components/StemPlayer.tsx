import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { originalAudioUrl, stemAudioUrl } from "../services/api";
import { STEM_NAMES, type StemName } from "../services/types";

interface StemPlayerProps {
  jobId: string;
}

const STEM_EMOJI: Record<StemName, string> = {
  vocals: "🎤",
  drums: "🥁",
  guitar: "🎸",
  bass: "🪕",
  piano: "🎹",
  other: "🎼",
};

const ORIGINAL_TRACK_KEY = "original";
const ORIGINAL_EMOJI = "🎧";

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface TrackTileProps {
  trackKey: string;
  label: string;
  emoji: string;
  src: string;
  isOpen: boolean;
  onToggle: () => void;
}

/**
 * One circular emoji "button" per track. Collapsed, it's just an emoji + label
 * in a circle. Clicking it expands the circle and reveals a small custom
 * play/seek/mute bar underneath, backed by a hidden <audio> element (no native
 * browser controls). Collapsing the tile (or opening a different one) pauses
 * its audio so only one stem plays at a time.
 */
function TrackTile({ trackKey, label, emoji, src, isOpen, onToggle }: TrackTileProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    if (!isOpen) {
      audioRef.current?.pause();
      setIsPlaying(false);
    }
  }, [isOpen]);

  function togglePlay() {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      void audio.play();
      setIsPlaying(true);
    } else {
      audio.pause();
      setIsPlaying(false);
    }
  }

  function toggleMute() {
    const audio = audioRef.current;
    if (!audio) return;
    audio.muted = !audio.muted;
    setIsMuted(audio.muted);
  }

  function handleSeek(event: ChangeEvent<HTMLInputElement>) {
    const audio = audioRef.current;
    if (!audio) return;
    const value = Number(event.target.value);
    audio.currentTime = value;
    setCurrentTime(value);
  }

  return (
    <div className={`track-tile ${isOpen ? "track-tile-open" : ""}`} data-track={trackKey}>
      <button
        type="button"
        className="track-circle"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-label={`${label} ${isOpen ? "닫기" : "재생 열기"}`}
      >
        <span className="track-emoji" aria-hidden="true">
          {emoji}
        </span>
        <span className="track-name">{label}</span>
      </button>

      {isOpen && (
        <div className="track-player">
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio
            ref={audioRef}
            src={src}
            preload="metadata"
            onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
            onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
            onEnded={() => setIsPlaying(false)}
          />

          <button
            type="button"
            className="track-play-btn"
            onClick={togglePlay}
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
            onChange={handleSeek}
            aria-label="재생 위치"
          />

          <button
            type="button"
            className="track-mute-btn"
            onClick={toggleMute}
            aria-label={isMuted ? "음소거 해제" : "음소거"}
          >
            {isMuted ? "🔇" : "🔊"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function StemPlayer({ jobId }: StemPlayerProps) {
  const [openTrack, setOpenTrack] = useState<string | null>(null);

  function toggleTrack(key: string) {
    setOpenTrack((current) => (current === key ? null : key));
  }

  return (
    <div className="stem-player">
      <h2>Listen</h2>

      <div className="track-grid">
        <TrackTile
          trackKey={ORIGINAL_TRACK_KEY}
          label="Original mix"
          emoji={ORIGINAL_EMOJI}
          src={originalAudioUrl(jobId)}
          isOpen={openTrack === ORIGINAL_TRACK_KEY}
          onToggle={() => toggleTrack(ORIGINAL_TRACK_KEY)}
        />

        {STEM_NAMES.map((stem) => (
          <TrackTile
            key={stem}
            trackKey={stem}
            label={stem}
            emoji={STEM_EMOJI[stem] ?? "🎼"}
            src={stemAudioUrl(jobId, stem)}
            isOpen={openTrack === stem}
            onToggle={() => toggleTrack(stem)}
          />
        ))}
      </div>
    </div>
  );
}
