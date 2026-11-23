"""Voice-note transcription.

WhatsApp voice notes arrive as an audio media id. We download the file and send
it to the configured speech-to-text model (Groq Whisper by default). Kept as a
separate module so you can A/B different transcription services (the brief's
week-3 task) by changing only `transcribe_file`.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from app import whatsapp
from app.llm import get_llm


def transcribe_file(audio_path: str | Path) -> str:
    """Transcribe a local audio file to text (Arabic/English/French auto)."""
    return get_llm().transcribe(str(audio_path))


def transcribe_media(media_id: str) -> str:
    """Download a WhatsApp voice note by media id and transcribe it."""
    tmp = Path(tempfile.gettempdir()) / "cedar_voice"
    path = whatsapp.download_media(media_id, tmp)
    try:
        return transcribe_file(path)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
