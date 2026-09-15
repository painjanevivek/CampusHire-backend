import json
import time
from typing import Any, cast

import httpx

from app.ai.providers.base import StructuredGenerationResult
from app.core.config import get_settings


class OpenRouterProvider:
    def __init__(self) -> None:
        settings = get_settings()
        if settings.openrouter_api_key is None or not settings.openrouter_model:
            raise RuntimeError("OpenRouter is not configured")
        self._api_key = settings.openrouter_api_key.get_secret_value()
        self._base_url = str(settings.openrouter_base_url).rstrip("/")
        self._model = settings.openrouter_model
        self._timeout = settings.openrouter_timeout_seconds
        self._max_output_tokens = settings.ai_max_output_tokens
        self._site_url = str(settings.openrouter_site_url) if settings.openrouter_site_url else None
        self._app_name = settings.openrouter_app_name

    def generate_structured(
        self, *, prompt: str, response_schema: dict[str, Any]
    ) -> StructuredGenerationResult:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": self._app_name,
        }
        if self._site_url:
            headers["HTTP-Referer"] = self._site_url
        started = time.perf_counter()
        response = httpx.post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            timeout=self._timeout,
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": self._max_output_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "campushire_response",
                        "strict": True,
                        "schema": response_schema,
                    },
                },
            },
        )
        response.raise_for_status()
        body = cast(dict[str, Any], response.json())
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenRouter returned no structured content")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content:
            raise RuntimeError("OpenRouter returned no structured content")
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenRouter returned an invalid structured payload")
        raw_usage = body.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        return StructuredGenerationResult(
            content=parsed,
            provider_name="openrouter",
            model_version=self._model,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
