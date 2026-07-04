from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import httpx

from ..schemas import ModelDescriptor, ProviderStatus
from .base import ChatResult, InferenceProvider


class OllamaProvider(InferenceProvider):
    id = "ollama"
    name = "Ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=1.0))

    async def status(self) -> ProviderStatus:
        try:
            response = await self.client.get(f"{self.base_url}/api/tags", timeout=3.0)
            available = response.status_code == 200
        except (httpx.HTTPError, OSError):
            available = False
        installed = bool(
            shutil.which("ollama")
            or (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe").is_file()
        )
        return ProviderStatus(
            id=self.id,
            name=self.name,
            kind="external",
            available=available,
            base_url=self.base_url,
            detail=(
                "Ready"
                if available else
                "Ollama is installed, but its local service is not responding. Open Ollama and refresh."
                if installed else
                "Ollama is not installed. Use the official installer to add it."
            ),
            license_name="MIT",
            redistributable=True,
        )

    async def models(self) -> list[ModelDescriptor]:
        try:
            response = await self.client.get(f"{self.base_url}/api/tags", timeout=3.0)
            response.raise_for_status()
        except (httpx.HTTPError, OSError):
            return []
        return [
            ModelDescriptor(
                id=item["name"],
                name=item["name"],
                provider_id=self.id,
                publisher="Ollama library",
                quantization=item.get("details", {}).get("quantization_level"),
                size_bytes=item.get("size"),
                capabilities=["chat", "structured_output", "tool_use"],
                installed=True,
            )
            for item in response.json().get("models", [])
        ]

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> ChatResult:
        normalized_messages = []
        for message in messages:
            normalized = {key: value for key, value in message.items() if key != "attachments"}
            images = [
                item["data_base64"] for item in message.get("attachments", [])
                if str(item.get("media_type", "")).startswith("image/")
            ]
            if images:
                normalized["images"] = images
            normalized_messages.append(normalized)
        body: dict[str, Any] = {
            "model": model,
            "messages": normalized_messages,
            "stream": False,
            "keep_alive": "5m",
            "options": options or {},
        }
        if tools:
            body["tools"] = [tool.get("function", tool) for tool in tools]
        if response_format:
            body["format"] = response_format.get("json_schema", response_format)
        response = await self.client.post(f"{self.base_url}/api/chat", json=body)
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message", {})
        return ChatResult(
            content=message.get("content", ""),
            prompt_tokens=int(payload.get("prompt_eval_count", 0)),
            completion_tokens=int(payload.get("eval_count", 0)),
            tool_calls=message.get("tool_calls") or [],
        )

    async def unload(self, model: str) -> None:
        try:
            await self.client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "prompt": "", "keep_alive": 0},
            )
        except httpx.HTTPError:
            pass

    async def close(self) -> None:
        await self.client.aclose()
