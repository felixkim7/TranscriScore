from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import export, transcribe, upload

app = FastAPI(
    title="TranscriScore API",
    description="Audio -> editable sheet music (MusicXML/MSCZ) pipeline.",
)

# Wide-open CORS for local frontend dev (React dev server on a different port).
# Tighten this (specific origins) before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(transcribe.router)
app.include_router(export.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
