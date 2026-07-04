from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..schemas import ModelDescriptor, ProviderStatus


@dataclass(slots=True)
class ChatResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class InferenceProvider(ABC):
    id: str
    name: str

    @abstractmethod
    async def status(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    async def models(self) -> list[ModelDescriptor]:
        raise NotImplementedError

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> ChatResult:
        raise NotImplementedError

    async def unload(self, model: str) -> None:
        del model

    async def close(self) -> None:
        return None
