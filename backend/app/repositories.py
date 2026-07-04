from __future__ import annotations

import json
import uuid
from typing import Any

from .db import Database, utc_now
from .schemas import Agent, AgentInput, AgentSkill, Workflow, WorkflowInput
from .security import SecretBox


class Repositories:
    def __init__(self, database: Database, secrets: SecretBox) -> None:
        self.db = database
        self.secrets = secrets

    def list_agents(self) -> list[Agent]:
        return [self._agent(row) for row in self.db.rows("SELECT * FROM agents ORDER BY updated_at DESC")]

    def get_agent(self, identifier: str) -> Agent | None:
        row = self.db.row("SELECT * FROM agents WHERE id=?", (identifier,))
        return self._agent(row) if row else None

    def save_agent(self, value: AgentInput, identifier: str | None = None) -> Agent:
        now = utc_now()
        identifier = identifier or uuid.uuid4().hex
        current = self.db.row("SELECT created_at FROM agents WHERE id=?", (identifier,))
        created = current["created_at"] if current else now
        self.db.execute(
            """INSERT INTO agents(id,name,description,provider_id,model_id,instructions_enc,config_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,
                 provider_id=excluded.provider_id,model_id=excluded.model_id,
                 instructions_enc=excluded.instructions_enc,config_json=excluded.config_json,
                 updated_at=excluded.updated_at""",
            (
                identifier, value.name, value.description, value.provider_id, value.model_id,
                self.secrets.encrypt(value.instructions), json.dumps(value.config), created, now,
            ),
        )
        return self.get_agent(identifier)  # type: ignore[return-value]

    def delete_agent(self, identifier: str) -> None:
        self.db.execute("DELETE FROM agents WHERE id=?", (identifier,))

    def workflows_using_agent(self, identifier: str) -> list[str]:
        names: list[str] = []
        for workflow in self.list_workflows():
            if any(
                node.config.get("agent_id") == identifier or node.config.get("reviewer_agent_id") == identifier
                for node in workflow.spec.nodes
            ):
                names.append(workflow.name)
        return names

    def list_agent_skills(self, agent_id: str) -> list[AgentSkill]:
        return [
            AgentSkill.model_validate(row)
            for row in self.db.rows(
                "SELECT id,agent_id,name,media_type,size_bytes,created_at "
                "FROM agent_skills WHERE agent_id=? ORDER BY name",
                (agent_id,),
            )
        ]

    def save_agent_skill(self, agent_id: str, name: str, media_type: str, content: str) -> AgentSkill:
        now = utc_now()
        identifier = uuid.uuid4().hex
        size_bytes = len(content.encode("utf-8"))
        self.db.execute(
            """INSERT INTO agent_skills(id,agent_id,name,media_type,content_enc,size_bytes,created_at)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(agent_id,name) DO UPDATE SET
               id=excluded.id,media_type=excluded.media_type,content_enc=excluded.content_enc,
               size_bytes=excluded.size_bytes,created_at=excluded.created_at""",
            (identifier, agent_id, name, media_type, self.secrets.encrypt(content), size_bytes, now),
        )
        row = self.db.row(
            "SELECT id,agent_id,name,media_type,size_bytes,created_at FROM agent_skills WHERE agent_id=? AND name=?",
            (agent_id, name),
        )
        return AgentSkill.model_validate(row)

    def delete_agent_skill(self, agent_id: str, identifier: str) -> bool:
        existing = self.db.row(
            "SELECT id FROM agent_skills WHERE id=? AND agent_id=?", (identifier, agent_id)
        )
        if not existing:
            return False
        self.db.execute("DELETE FROM agent_skills WHERE id=? AND agent_id=?", (identifier, agent_id))
        return True

    def agent_skill_context(self, agent_id: str, limit: int = 8_000) -> str:
        rows = self.db.rows(
            "SELECT name,content_enc FROM agent_skills WHERE agent_id=? ORDER BY name", (agent_id,)
        )
        chunks: list[str] = []
        remaining = limit
        for row in rows:
            content = self.secrets.decrypt(row["content_enc"]) or ""
            header = f"\n--- Skill file: {row['name']} ---\n"
            if remaining <= len(header):
                break
            excerpt = content[: max(0, remaining - len(header))]
            chunks.append(header + excerpt)
            remaining -= len(header) + len(excerpt)
            if len(excerpt) < len(content):
                chunks.append("\n[Additional skill content omitted to preserve model context.]\n")
                break
        return "".join(chunks)

    def _agent(self, row: dict[str, Any]) -> Agent:
        return Agent(
            id=row["id"], name=row["name"], description=row["description"],
            provider_id=row["provider_id"], model_id=row["model_id"],
            instructions=self.secrets.decrypt(row["instructions_enc"]) or "",
            config=json.loads(row["config_json"]), created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_workflows(self) -> list[Workflow]:
        return [self._workflow(row) for row in self.db.rows("SELECT * FROM workflows ORDER BY updated_at DESC")]

    def get_workflow(self, identifier: str) -> Workflow | None:
        row = self.db.row("SELECT * FROM workflows WHERE id=?", (identifier,))
        return self._workflow(row) if row else None

    def save_workflow(self, value: WorkflowInput, identifier: str | None = None) -> Workflow:
        now = utc_now()
        identifier = identifier or uuid.uuid4().hex
        current = self.db.row("SELECT created_at FROM workflows WHERE id=?", (identifier,))
        created = current["created_at"] if current else now
        self.db.execute(
            """INSERT INTO workflows(id,name,description,spec_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,
               description=excluded.description,spec_json=excluded.spec_json,updated_at=excluded.updated_at""",
            (identifier, value.name, value.description, value.spec.model_dump_json(), created, now),
        )
        return self.get_workflow(identifier)  # type: ignore[return-value]

    def delete_workflow(self, identifier: str) -> None:
        self.db.execute("DELETE FROM workflows WHERE id=?", (identifier,))

    def workflow_has_active_runs(self, identifier: str) -> bool:
        return self.db.row(
            "SELECT 1 AS active FROM runs WHERE workflow_id=? AND status IN ('queued','running','waiting_approval') LIMIT 1",
            (identifier,),
        ) is not None

    def _workflow(self, row: dict[str, Any]) -> Workflow:
        return Workflow(
            id=row["id"], name=row["name"], description=row["description"],
            spec=json.loads(row["spec_json"]), created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.rows("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))
        return [self._run(row) for row in rows]

    def get_run(self, identifier: str, *, include_private: bool = False) -> dict[str, Any] | None:
        row = self.db.row("SELECT * FROM runs WHERE id=?", (identifier,))
        return self._run(row, include_private=include_private) if row else None

    def create_run(
        self, workflow_id: str, input_text: str, initial_state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        identifier = uuid.uuid4().hex
        now = utc_now()
        state = dict(initial_state or {"level": 0, "results": {}, "inactive_edges": []})
        attachments = list(state.pop("attachments", []))
        self.db.execute(
            "INSERT INTO runs(id,workflow_id,status,input_enc,state_enc,started_at) VALUES(?,?,?,?,?,?)",
            (
                identifier, workflow_id, "queued", self.secrets.encrypt(input_text),
                self.secrets.encrypt(json.dumps(state)), now,
            ),
        )
        for attachment in attachments:
            data = str(attachment.get("data_base64", ""))
            self.db.execute(
                "INSERT INTO run_attachments(id,run_id,name,media_type,size_bytes,data_enc) VALUES(?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex, identifier, str(attachment.get("name", "attachment"))[:255],
                    str(attachment.get("media_type", "application/octet-stream"))[:120],
                    int(attachment.get("size_bytes", 0)), self.secrets.encrypt(data),
                ),
            )
        return self.get_run(identifier)  # type: ignore[return-value]

    def update_run(self, identifier: str, **changes: Any) -> None:
        allowed = {
            "status", "output", "state", "error", "prompt_tokens", "completion_tokens", "finished_at"
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            column = {"output": "output_enc", "state": "state_enc"}.get(key, key)
            if key in {"output", "state"} and value is not None:
                if key == "state" and isinstance(value, dict):
                    value = {item_key: item_value for item_key, item_value in value.items() if item_key != "attachments"}
                value = self.secrets.encrypt(value if isinstance(value, str) else json.dumps(value))
            assignments.append(f"{column}=?")
            values.append(value)
        if assignments:
            values.append(identifier)
            self.db.execute(f"UPDATE runs SET {','.join(assignments)} WHERE id=?", tuple(values))

    def _run(self, row: dict[str, Any], *, include_private: bool = False) -> dict[str, Any]:
        state_raw = self.secrets.decrypt(row["state_enc"]) or "{}"
        state = json.loads(state_raw)
        attachments = self.db.rows(
            "SELECT id,name,media_type,size_bytes,data_enc FROM run_attachments WHERE run_id=? ORDER BY id",
            (row["id"],),
        )
        state["attachments"] = [
            {
                "id": item["id"], "name": item["name"], "media_type": item["media_type"],
                "size_bytes": item["size_bytes"],
                **({"data_base64": self.secrets.decrypt(item["data_enc"]) or ""} if include_private else {}),
            }
            for item in attachments
        ]
        return {
            "id": row["id"], "workflow_id": row["workflow_id"], "status": row["status"],
            "input": self.secrets.decrypt(row["input_enc"]) or "",
            "output": self.secrets.decrypt(row["output_enc"]),
            "state": state, "error": row["error"],
            "prompt_tokens": row["prompt_tokens"], "completion_tokens": row["completion_tokens"],
            "started_at": row["started_at"], "finished_at": row["finished_at"],
        }
