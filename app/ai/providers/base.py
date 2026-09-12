from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StructuredGenerationResult:
    content: dict[str, Any]
    provider_name: str
    model_version: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class StructuredGenerator(Protocol):
    def generate_structured(
        self, *, prompt: str, response_schema: dict[str, Any]
    ) -> StructuredGenerationResult: ...
