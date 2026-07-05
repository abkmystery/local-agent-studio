from __future__ import annotations

import json
import io
import smtplib
import sys
import time
import zipfile
from pathlib import Path

import pytest
import httpx
from fastapi.testclient import TestClient

from backend.app.agentpacks import export_agentpack
from backend.app.config import Settings
from backend.app.db import Database
from backend.app.main import create_app
from backend.app.providers.base import ChatResult
from backend.app.repositories import Repositories
from backend.app.runtime_installer import LlamaRuntimeInstaller
from backend.app.schemas import AgentInput, WorkflowInput, WorkflowSpec
from backend.app.security import SecretBox
from backend.app.tools import ApprovalRequired, ToolRegistry
from backend.app.workflows import WorkflowValidationError, optimized_inference_options, workflow_levels


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, auth_token="test-token")
    with TestClient(create_app(settings)) as value:
        yield value


HEADERS = {"x-studio-token": "test-token"}


def test_api_requires_desktop_token(client: TestClient) -> None:
    assert client.get("/health").status_code == 401
    response = client.get("/health", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_hardware_and_provider_preflight(client: TestClient) -> None:
    hardware = client.get("/api/system/hardware", headers=HEADERS).json()
    assert hardware["ram_total_bytes"] > 0
    assert hardware["recommended_profile"] in {"small_fast", "balanced", "highest_quality"}
    assert hardware["recommended_context"] <= 8192
    providers = client.get("/api/providers", headers=HEADERS).json()
    assert {item["id"] for item in providers} == {"llama_cpp", "ollama", "lm_studio", "gemini"}
    catalog = client.get("/api/catalog", headers=HEADERS).json()
    assert len(catalog) >= 3
    assert all(item["license_name"] for item in catalog)
    assert any(item["recommended"] for item in catalog)
    starter = next(item for item in catalog if item.get("starter"))
    assert starter["size_bytes"] < 1_000_000_000


def test_one_failed_provider_probe_cannot_remove_setup_choices(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_status():
        raise RuntimeError("simulated detection failure")

    monkeypatch.setattr(client.app.state.providers.get("gemini"), "status", broken_status)
    response = client.get("/api/providers", headers=HEADERS)
    assert response.status_code == 200
    values = response.json()
    assert {item["id"] for item in values} == {"gemini", "llama_cpp", "ollama", "lm_studio"}
    gemini = next(item for item in values if item["id"] == "gemini")
    assert gemini["available"] is False
    assert "failed safely" in gemini["detail"]


def test_one_failed_model_probe_cannot_hide_other_provider_models(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_models():
        raise RuntimeError("simulated model discovery failure")

    async def ollama_models():
        from backend.app.schemas import ModelDescriptor
        return [ModelDescriptor(
            id="qwen:test", name="Qwen test", provider_id="ollama",
            publisher="Test", license_name="Apache-2.0", installed=True,
        )]

    monkeypatch.setattr(client.app.state.providers.get("gemini"), "models", broken_models)
    monkeypatch.setattr(client.app.state.providers.get("ollama"), "models", ollama_models)
    response = client.get("/api/models", headers=HEADERS)
    assert response.status_code == 200
    assert any(item["provider_id"] == "ollama" for item in response.json())


def test_gemini_key_is_verified_and_encrypted(client: TestClient, tmp_path: Path) -> None:
    provider = client.app.state.providers.get("gemini")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-gemini-key-1234567890"
        return httpx.Response(200, json={"models": [{"name": "models/gemini-3.5-flash"}]})

    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = client.put(
        "/api/providers/gemini/config",
        json={"api_key": "test-gemini-key-1234567890"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["configured"] is True
    raw = Database(tmp_path / "studio.db").setting("gemini_api_key_enc")
    assert isinstance(raw, str) and raw.startswith("enc:v1:")
    assert "test-gemini" not in raw
    models = client.get("/api/models?provider_id=gemini", headers=HEADERS).json()
    assert models[0]["id"] == "gemini-3.5-flash"


def test_agent_round_trip_encrypts_instructions(client: TestClient, tmp_path: Path) -> None:
    payload = {
        "name": "Researcher",
        "description": "Finds facts",
        "provider_id": "ollama",
        "model_id": "local-model",
        "instructions": "A very private instruction",
        "config": {"temperature": 0.2},
    }
    created = client.post("/api/agents", json=payload, headers=HEADERS)
    assert created.status_code == 200
    assert created.json()["instructions"] == payload["instructions"]
    raw = Database(tmp_path / "studio.db").row("SELECT instructions_enc FROM agents")
    assert raw and raw["instructions_enc"].startswith("enc:v1:")
    assert payload["instructions"] not in raw["instructions_enc"]


def test_plain_language_draft_uses_bounded_review_and_approval(client: TestClient) -> None:
    for name in ("Writer", "Reviewer"):
        response = client.post("/api/agents", json={
            "name": name, "description": "", "provider_id": "ollama", "model_id": "model",
            "instructions": f"Act as the {name}.", "config": {},
        }, headers=HEADERS)
        assert response.status_code == 200
    drafted = client.post(
        "/api/workflows/draft", json={"goal": "Draft and review a report, then ask for approval"}, headers=HEADERS
    )
    assert drafted.status_code == 200
    node_types = {node["type"] for node in drafted.json()["spec"]["nodes"]}
    assert {"review", "approval", "output"}.issubset(node_types)


def test_parallel_router_and_review_workflow_patterns(client: TestClient) -> None:
    class FakeProvider:
        cloud = False

        async def chat(self, model, messages, **kwargs):
            system = messages[0]["content"]
            user = messages[-1]["content"]
            if "Reviewer" in system:
                content = "APPROVED"
            else:
                content = f"{system.split('.')[0]}: {user[:80]}"
            return ChatResult(content=content, prompt_tokens=3, completion_tokens=2)

        async def close(self):
            return None

    client.app.state.providers.providers["ollama"] = FakeProvider()
    agent_ids = []
    for name in ("Writer", "Reviewer"):
        agent_ids.append(client.post("/api/agents", json={
            "name": name, "description": "", "provider_id": "ollama", "model_id": "fake",
            "instructions": f"{name}. Work concisely.", "config": {},
        }, headers=HEADERS).json()["id"])

    workflows = [
        {
            "name": "Parallel", "nodes": [
                {"id": "in", "type": "input", "label": "Input", "position": {}, "config": {}},
                {"id": "p", "type": "parallel", "label": "Parallel", "position": {}, "config": {}},
                {"id": "a", "type": "agent", "label": "A", "position": {}, "config": {"agent_id": agent_ids[0]}},
                {"id": "b", "type": "agent", "label": "B", "position": {}, "config": {"agent_id": agent_ids[1]}},
                {"id": "out", "type": "output", "label": "Output", "position": {}, "config": {}},
            ], "edges": [
                {"id": "e1", "source": "in", "target": "p"}, {"id": "e2", "source": "p", "target": "a"},
                {"id": "e3", "source": "p", "target": "b"}, {"id": "e4", "source": "a", "target": "out"},
                {"id": "e5", "source": "b", "target": "out"},
            ],
        },
        {
            "name": "Router", "nodes": [
                {"id": "in", "type": "input", "label": "Input", "position": {}, "config": {}},
                {"id": "r", "type": "router", "label": "Router", "position": {}, "config": {"default_target": "b", "routes": [{"contains": "writer", "target": "a"}]}},
                {"id": "a", "type": "agent", "label": "A", "position": {}, "config": {"agent_id": agent_ids[0]}},
                {"id": "b", "type": "agent", "label": "B", "position": {}, "config": {"agent_id": agent_ids[1]}},
                {"id": "out", "type": "output", "label": "Output", "position": {}, "config": {}},
            ], "edges": [
                {"id": "e1", "source": "in", "target": "r"}, {"id": "e2", "source": "r", "target": "a"},
                {"id": "e3", "source": "r", "target": "b"}, {"id": "e4", "source": "a", "target": "out"},
                {"id": "e5", "source": "b", "target": "out"},
            ],
        },
        {
            "name": "Review", "nodes": [
                {"id": "in", "type": "input", "label": "Input", "position": {}, "config": {}},
                {"id": "review", "type": "review", "label": "Review", "position": {}, "config": {"agent_id": agent_ids[0], "reviewer_agent_id": agent_ids[1], "max_iterations": 2}},
                {"id": "out", "type": "output", "label": "Output", "position": {}, "config": {}},
            ], "edges": [{"id": "e1", "source": "in", "target": "review"}, {"id": "e2", "source": "review", "target": "out"}],
        },
    ]
    for item in workflows:
        created = client.post("/api/workflows", json={
            "name": item["name"], "description": "", "spec": {
                "version": "1.0", "nodes": item["nodes"], "edges": item["edges"],
                "limits": {"max_iterations": 3, "timeout_seconds": 30},
            },
        }, headers=HEADERS).json()
        run = client.post(f"/api/workflows/{created['id']}/run", json={"input": "writer task"}, headers=HEADERS).json()
        for _ in range(100):
            detail = client.get(f"/api/runs/{run['id']}", headers=HEADERS).json()
            if detail["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert detail["status"] == "completed", detail.get("error")
        assert detail["output"]
    blocked = client.delete(f"/api/agents/{agent_ids[0]}", headers=HEADERS)
    assert blocked.status_code == 409
    assert "Replace this agent" in blocked.json()["detail"]


def test_approval_workflow_pauses_and_resumes(client: TestClient) -> None:
    workflow = {
        "name": "Approval test",
        "description": "",
        "spec": {
            "version": "1.0",
            "limits": {"max_iterations": 2, "timeout_seconds": 30},
            "nodes": [
                {"id": "input", "type": "input", "label": "Input", "position": {}, "config": {}},
                {"id": "approval", "type": "approval", "label": "Approve", "position": {}, "config": {"reason": "Check it"}},
                {"id": "output", "type": "output", "label": "Output", "position": {}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "input", "target": "approval"},
                {"id": "e2", "source": "approval", "target": "output"},
            ],
        },
    }
    created = client.post("/api/workflows", json=workflow, headers=HEADERS).json()
    run = client.post(f"/api/workflows/{created['id']}/run", json={"input": "hello"}, headers=HEADERS).json()
    for _ in range(30):
        detail = client.get(f"/api/runs/{run['id']}", headers=HEADERS).json()
        if detail["status"] == "waiting_approval":
            break
        time.sleep(0.02)
    assert detail["status"] == "waiting_approval"
    assert detail["state"]["pending_approval"]["reason"] == "Check it"
    step_statuses = {step["node_id"]: step["status"] for step in detail["state"]["steps"]}
    assert step_statuses == {"input": "completed", "approval": "waiting_approval", "output": "pending"}
    response = client.post(f"/api/runs/{run['id']}/approval", json={"approved": True, "response": ""}, headers=HEADERS)
    assert response.status_code == 200
    for _ in range(30):
        detail = client.get(f"/api/runs/{run['id']}", headers=HEADERS).json()
        if detail["status"] == "completed":
            break
        time.sleep(0.02)
    assert detail["status"] == "completed"
    assert detail["output"] == "hello"
    assert all(step["status"] == "completed" for step in detail["state"]["steps"])

    stopped = client.post(f"/api/workflows/{created['id']}/run", json={"input": "stop me"}, headers=HEADERS).json()
    for _ in range(30):
        stopped_detail = client.get(f"/api/runs/{stopped['id']}", headers=HEADERS).json()
        if stopped_detail["status"] == "waiting_approval":
            break
        time.sleep(0.02)
    assert client.delete(f"/api/workflows/{created['id']}", headers=HEADERS).status_code == 409
    response = client.post(f"/api/runs/{stopped['id']}/cancel", headers=HEADERS)
    assert response.status_code == 200
    stopped_detail = client.get(f"/api/runs/{stopped['id']}", headers=HEADERS).json()
    assert stopped_detail["status"] == "cancelled"
    assert stopped_detail["error"] == "Stopped by user"
    assert client.delete(f"/api/workflows/{created['id']}", headers=HEADERS).status_code == 200
    assert client.get(f"/api/runs/{stopped['id']}", headers=HEADERS).status_code == 404


def test_inference_options_prioritize_responsiveness() -> None:
    options = optimized_inference_options({"temperature": 0.3, "num_ctx": 16384, "num_predict": 5000})
    assert options == {"temperature": 0.3, "num_ctx": 4096, "num_predict": 256}


@pytest.mark.asyncio
async def test_mutating_tools_cannot_bypass_approval(tmp_path: Path) -> None:
    registry = ToolRegistry([tmp_path])
    destination = tmp_path / "result.txt"
    with pytest.raises(ApprovalRequired):
        await registry.execute("write_file", {"path": str(destination), "content": "private"})
    assert not destination.exists()
    await registry.execute("write_file", {"path": str(destination), "content": "private"}, approved=True)
    assert destination.read_text(encoding="utf-8") == "private"
    with pytest.raises(ApprovalRequired):
        await registry.execute("send_email", {"to": "person@example.com", "subject": "Hi", "body": "Private"})
    with pytest.raises(ApprovalRequired):
        await registry.execute(
            "write_file", {"path": "still-protected.txt", "content": "No bypass"},
            allow_without_approval=True,
        )
    with pytest.raises(PermissionError):
        await registry.execute("http_request", {"url": "https://unapproved.example/data", "method": "GET"})


@pytest.mark.asyncio
async def test_word_and_excel_tools_create_and_read_real_files(tmp_path: Path) -> None:
    registry = ToolRegistry([tmp_path])
    word_path = tmp_path / "summary.docx"
    excel_path = tmp_path / "people.xlsx"
    with pytest.raises(ApprovalRequired):
        await registry.execute("create_word", {"path": str(word_path), "title": "Summary", "content": "First paragraph."})
    await registry.execute(
        "create_word", {"path": str(word_path), "title": "Summary", "content": "First paragraph."}, approved=True
    )
    assert "First paragraph" in await registry.execute("read_file", {"path": str(word_path)})
    await registry.execute(
        "create_excel",
        {"path": str(excel_path), "sheet_name": "People", "data": [{"name": "Ada", "value": "=2+2"}]},
        approved=True,
    )
    workbook_text = await registry.execute("read_file", {"path": str(excel_path)})
    assert "Ada" in workbook_text
    assert "'=2+2" in workbook_text


def test_agent_skill_upload_is_encrypted_and_deletable(client: TestClient, tmp_path: Path) -> None:
    agent = client.post("/api/agents", json={
        "name": "Skilled", "description": "", "provider_id": "ollama", "model_id": "model",
        "instructions": "Use attached guidance.", "config": {},
    }, headers=HEADERS).json()
    response = client.post(
        f"/api/agents/{agent['id']}/skills",
        files={"file": ("fact-check.md", io.BytesIO(b"Always distinguish facts from assumptions."), "text/markdown")},
        headers=HEADERS,
    )
    assert response.status_code == 200
    skill = response.json()
    raw = Database(tmp_path / "studio.db").row("SELECT content_enc FROM agent_skills WHERE id=?", (skill["id"],))
    assert raw and raw["content_enc"].startswith("enc:v1:")
    assert "distinguish facts" not in raw["content_enc"]
    context = client.app.state.repositories.agent_skill_context(agent["id"])
    assert "fact-check.md" in context and "distinguish facts" in context
    assert client.delete(f"/api/agents/{agent['id']}/skills/{skill['id']}", headers=HEADERS).status_code == 200
    assert client.get(f"/api/agents/{agent['id']}/skills", headers=HEADERS).json() == []


def test_email_configuration_encrypts_password_and_sends_test(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, username, password):
            assert username == "sender@example.com"
            assert password == "app-password"

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("backend.app.tools.smtplib.SMTP_SSL", FakeSMTP)
    configured = client.put("/api/integrations/email", json={
        "provider": "custom", "sender_email": "sender@example.com", "sender_name": "Studio",
        "username": "sender@example.com", "password": "app-password", "host": "smtp.example.com",
        "port": 465, "security": "ssl",
    }, headers=HEADERS)
    assert configured.status_code == 200
    assert configured.json()["password_saved"] is True
    raw = Database(tmp_path / "studio.db").setting("email_password_enc")
    assert raw.startswith("enc:v1:") and "app-password" not in raw
    result = client.post("/api/integrations/email/test", json={"to": "recipient@example.com"}, headers=HEADERS)
    assert result.status_code == 200
    assert len(sent) == 1
    assert sent[0]["To"] == "recipient@example.com"

    workflow = client.post("/api/workflows", json={
        "name": "Email result", "description": "", "spec": {
            "version": "1.0", "limits": {"max_iterations": 2, "timeout_seconds": 30},
            "nodes": [
                {"id": "input", "type": "input", "label": "Input", "position": {}, "config": {}},
                {"id": "email", "type": "function", "label": "Email", "position": {}, "config": {
                    "tool_id": "send_email", "arguments": {
                        "to": "workflow@example.com", "subject": "Workflow result", "body": "$input",
                    },
                }},
                {"id": "output", "type": "output", "label": "Output", "position": {}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "input", "target": "email"},
                {"id": "e2", "source": "email", "target": "output"},
            ],
        },
    }, headers=HEADERS).json()
    run = client.post(f"/api/workflows/{workflow['id']}/run", json={"input": "Approved body"}, headers=HEADERS).json()
    for _ in range(50):
        detail = client.get(f"/api/runs/{run['id']}", headers=HEADERS).json()
        if detail["status"] == "waiting_approval":
            break
        time.sleep(0.02)
    assert detail["state"]["pending_approval"]["tool_id"] == "send_email"
    assert len(sent) == 1
    assert client.post(f"/api/runs/{run['id']}/approval", json={"approved": True}, headers=HEADERS).status_code == 200
    for _ in range(50):
        detail = client.get(f"/api/runs/{run['id']}", headers=HEADERS).json()
        if detail["status"] == "completed":
            break
        time.sleep(0.02)
    assert detail["status"] == "completed"
    assert len(sent) == 2 and sent[1]["To"] == "workflow@example.com"

    automatic = client.post("/api/workflows", json={
        "name": "Automatic email", "description": "", "spec": {
            "version": "1.0", "limits": {"max_iterations": 2, "timeout_seconds": 30},
            "nodes": [
                {"id": "input", "type": "input", "label": "Input", "position": {}, "config": {}},
                {"id": "email", "type": "function", "label": "Email", "position": {}, "config": {
                    "tool_id": "send_email", "approval_policy": "never", "arguments": {
                        "to": "automatic@example.com", "subject": "Automatic result", "body": "$input",
                    },
                }},
                {"id": "output", "type": "output", "label": "Output", "position": {}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "input", "target": "email"},
                {"id": "e2", "source": "email", "target": "output"},
            ],
        },
    }, headers=HEADERS).json()
    automatic_run = client.post(
        f"/api/workflows/{automatic['id']}/run", json={"input": "Automatic body"}, headers=HEADERS
    ).json()
    for _ in range(50):
        automatic_detail = client.get(f"/api/runs/{automatic_run['id']}", headers=HEADERS).json()
        if automatic_detail["status"] in {"completed", "failed", "waiting_approval"}:
            break
        time.sleep(0.02)
    assert automatic_detail["status"] == "completed"
    assert len(sent) == 3 and sent[2]["To"] == "automatic@example.com"


@pytest.mark.asyncio
async def test_gmail_auth_error_explains_app_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class RejectingSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(534, b"Application-specific password required")

    monkeypatch.setattr("backend.app.tools.smtplib.SMTP_SSL", RejectingSMTP)
    registry = ToolRegistry([tmp_path])
    registry.configure_email({
        "provider": "gmail", "host": "smtp.gmail.com", "port": 465, "security": "ssl",
        "username": "sender@gmail.com", "password": "normal-password", "sender_email": "sender@gmail.com",
    })
    with pytest.raises(RuntimeError, match="Google App Password"):
        await registry.execute(
            "send_email", {"to": "recipient@example.com", "subject": "Test", "body": "Body"}, approved=True
        )


def test_cross_provider_agents_handoff_in_one_workflow(client: TestClient) -> None:
    calls: list[tuple[str, str, str]] = []

    class FakeProvider:
        def __init__(self, provider_id: str, prefix: str, cloud: bool = False):
            self.id = provider_id
            self.name = provider_id
            self.prefix = prefix
            self.cloud = cloud

        async def chat(self, model, messages, **kwargs):
            supplied = messages[-1]["content"]
            calls.append((self.id, model, supplied))
            return ChatResult(content=f"{self.prefix}:{supplied}", prompt_tokens=2, completion_tokens=3)

        async def close(self):
            return None

    client.app.state.providers.providers["gemini"] = FakeProvider("gemini", "cloud", cloud=True)
    client.app.state.providers.providers["ollama"] = FakeProvider("ollama", "local")
    gemini_agent = client.post("/api/agents", json={
        "name": "Cloud researcher", "provider_id": "gemini", "model_id": "gemini-3.5-flash",
        "instructions": "Research", "description": "", "config": {},
    }, headers=HEADERS).json()
    ollama_agent = client.post("/api/agents", json={
        "name": "Local writer", "provider_id": "ollama", "model_id": "qwen-local",
        "instructions": "Write", "description": "", "config": {},
    }, headers=HEADERS).json()
    workflow = client.post("/api/workflows", json={
        "name": "Cloud to local handoff", "description": "", "spec": {
            "version": "1.0", "limits": {"max_iterations": 2, "timeout_seconds": 30},
            "nodes": [
                {"id": "input", "type": "input", "label": "Input", "position": {}, "config": {}},
                {"id": "cloud", "type": "agent", "label": "Cloud", "position": {}, "config": {"agent_id": gemini_agent["id"]}},
                {"id": "local", "type": "agent", "label": "Local", "position": {}, "config": {"agent_id": ollama_agent["id"]}},
                {"id": "output", "type": "output", "label": "Output", "position": {}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "input", "target": "cloud"},
                {"id": "e2", "source": "cloud", "target": "local"},
                {"id": "e3", "source": "local", "target": "output"},
            ],
        },
    }, headers=HEADERS).json()
    run = client.post(f"/api/workflows/{workflow['id']}/run", json={"input": "start"}, headers=HEADERS).json()
    for _ in range(100):
        detail = client.get(f"/api/runs/{run['id']}", headers=HEADERS).json()
        if detail["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert detail["status"] == "completed"
    assert detail["output"] == "local:cloud:start"
    assert calls == [
        ("gemini", "gemini-3.5-flash", "start"),
        ("ollama", "qwen-local", "cloud:start"),
    ]


def test_agentpack_excludes_paths_and_secrets(tmp_path: Path) -> None:
    database = Database(tmp_path / "studio.db")
    repositories = Repositories(database, SecretBox(tmp_path))
    agent = repositories.save_agent(AgentInput(
        name="Agent", provider_id="ollama", model_id="model", instructions="Prompt",
        config={"temperature": 0.2, "api_key": "never-export"},
    ))
    workflow = repositories.save_workflow(WorkflowInput.model_validate({
        "name": "Portable", "description": "", "spec": {"version": "1.0", "nodes": [
            {"id": "a", "type": "agent", "label": "Agent", "position": {}, "config": {"agent_id": agent.id}},
            {"id": "f", "type": "function", "label": "Write", "position": {}, "config": {"tool_id": "write_file", "arguments": {"path": "C:/secret/data.txt"}}},
        ], "edges": [{"id": "e", "source": "a", "target": "f"}]},
    }))
    archive_path = export_agentpack(repositories, workflow.id, tmp_path / "portable.agentpack")
    with zipfile.ZipFile(archive_path) as archive:
        combined = b"\n".join(archive.read(name) for name in archive.namelist()).decode()
    assert "never-export" not in combined
    assert "C:/secret" not in combined
    assert '"contains_secrets": false' in combined


def test_cycles_are_rejected() -> None:
    spec = WorkflowSpec.model_validate({
        "version": "1.0",
        "nodes": [
            {"id": "a", "type": "input", "label": "A", "position": {}, "config": {}},
            {"id": "b", "type": "output", "label": "B", "position": {}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "a"},
        ],
    })
    with pytest.raises(WorkflowValidationError):
        workflow_levels(spec)


def test_runtime_installer_refuses_unverifiable_assets(tmp_path: Path) -> None:
    installer = LlamaRuntimeInstaller(Settings(data_dir=tmp_path))
    with pytest.raises(RuntimeError):
        installer._select_asset([{"name": "unrelated-linux.tar.gz"}])


def test_studio_and_agent_capabilities_block_privileged_functions(client: TestClient) -> None:
    settings = client.get("/api/settings", headers=HEADERS).json()
    assert settings["capabilities"]["code_execution"] is False
    updated = client.put(
        "/api/settings", json={"capabilities": {**settings["capabilities"], "code_execution": True}}, headers=HEADERS
    )
    assert updated.status_code == 200
    runtime = client.put("/api/runtime/python/path", json={"path": sys.executable}, headers=HEADERS)
    assert runtime.status_code == 200 and runtime.json()["available"] is True
    tools = {item["id"]: item for item in client.get("/api/tools", headers=HEADERS).json()}
    assert tools["python_code"]["available"] is True

    agent = client.post("/api/agents", json={
        "name": "No code", "description": "", "provider_id": "ollama", "model_id": "fake",
        "instructions": "No code.", "config": {"capabilities": {"code_execution": False}},
    }, headers=HEADERS).json()
    workflow = client.post("/api/workflows", json={
        "name": "Blocked code", "description": "", "spec": {
            "version": "1.0", "limits": {"max_iterations": 2, "timeout_seconds": 30},
            "nodes": [
                {"id": "in", "type": "input", "label": "Input", "position": {}, "config": {}},
                {"id": "code", "type": "function", "label": "Code", "position": {}, "config": {
                    "agent_id": agent["id"], "tool_id": "python_code",
                    "arguments": {"code": "print('should never run')", "input": "$input", "timeout_seconds": "5"},
                }},
                {"id": "out", "type": "output", "label": "Output", "position": {}, "config": {}},
            ],
            "edges": [{"id": "e1", "source": "in", "target": "code"}, {"id": "e2", "source": "code", "target": "out"}],
        },
    }, headers=HEADERS).json()
    run = client.post(f"/api/workflows/{workflow['id']}/run", json={"input": "hello"}, headers=HEADERS).json()
    for _ in range(50):
        detail = client.get(f"/api/runs/{run['id']}", headers=HEADERS).json()
        if detail["status"] in {"failed", "waiting_approval"}:
            break
        time.sleep(0.02)
    assert detail["status"] == "failed"
    assert "disabled for the selected agent" in detail["error"]

    agent["config"]["capabilities"] = {"code_execution": True}
    updated_agent = {key: agent[key] for key in ("name", "description", "provider_id", "model_id", "instructions", "config")}
    assert client.put(f"/api/agents/{agent['id']}", json=updated_agent, headers=HEADERS).status_code == 200
    approved_run = client.post(
        f"/api/workflows/{workflow['id']}/run", json={"input": "hello"}, headers=HEADERS
    ).json()
    for _ in range(50):
        approved_detail = client.get(f"/api/runs/{approved_run['id']}", headers=HEADERS).json()
        if approved_detail["status"] == "waiting_approval":
            break
        time.sleep(0.02)
    assert approved_detail["state"]["pending_approval"]["tool_id"] == "python_code"
    preview = approved_detail["state"]["pending_approval"]["preview"]
    assert "should never run" in preview
    client.post(f"/api/runs/{approved_run['id']}/approval", json={"approved": True}, headers=HEADERS)
    for _ in range(100):
        approved_detail = client.get(f"/api/runs/{approved_run['id']}", headers=HEADERS).json()
        if approved_detail["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert approved_detail["status"] == "completed", approved_detail.get("error")
    assert "should never run" in approved_detail["output"]


def test_run_attachments_are_bounded_delivered_and_redacted(client: TestClient) -> None:
    captured: list[list[dict]] = []

    class VisionProvider:
        cloud = False

        async def chat(self, model, messages, **kwargs):
            captured.append(messages)
            return ChatResult(content="image received", prompt_tokens=1, completion_tokens=1)

        async def close(self):
            return None

    client.app.state.providers.providers["ollama"] = VisionProvider()
    agent = client.post("/api/agents", json={
        "name": "Viewer", "description": "", "provider_id": "ollama", "model_id": "vision",
        "instructions": "Describe attachments.", "config": {"capabilities": {"attachments": True}},
    }, headers=HEADERS).json()
    workflow = client.post("/api/workflows", json={
        "name": "See image", "description": "", "spec": {"version": "1.0", "nodes": [
            {"id": "in", "type": "input", "label": "Input", "position": {}, "config": {}},
            {"id": "agent", "type": "agent", "label": "Viewer", "position": {}, "config": {"agent_id": agent["id"]}},
            {"id": "out", "type": "output", "label": "Output", "position": {}, "config": {}},
        ], "edges": [{"id": "e1", "source": "in", "target": "agent"}, {"id": "e2", "source": "agent", "target": "out"}]},
    }, headers=HEADERS).json()
    response = client.post(
        f"/api/workflows/{workflow['id']}/run-with-files",
        data={"input": "What is attached?", "local_paths": "[]"},
        files={"files": ("tiny.png", io.BytesIO(b"\x89PNG\r\n\x1a\nmock"), "image/png")},
        headers=HEADERS,
    )
    assert response.status_code == 200
    run_id = response.json()["id"]
    for _ in range(50):
        detail = client.get(f"/api/runs/{run_id}", headers=HEADERS).json()
        if detail["status"] == "completed":
            break
        time.sleep(0.02)
    assert detail["status"] == "completed"
    assert captured[0][-1]["attachments"][0]["data_base64"].startswith("iVBOR")
    public_attachment = detail["state"]["attachments"][0]
    assert public_attachment["name"] == "tiny.png"
    assert "data_base64" not in public_attachment


def test_mcp_configuration_requires_master_switch_absolute_path_and_acknowledgement(
    client: TestClient, tmp_path: Path
) -> None:
    blocked = client.put("/api/mcp/servers", json={"name": "Tools", "command": "server.exe"}, headers=HEADERS)
    assert blocked.status_code == 403
    settings = client.get("/api/settings", headers=HEADERS).json()
    client.put("/api/settings", json={"capabilities": {**settings["capabilities"], "mcp": True}}, headers=HEADERS)
    executable = tmp_path / "trusted-server.exe"
    executable.write_bytes(b"not executed in this configuration test")
    missing_ack = client.put("/api/mcp/servers", json={
        "name": "Tools", "command": str(executable), "args": [], "enabled": True,
    }, headers=HEADERS)
    assert missing_ack.status_code == 403
    saved = client.put("/api/mcp/servers", json={
        "name": "Tools", "command": str(executable), "args": [], "enabled": True,
        "warning_acknowledged": True,
    }, headers=HEADERS)
    assert saved.status_code == 200
    assert saved.json()["transport"] == "stdio"


@pytest.mark.asyncio
async def test_gemini_search_requires_studio_and_agent_web_permissions(client: TestClient) -> None:
    observed_tools: list[object] = []

    class SearchAwareGemini:
        cloud = True

        async def chat(self, model, messages, **kwargs):
            observed_tools.append(kwargs.get("tools"))
            return ChatResult(content="grounded", prompt_tokens=1, completion_tokens=1)

        async def close(self):
            return None

    client.app.state.providers.providers["gemini"] = SearchAwareGemini()
    settings = client.get("/api/settings", headers=HEADERS).json()
    client.put("/api/settings", json={
        "capabilities": {**settings["capabilities"], "web_access": True},
    }, headers=HEADERS)
    agent = client.post("/api/agents", json={
        "name": "Current researcher", "description": "", "provider_id": "gemini", "model_id": "gemini-3.5-flash",
        "instructions": "Use current sources.", "config": {"capabilities": {"web_access": True}},
    }, headers=HEADERS).json()
    await client.app.state.engine._agent_call(agent["id"], "Find current information")
    assert observed_tools[-1] == [{"type": "google_search"}]

    agent["config"]["capabilities"]["web_access"] = False
    payload = {key: agent[key] for key in ("name", "description", "provider_id", "model_id", "instructions", "config")}
    client.put(f"/api/agents/{agent['id']}", json=payload, headers=HEADERS)
    await client.app.state.engine._agent_call(agent["id"], "Do not browse")
    assert observed_tools[-1] is None
