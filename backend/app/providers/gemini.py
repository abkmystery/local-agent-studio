from __future__ import annotations

from typing import Any

import httpx

from ..schemas import ModelDescriptor, ProviderStatus
from .base import ChatResult, InferenceProvider


class GeminiProvider(InferenceProvider):
    id = "gemini"
    name = "Gemini 3.5 Flash"
    cloud = True
    model_id = "gemini-3.5-flash"
    interactions_url = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10.0))

    def configure(self, api_key: str | None) -> None:
        self.api_key = api_key.strip() if api_key else None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("Gemini is not connected. Add an API key in setup or Settings.")
        return {"x-goog-api-key": self.api_key, "content-type": "application/json"}

    async def verify(self) -> None:
        response = await self.client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers=self._headers(),
        )
        if response.status_code in {401, 403}:
            raise ValueError("Google rejected this API key. Create a new Gemini API key in Google AI Studio.")
        response.raise_for_status()
        available = {item.get("name", "").removeprefix("models/") for item in response.json().get("models", [])}
        if self.model_id not in available:
            raise ValueError("This Google project does not currently have access to Gemini 3.5 Flash.")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            id=self.id,
            name=self.name,
            kind="external",
            available=self.configured,
            base_url="https://generativelanguage.googleapis.com",
            detail=(
                "Connected through your encrypted Google AI Studio key."
                if self.configured else
                "Optional cloud provider. Connect a Google AI Studio key only if you choose it."
            ),
            license_name="Google Gemini API terms",
            redistributable=False,
        )

    async def models(self) -> list[ModelDescriptor]:
        if not self.configured:
            return []
        return [
            ModelDescriptor(
                id=self.model_id,
                name="Gemini 3.5 Flash",
                provider_id=self.id,
                publisher="Google",
                source_url="https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash",
                license_name="Google Gemini API terms",
                license_url="https://ai.google.dev/gemini-api/terms",
                commercial_use=None,
                redistribution=False,
                context_length=1_048_576,
                capabilities=["chat", "structured_output", "tool_use", "vision", "cloud"],
                installed=True,
                loaded=True,
            )
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
        if model != self.model_id:
            raise ValueError(f"Unsupported Gemini model: {model}")
        system_instruction = "\n\n".join(
            str(message.get("content", "")) for message in messages if message.get("role") == "system"
        )
        conversation = "\n\n".join(
            f"{str(message.get('role', 'user')).capitalize()}: {message.get('content', '')}"
            for message in messages if message.get("role") != "system"
        )
        generation = options or {}
        attachments = [
            attachment for message in messages for attachment in message.get("attachments", [])
            if str(attachment.get("media_type", "")).startswith("image/")
        ]
        interaction_input: str | list[dict[str, Any]] = conversation
        if attachments:
            interaction_input = [{"type": "text", "text": conversation}] + [
                {
                    "type": "image", "data": item["data_base64"],
                    "mime_type": item["media_type"],
                }
                for item in attachments
            ]
        body: dict[str, Any] = {
            "model": model,
            "input": interaction_input,
            "store": False,
            "generation_config": {
                "temperature": float(generation.get("temperature", 0.2)),
                "max_output_tokens": int(generation.get("num_predict", generation.get("max_tokens", 256))),
                "thinking_level": "low",
                "thinking_summaries": "none",
            },
        }
        if system_instruction:
            body["system_instruction"] = system_instruction
        if tools:
            allowed_builtin_tools = [tool for tool in tools if tool.get("type") == "google_search"]
            if allowed_builtin_tools:
                body["tools"] = allowed_builtin_tools
        if response_format:
            body["response_format"] = response_format
        response = await self.client.post(self.interactions_url, headers=self._headers(), json=body)
        if response.status_code == 429:
            raise RuntimeError("Gemini's current project quota is exhausted. Check live limits in Google AI Studio or try later.")
        if response.status_code in {401, 403}:
            raise RuntimeError("Gemini authentication failed. Reconnect the API key in Settings.")
        response.raise_for_status()
        payload = response.json()
        text_parts = [
            str(block.get("text", ""))
            for step in payload.get("steps", []) if step.get("type") == "model_output"
            for block in step.get("content", []) if block.get("type") == "text"
        ]
        usage = payload.get("usage", {})
        return ChatResult(
            content="".join(text_parts),
            prompt_tokens=int(usage.get("total_input_tokens", 0)),
            completion_tokens=int(usage.get("total_output_tokens", 0)),
        )

    async def close(self) -> None:
        await self.client.aclose()
