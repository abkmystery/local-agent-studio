from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 7331
    data_dir: Path = Path.home() / ".local-agent-studio"
    runtime_dir: Path | None = None
    auth_token: str = "development-token"

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "studio.db"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def llama_server_path(self) -> Path | None:
        candidates: list[Path] = []
        candidates.extend(
            [
                self.data_dir / "runtimes" / "llama.cpp" / "llama-server.exe",
                self.data_dir / "runtimes" / "llama.cpp" / "llama-server",
            ]
        )
        if self.runtime_dir:
            candidates.extend(
                [
                    self.runtime_dir / "llama.cpp" / "llama-server.exe",
                    self.runtime_dir / "llama.cpp" / "llama-server",
                ]
            )
        candidates.extend(
            [
                Path.cwd() / "vendor" / "llama.cpp" / "llama-server.exe",
                Path.cwd() / "vendor" / "llama.cpp" / "llama-server",
            ]
        )
        return next((candidate for candidate in candidates if candidate.exists()), None)
