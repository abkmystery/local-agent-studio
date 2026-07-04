from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from .db import Database
from .security import SecretBox
from .workflows import WorkflowEngine


class LocalScheduler:
    def __init__(self, database: Database, secrets: SecretBox, engine: WorkflowEngine) -> None:
        self.database = database
        self.secrets = secrets
        self.engine = engine
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(UTC)
            due = self.database.rows(
                "SELECT * FROM schedules WHERE enabled=1 AND next_run_at<=?", (now.isoformat(),)
            )
            for schedule in due:
                input_text = self.secrets.decrypt(schedule["input_enc"]) or ""
                self.engine.start(schedule["workflow_id"], input_text)
                next_run = now + timedelta(minutes=int(schedule["interval_minutes"]))
                self.database.execute(
                    "UPDATE schedules SET next_run_at=? WHERE id=?", (next_run.isoformat(), schedule["id"])
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=15)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    def list(self) -> list[dict[str, object]]:
        rows = self.database.rows("SELECT id,workflow_id,interval_minutes,enabled,next_run_at FROM schedules")
        for row in rows:
            row["enabled"] = bool(row["enabled"])
        return rows

    def create(self, workflow_id: str, interval_minutes: int, input_text: str, enabled: bool) -> dict[str, object]:
        identifier = uuid.uuid4().hex
        next_run = datetime.now(UTC) + timedelta(minutes=interval_minutes)
        self.database.execute(
            "INSERT INTO schedules(id,workflow_id,interval_minutes,enabled,next_run_at,input_enc) VALUES(?,?,?,?,?,?)",
            (identifier, workflow_id, interval_minutes, int(enabled), next_run.isoformat(), self.secrets.encrypt(input_text)),
        )
        return next(item for item in self.list() if item["id"] == identifier)
