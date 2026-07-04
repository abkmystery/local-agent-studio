from __future__ import annotations

import asyncio
import os
import socket
import subprocess
from pathlib import Path
from typing import Any

from ..schemas import ModelDescriptor, ProviderStatus
from .base import ChatResult
from .openai_compat import OpenAICompatibleProvider


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LlamaCppProvider(OpenAICompatibleProvider):
    kind = "embedded"
    license_name = "MIT"
    redistributable = True

    def __init__(self, executable: Path | None, models_dir: Path) -> None:
        self.executable = executable
        self.models_dir = models_dir
        self.process: subprocess.Popen[bytes] | None = None
        self.loaded_model: str | None = None
        self.port = _free_port()
        self._process_lock = asyncio.Lock()
        super().__init__(
            "llama_cpp",
            "Built-in llama.cpp",
            f"http://127.0.0.1:{self.port}",
            "Runtime pack is not installed yet.",
        )

    async def status(self) -> ProviderStatus:
        binary_ready = self.executable is not None
        running = self.process is not None and self.process.poll() is None
        return ProviderStatus(
            id=self.id,
            name=self.name,
            kind="embedded",
            available=binary_ready,
            base_url=self.base_url,
            detail=(
                f"Running {self.loaded_model}" if running else
                "Ready; choose a GGUF model." if binary_ready else
                "The llama.cpp runtime pack has not been added to this build."
            ),
            license_name="MIT",
            redistributable=True,
        )

    async def models(self) -> list[ModelDescriptor]:
        models: list[ModelDescriptor] = []
        for model in sorted(self.models_dir.glob("*.gguf")):
            models.append(
                ModelDescriptor(
                    id=model.name,
                    name=model.stem,
                    provider_id=self.id,
                    publisher="Local GGUF",
                    source_url=model.as_uri(),
                    license_name="Review source metadata",
                    size_bytes=model.stat().st_size,
                    memory_estimate_bytes=int(model.stat().st_size * 1.2),
                    capabilities=["chat", "structured_output"],
                    installed=True,
                    loaded=self.loaded_model == model.name,
                )
            )
        return models

    async def _ensure_started(self, model: str, context_length: int = 4096) -> None:
        if self.executable is None:
            raise RuntimeError("llama.cpp runtime is not installed")
        model_path = (self.models_dir / model).resolve()
        if not model_path.is_file() or model_path.parent != self.models_dir.resolve():
            raise ValueError("The selected GGUF model is not in the managed model directory")
        async with self._process_lock:
            if self.process and self.process.poll() is None and self.loaded_model == model:
                return
            if self.process and self.process.poll() is None:
                self.process.terminate()
                await asyncio.to_thread(self.process.wait, 10)
            context_length = max(512, min(context_length, 4096))
            threads = max(1, (os.cpu_count() or 4) - 2)
            self.process = subprocess.Popen(
                [
                    str(self.executable), "-m", str(model_path), "--host", "127.0.0.1",
                    "--port", str(self.port), "-c", str(context_length),
                    "--threads", str(threads), "--threads-batch", str(threads),
                    "--parallel", "1", "--no-webui",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.loaded_model = model
            for _ in range(120):
                if self.process.poll() is not None:
                    raise RuntimeError("llama.cpp stopped while loading the model")
                try:
                    response = await self.client.get(f"{self.base_url}/health")
                    if response.status_code == 200:
                        return
                except Exception:
                    pass
                await asyncio.sleep(0.25)
            raise TimeoutError("llama.cpp did not become ready")

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> ChatResult:
        await self._ensure_started(model, int((options or {}).get("num_ctx", 4096)))
        return await super().chat(
            model,
            messages,
            tools=tools,
            response_format=response_format,
            options=options,
        )

    async def unload(self, model: str) -> None:
        if self.process and self.process.poll() is None and self.loaded_model == model:
            self.process.terminate()
            await asyncio.to_thread(self.process.wait, 10)
            self.loaded_model = None

    async def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
        await super().close()
