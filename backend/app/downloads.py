from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx


@dataclass(slots=True)
class DownloadState:
    id: str
    url: str
    destination: str
    expected_sha256: str | None
    status: str = "queued"
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    error: str | None = None


class DownloadManager:
    def __init__(self) -> None:
        self.states: dict[str, DownloadState] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, url: str, destination: Path, sha256: str | None = None) -> DownloadState:
        identifier = uuid.uuid4().hex
        state = DownloadState(identifier, url, str(destination), sha256)
        self.states[identifier] = state
        self.tasks[identifier] = asyncio.create_task(self._download(state))
        return state

    async def _download(self, state: DownloadState) -> None:
        destination = Path(state.destination)
        partial = destination.with_suffix(destination.suffix + ".partial")
        partial.parent.mkdir(parents=True, exist_ok=True)
        existing = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        state.downloaded_bytes = existing
        state.status = "downloading"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
                async with client.stream("GET", state.url, headers=headers) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    state.total_bytes = existing + int(content_length) if content_length else None
                    mode = "ab" if response.status_code == 206 and existing else "wb"
                    if mode == "wb":
                        state.downloaded_bytes = 0
                    with partial.open(mode) as output:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            output.write(chunk)
                            state.downloaded_bytes += len(chunk)
            if state.expected_sha256:
                digest = hashlib.sha256()
                with partial.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest().lower() != state.expected_sha256.lower():
                    raise ValueError("Downloaded file did not match the expected SHA-256 hash")
            partial.replace(destination)
            state.status = "complete"
        except asyncio.CancelledError:
            state.status = "paused"
        except Exception as error:
            state.status = "failed"
            state.error = str(error)

    def pause(self, identifier: str) -> DownloadState:
        task = self.tasks.get(identifier)
        if task and not task.done():
            task.cancel()
        return self.states[identifier]

    def serialized(self, identifier: str | None = None) -> list[dict[str, object]]:
        states = [self.states[identifier]] if identifier else list(self.states.values())
        return [asdict(state) for state in states]
