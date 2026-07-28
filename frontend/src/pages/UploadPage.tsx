import { type ChangeEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, uploadAudio } from "../services/api";

const ALLOWED_EXTENSIONS = [".mp3", ".wav", ".flac", ".m4a"];

function hasAllowedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export default function UploadPage() {
  const navigate = useNavigate();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setError(null);
    if (file && !hasAllowedExtension(file.name)) {
      setError(`Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(", ")}`);
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  }

  async function handleUpload() {
    if (!selectedFile) return;
    setIsUploading(true);
    setError(null);
    try {
      const job = await uploadAudio(selectedFile);
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

  return (
    <div className="upload-page">
      <h1>TranscriScore</h1>
      <p>Upload an audio clip to generate an editable draft of sheet music.</p>

      <input
        type="file"
        accept={ALLOWED_EXTENSIONS.join(",")}
        onChange={handleFileChange}
        disabled={isUploading}
      />

      {selectedFile && <p>Selected: {selectedFile.name}</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <button type="button" onClick={handleUpload} disabled={!selectedFile || isUploading}>
        {isUploading ? "Uploading..." : "Transcribe"}
      </button>
    </div>
  );
}
