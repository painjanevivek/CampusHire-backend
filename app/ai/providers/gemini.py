from google import genai
from google.genai import types

from app.core.config import get_settings


class GeminiProvider:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("Gemini is not configured")
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=settings.gemini_timeout_ms),
        )
        self._embedding_model = settings.gemini_embedding_model

    def embed(self, text: str) -> list[float]:
        response = self._client.models.embed_content(
            model=self._embedding_model, contents=text[:20_000]
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise RuntimeError("Gemini returned no embedding")
        return list(response.embeddings[0].values)
