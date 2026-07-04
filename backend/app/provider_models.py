from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class ProviderModelInstall:
    id: str
    provider_id: str
    model_id: str
    display_name: str
    status: str = "queued"
    progress: float = 0.0
    detail: str = "Preparing download…"
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    error: str | None = None


class StarterModelInstaller:
    OLLAMA_MODEL = "qwen2.5:0.5b"
    LM_REPOSITORY = "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"

    def __init__(self) -> None:
        self.states: dict[str, ProviderModelInstall] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, provider_id: str) -> ProviderModelInstall:
        if provider_id not in {"ollama", "lm_studio"}:
            raise ValueError("Automatic starter installation is available for Ollama and LM Studio only")
        for state in self.states.values():
            if state.provider_id == provider_id and state.status in {"queued", "downloading"}:
                return state
        state = ProviderModelInstall(
            id=uuid.uuid4().hex,
            provider_id=provider_id,
            model_id=self.OLLAMA_MODEL if provider_id == "ollama" else "qwen2.5-0.5b-instruct-q4_k_m",
            display_name="Qwen 2.5 0.5B Quick Start",
        )
        self.states[state.id] = state
        task = self._pull_ollama(state) if provider_id == "ollama" else self._download_lm_studio(state)
        self.tasks[state.id] = asyncio.create_task(task)
        return state

    def serialized(self) -> list[dict[str, Any]]:
        return [asdict(state) for state in self.states.values()]

    async def _pull_ollama(self, state: ProviderModelInstall) -> None:
        state.status = "downloading"
        state.detail = "Ollama is downloading Qwen 2.5 0.5B…"
        try:
            timeout = httpx.Timeout(None, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", "http://127.0.0.1:11434/api/pull",
                    json={"model": self.OLLAMA_MODEL, "stream": True},
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        payload = json.loads(line)
                        state.detail = str(payload.get("status", state.detail)).capitalize()
                        if payload.get("total"):
                            state.total_bytes = int(payload["total"])
                            state.downloaded_bytes = int(payload.get("completed", 0))
                            state.progress = min(1.0, state.downloaded_bytes / state.total_bytes)
            state.status = "complete"
            state.progress = 1.0
            state.detail = "Qwen 2.5 0.5B is ready in Ollama."
        except Exception as error:
            state.status = "failed"
            state.error = str(error)
            state.detail = "Ollama model installation failed."

    async def _download_lm_studio(self, state: ProviderModelInstall) -> None:
        state.status = "downloading"
        state.detail = "LM Studio is downloading Qwen 2.5 0.5B…"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5.0)) as client:
                response = await client.post(
                    "http://127.0.0.1:1234/api/v1/models/download",
                    json={"model": self.LM_REPOSITORY, "quantization": "Q4_K_M"},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") == "already_downloaded":
                    state.status = "complete"
                    state.progress = 1.0
                    state.detail = "Qwen 2.5 0.5B is already available in LM Studio."
                    return
                job_id = str(payload.get("job_id", ""))
                if not job_id:
                    raise RuntimeError("LM Studio did not return a download job")
                while True:
                    await asyncio.sleep(1)
                    response = await client.get(
                        f"http://127.0.0.1:1234/api/v1/models/download/status/{job_id}"
                    )
                    response.raise_for_status()
                    payload = response.json()
                    state.detail = f"LM Studio: {str(payload.get('status', 'downloading')).replace('_', ' ')}"
                    state.downloaded_bytes = int(payload.get("downloaded_bytes", 0))
                    state.total_bytes = int(payload["total_size_bytes"]) if payload.get("total_size_bytes") else None
                    if state.total_bytes:
                        state.progress = min(1.0, state.downloaded_bytes / state.total_bytes)
                    if payload.get("status") == "completed":
                        state.status = "complete"
                        state.progress = 1.0
                        state.detail = "Qwen 2.5 0.5B is ready in LM Studio."
                        return
                    if payload.get("status") == "failed":
                        raise RuntimeError(str(payload.get("error", "LM Studio download failed")))
        except Exception as error:
            state.status = "failed"
            state.error = str(error)
            state.detail = "LM Studio model installation failed."
