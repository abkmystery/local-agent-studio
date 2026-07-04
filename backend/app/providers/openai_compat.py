from __future__ import annotations

from typing import Any

import httpx

from ..schemas import ModelDescriptor, ProviderStatus
from .base import ChatResult, InferenceProvider


class OpenAICompatibleProvider(InferenceProvider):
    kind = "external"
    license_name = "External runtime"
    redistributable = False

    def __init__(self, provider_id: str, name: str, base_url: str, detail: str) -> None:
        self.id = provider_id
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.detail = detail
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=1.0))

    async def status(self) -> ProviderStatus:
        try:
            response = await self.client.get(f"{self.base_url}/v1/models", timeout=3.0)
            available = response.status_code == 200
            detail = self.detail if available else f"API returned HTTP {response.status_code}"
        except (httpx.HTTPError, OSError):
            available = False
            detail = self.detail
        return ProviderStatus(
            id=self.id,
            name=self.name,
            kind=self.kind,
            available=available,
            base_url=self.base_url,
            detail=detail,
            license_name=self.license_name,
            redistributable=self.redistributable,
        )

    async def models(self) -> list[ModelDescriptor]:
        try:
            response = await self.client.get(f"{self.base_url}/v1/models", timeout=3.0)
            response.raise_for_status()
        except (httpx.HTTPError, OSError):
            return []
        payload = response.json()
        return [
            ModelDescriptor(
                id=item.get("id", "unknown"),
                name=item.get("id", "Unknown model"),
                provider_id=self.id,
                publisher=item.get("owned_by", "Local"),
                capabilities=["chat", "structured_output", "tool_use"],
                installed=True,
            )
            for item in payload.get("data", [])
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
            attachments = [
                item for item in message.get("attachments", [])
                if str(item.get("media_type", "")).startswith("image/")
            ]
            if attachments:
                content: list[dict[str, Any]] = [{"type": "text", "text": str(message.get("content", ""))}]
                content.extend({
                    "type": "image_url",
                    "image_url": {"url": f"data:{item['media_type']};base64,{item['data_base64']}"},
                } for item in attachments)
                normalized_messages.append({"role": message.get("role", "user"), "content": content})
            else:
                normalized_messages.append({key: value for key, value in message.items() if key != "attachments"})
        body: dict[str, Any] = {"model": model, "messages": normalized_messages, "stream": False}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if response_format:
            body["response_format"] = response_format
        if options:
            body.update({key: value for key, value in options.items() if key in {"temperature", "max_tokens"}})
            if "num_predict" in options:
                body["max_tokens"] = options["num_predict"]
        response = await self.client.post(f"{self.base_url}/v1/chat/completions", json=body)
        response.raise_for_status()
        payload = response.json()
        message = payload["choices"][0]["message"]
        usage = payload.get("usage", {})
        return ChatResult(
            content=message.get("content") or "",
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            tool_calls=message.get("tool_calls") or [],
        )

    async def close(self) -> None:
        await self.client.aclose()
