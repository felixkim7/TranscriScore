import { type ChangeEvent, type DragEvent, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, uploadAudio } from "../services/api";
import { SINGLE_INSTRUMENT_LABELS, type SingleInstrumentLabel } from "../services/types";

const ALLOWED_EXTENSIONS = [".mp3", ".wav", ".flac", ".m4a"];

// Human-readable label per SingleInstrumentLabel value — shown to the user
// instead of the raw backend stem_label strings (e.g. "vocal_melody").
const INSTRUMENT_DISPLAY_NAMES: Record<SingleInstrumentLabel, string> = {
  vocal_melody: "Vocals",
  bass: "Bass",
  guitar_accompaniment: "Guitar",
  piano_accompaniment: "Piano",
  drums: "Drums",
  other_accompaniment: "Other",
};

type SeparationMode = "multiple" | "single";

function hasAllowedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragActive, setIsDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [separationMode, setSeparationMode] = useState<SeparationMode>("multiple");
  const [singleInstrument, setSingleInstrument] = useState<SingleInstrumentLabel | "">("");

  function applyFile(file: File | null) {
    setError(null);
    if (file && !hasAllowedExtension(file.name)) {
      setError(`Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(", ")}`);
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    applyFile(event.target.files?.[0] ?? null);
  }

  function handleDragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (isUploading) return;
    setIsDragActive(true);
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (event.currentTarget.contains(event.relatedTarget as Node)) return;
    setIsDragActive(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragActive(false);
    if (isUploading) return;
    applyFile(event.dataTransfer.files?.[0] ?? null);
  }

  function openFileBrowser() {
    if (isUploading) return;
    fileInputRef.current?.click();
  }

  function handleDropzoneKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openFileBrowser();
    }
  }

  function clearFile(event: React.MouseEvent) {
    event.stopPropagation();
    setSelectedFile(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleUpload() {
    if (!selectedFile) return;
    if (separationMode === "single" && !singleInstrument) {
      setError("Choose which instrument this recording is.");
      return;
    }
    setIsUploading(true);
    setError(null);
    try {
      const job = await uploadAudio(
        selectedFile,
        separationMode === "single" ? (singleInstrument as SingleInstrumentLabel) : undefined,
      );
      navigate(`/job/${job.job_id}`);
    } catch (e) {
      // The backend pipeline takes several minutes — upload() only waits for the
      // file to be saved and the job to be created, so a failure here means the
      // upload itself was rejected (bad file type, network issue), not that the
      // pipeline failed later (that shows up on the status page instead).
      setError(e instanceof ApiError ? String(e.detail) : "Upload failed. Is the backend running?");
      setIsUploading(false);
    }
  }

  const dropzoneClassName = [
    "dropzone",
    isDragActive ? "dropzone-active" : "",
    selectedFile ? "dropzone-filled" : "",
    isUploading ? "dropzone-disabled" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="upload-page">
      <h1>TranscriScore</h1>
      <p>Upload an audio clip to generate an editable draft of sheet music.</p>

      <div
        className={dropzoneClassName}
        role="button"
        tabIndex={isUploading ? -1 : 0}
        aria-disabled={isUploading}
        onClick={openFileBrowser}
        onKeyDown={handleDropzoneKeyDown}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ALLOWED_EXTENSIONS.join(",")}
          onChange={handleFileChange}
          disabled={isUploading}
          className="dropzone-input"
          aria-label="Audio file"
        />

        <svg
          className="dropzone-icon"
          width="40"
          height="40"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M12 16V4M12 4L7 9M12 4l5 5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>

        {selectedFile ? (
          <div className="dropzone-file">
            <span className="dropzone-filename">{selectedFile.name}</span>
            <span className="dropzone-filesize">{formatFileSize(selectedFile.size)}</span>
            {!isUploading && (
              <button type="button" className="dropzone-clear" onClick={clearFile} aria-label="Remove file">
                ×
              </button>
            )}
          </div>
        ) : (
          <>
            <p className="dropzone-title">
              Drag and drop an audio file, or <span className="dropzone-link">browse</span>
            </p>
            <p className="dropzone-hint">{ALLOWED_EXTENSIONS.join(" · ")}</p>
          </>
        )}
      </div>

      <fieldset className="instrument-mode" disabled={isUploading}>
        <legend>How many instruments/voices are in this recording?</legend>

        <label className="radio-option">
          <input
            type="radio"
            name="separationMode"
            value="multiple"
            checked={separationMode === "multiple"}
            onChange={() => setSeparationMode("multiple")}
          />
          Multiple instruments (separate into stems)
        </label>

        <label className="radio-option">
          <input
            type="radio"
            name="separationMode"
            value="single"
            checked={separationMode === "single"}
            onChange={() => setSeparationMode("single")}
          />
          Single instrument (skip separation)
        </label>

        {separationMode === "single" && (
          <select
            className="instrument-select"
            value={singleInstrument}
            onChange={(e) => setSingleInstrument(e.target.value as SingleInstrumentLabel | "")}
            aria-label="Which instrument"
          >
            <option value="" disabled>
              Choose an instrument…
            </option>
            {SINGLE_INSTRUMENT_LABELS.map((label) => (
              <option key={label} value={label}>
                {INSTRUMENT_DISPLAY_NAMES[label]}
              </option>
            ))}
          </select>
        )}
      </fieldset>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <button
        type="button"
        className="btn-primary"
        onClick={handleUpload}
        disabled={!selectedFile || isUploading || (separationMode === "single" && !singleInstrument)}
      >
        {isUploading ? "Uploading…" : "Transcribe"}
      </button>
    </div>
  );
}
