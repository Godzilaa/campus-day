from __future__ import annotations

from pathlib import Path

from openai import OpenAI


class VoiceTranscriber:
    def __init__(self, api_key: str, model: str = "whisper-1", base_url: str | None = None) -> None:
        if base_url:
            self._client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self._client = OpenAI(api_key=api_key)
        self._model = model

    def transcribe(self, file_path: str) -> str:
        with Path(file_path).open("rb") as audio_file:
            response = self._client.audio.transcriptions.create(
                model=self._model,
                file=audio_file,
            )
        text = getattr(response, "text", "")
        return text.strip()
