from typing import Any

import httpx
import pytest

from app.ai.providers.openrouter import OpenRouterProvider
from app.core.config import get_settings


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "choices": [{"message": {"content": '{"answer":"approved source"}'}}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 5},
        }


def test_openrouter_provider_sends_schema_bound_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/test-model")
    get_settings.cache_clear()
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> _Response:
        captured.update({"url": url, **kwargs})
        return _Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    result = OpenRouterProvider().generate_structured(
        prompt="Use only the approved source.",
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )

    assert result.content == {"answer": "approved source"}
    assert result.provider_name == "openrouter"
    assert result.model_version == "openai/test-model"
    assert result.input_tokens == 17
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-openrouter-key"
    assert captured["json"]["response_format"]["type"] == "json_schema"
    get_settings.cache_clear()
