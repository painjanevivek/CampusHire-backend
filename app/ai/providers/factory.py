from app.ai.providers.base import StructuredGenerator
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openrouter import OpenRouterProvider
from app.core.config import get_settings


def build_copilot_generator() -> StructuredGenerator:
    if get_settings().copilot_generation_provider == "openrouter":
        return OpenRouterProvider()
    return GeminiProvider()
