from __future__ import annotations

import asyncio

from ..config import Settings
from ..schemas import ModelDescriptor, ProviderStatus
from .base import InferenceProvider
from .gemini import GeminiProvider
from .llamacpp import LlamaCppProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatibleProvider


class ProviderManager:
    def __init__(self, settings: Settings, gemini_api_key: str | None = None) -> None:
        self.providers: dict[str, InferenceProvider] = {
            "llama_cpp": LlamaCppProvider(settings.llama_server_path, settings.models_dir),
            "ollama": OllamaProvider(),
            "gemini": GeminiProvider(gemini_api_key),
            "lm_studio": OpenAICompatibleProvider(
                "lm_studio",
                "LM Studio",
                "http://127.0.0.1:1234",
                "Not detected. Start LM Studio's local API server to connect.",
            ),
        }
        self.providers["lm_studio"].license_name = "Proprietary desktop / MIT SDKs"  # type: ignore[attr-defined]
        self.semaphore = asyncio.Semaphore(1)

    async def statuses(self) -> list[ProviderStatus]:
        return list(await asyncio.gather(*(provider.status() for provider in self.providers.values())))

    async def models(self, provider_id: str | None = None) -> list[ModelDescriptor]:
        selected = (
            [self.get(provider_id)] if provider_id else list(self.providers.values())
        )
        results = await asyncio.gather(*(provider.models() for provider in selected))
        return [model for group in results for model in group]

    def get(self, provider_id: str) -> InferenceProvider:
        try:
            return self.providers[provider_id]
        except KeyError as error:
            raise ValueError(f"Unknown inference provider: {provider_id}") from error

    def refresh_llama_cpp(self, settings: Settings) -> None:
        provider = self.providers["llama_cpp"]
        provider.executable = settings.llama_server_path  # type: ignore[attr-defined]

    async def close(self) -> None:
        await asyncio.gather(*(provider.close() for provider in self.providers.values()))
