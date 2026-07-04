from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    instructions_enc TEXT NOT NULL,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    spec_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_skills (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    content_enc TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(agent_id, name),
                    FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_enc TEXT NOT NULL,
                    output_enc TEXT,
                    state_enc TEXT NOT NULL,
                    error TEXT,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS run_attachments (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    data_enc TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS benchmarks (
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    tokens_per_second REAL,
                    first_token_ms REAL,
                    structured_output_ok INTEGER NOT NULL DEFAULT 0,
                    tool_calling_ok INTEGER NOT NULL DEFAULT 0,
                    measured_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    interval_minutes INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_run_at TEXT NOT NULL,
                    input_enc TEXT NOT NULL,
                    FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_runs_workflow_status ON runs(workflow_id, status);
                CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_run_attachments_run ON run_attachments(run_id);
                CREATE INDEX IF NOT EXISTS idx_agent_skills_agent ON agent_skills(agent_id);
                """
            )

    def setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (key, json.dumps(value), utc_now()),
            )

    def rows(self, query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, parameters).fetchall()]

    def row(self, query: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as db:
            result = db.execute(query, parameters).fetchone()
            return dict(result) if result else None

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> None:
        with self._lock, self.connect() as db:
            db.execute(query, parameters)
