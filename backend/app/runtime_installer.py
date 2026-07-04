from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import httpx

from .config import Settings
from .hardware import hardware_assessment


@dataclass(slots=True)
class RuntimeInstallState:
    status: str = "idle"
    progress: float = 0
    detail: str = "Built-in runtime is not installed."
    version: str | None = None
    asset: str | None = None
    error: str | None = None


class LlamaRuntimeInstaller:
    RELEASE_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

    def __init__(self, settings: Settings, on_complete=None) -> None:
        self.settings = settings
        self.on_complete = on_complete
        self.state = RuntimeInstallState(
            status="ready" if settings.llama_server_path else "idle",
            progress=1 if settings.llama_server_path else 0,
            detail="Built-in llama.cpp is ready." if settings.llama_server_path else "Built-in runtime is not installed.",
        )
        self.task: asyncio.Task[None] | None = None

    def serialized(self) -> dict[str, object]:
        return asdict(self.state)

    def start(self) -> dict[str, object]:
        if self.task and not self.task.done():
            return self.serialized()
        self.state = RuntimeInstallState(status="discovering", detail="Finding the verified llama.cpp release…")
        self.task = asyncio.create_task(self._install())
        return self.serialized()

    async def _install(self) -> None:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(300, connect=15),
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Local-Agent-Studio"},
            ) as client:
                release_response = await client.get(self.RELEASE_API)
                release_response.raise_for_status()
                release = release_response.json()
                asset = self._select_asset(release.get("assets", []))
                digest_value = str(asset.get("digest") or "")
                if not digest_value.startswith("sha256:"):
                    raise RuntimeError("The official release did not publish a SHA-256 digest; automatic installation was stopped.")
                expected = digest_value.split(":", 1)[1]
                self.state.version = release.get("tag_name")
                self.state.asset = asset["name"]
                self.state.status = "downloading"
                self.state.detail = f"Downloading {asset['name']} from the official llama.cpp release…"
                runtime_root = self.settings.data_dir / "runtimes"
                runtime_root.mkdir(parents=True, exist_ok=True)
                archive_path = runtime_root / "llama.cpp.download.zip"
                async with client.stream("GET", asset["browser_download_url"]) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length", 0))
                    downloaded = 0
                    digest = hashlib.sha256()
                    with archive_path.open("wb") as output:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            output.write(chunk)
                            digest.update(chunk)
                            downloaded += len(chunk)
                            self.state.progress = downloaded / total if total else 0
                if digest.hexdigest().lower() != expected.lower():
                    archive_path.unlink(missing_ok=True)
                    raise RuntimeError("Runtime download failed SHA-256 verification")
                self.state.status = "installing"
                self.state.detail = "Installing the verified local runtime…"
                with tempfile.TemporaryDirectory(dir=runtime_root) as temporary:
                    extracted = Path(temporary)
                    self._safe_extract(archive_path, extracted)
                    server = next(extracted.rglob("llama-server.exe"), None)
                    if not server:
                        raise RuntimeError("The verified release did not contain llama-server.exe")
                    target = runtime_root / "llama.cpp"
                    staging = runtime_root / "llama.cpp.new"
                    if staging.exists():
                        shutil.rmtree(staging)
                    shutil.copytree(server.parent, staging)
                    old = runtime_root / "llama.cpp.old"
                    if old.exists():
                        shutil.rmtree(old)
                    if target.exists():
                        target.replace(old)
                    staging.replace(target)
                    if old.exists():
                        shutil.rmtree(old)
                archive_path.unlink(missing_ok=True)
                metadata = {
                    "version": self.state.version,
                    "asset": self.state.asset,
                    "sha256": expected,
                    "source": release.get("html_url"),
                }
                (runtime_root / "llama.cpp" / "runtime-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                self.state.status = "ready"
                self.state.progress = 1
                self.state.detail = "Built-in llama.cpp is ready."
                if self.on_complete:
                    self.on_complete()
        except asyncio.CancelledError:
            self.state.status = "paused"
            self.state.detail = "Runtime installation was paused."
        except Exception as error:
            self.state.status = "failed"
            self.state.error = str(error)
            self.state.detail = "Runtime installation failed safely; no unverified binary was installed."

    def _select_asset(self, assets: list[dict[str, object]]) -> dict[str, object]:
        names = [(str(asset.get("name", "")).lower(), asset) for asset in assets]
        self.settings.models_dir.mkdir(parents=True, exist_ok=True)
        hardware = hardware_assessment(self.settings.models_dir)
        has_gpu = bool(hardware.get("gpus"))
        priorities = ["bin-win-vulkan-x64.zip", "bin-win-cpu-x64.zip"] if has_gpu else ["bin-win-cpu-x64.zip", "bin-win-vulkan-x64.zip"]
        for suffix in priorities:
            matches = [asset for name, asset in names if name.endswith(suffix) and "cudart" not in name]
            if matches:
                return matches[0]
        raise RuntimeError("No compatible verified Windows x64 llama.cpp runtime was found")

    def _safe_extract(self, archive_path: Path, destination: Path) -> None:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("Runtime archive contained an unsafe path")
            archive.extractall(destination)
