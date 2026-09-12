import json
import time

from google import genai
from google.genai import types

from app.ai.providers.base import StructuredGenerationResult
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
        self._generation_model = settings.gemini_generation_model
        self._max_output_tokens = settings.ai_max_output_tokens

    def embed(self, text: str) -> list[float]:
        response = self._client.models.embed_content(
            model=self._embedding_model, contents=text[:20_000]
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise RuntimeError("Gemini returned no embedding")
        return list(response.embeddings[0].values)

    def generate_structured(
        self, *, prompt: str, response_schema: dict[str, object]
    ) -> StructuredGenerationResult:
        if not self._generation_model:
            raise RuntimeError("Gemini text generation is not configured")
        started = time.perf_counter()
        response = self._client.models.generate_content(
            model=self._generation_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=response_schema,
                max_output_tokens=self._max_output_tokens,
                temperature=0.2,
            ),
        )
        if not response.text:
            raise RuntimeError("Gemini returned no structured content")
        parsed = json.loads(response.text)
        if not isinstance(parsed, dict):
            raise RuntimeError("Gemini returned an invalid structured payload")
        usage = response.usage_metadata
        return StructuredGenerationResult(
            content=parsed,
            provider_name="gemini",
            model_version=self._generation_model,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )
