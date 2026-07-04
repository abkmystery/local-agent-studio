from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import smtplib
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import httpx

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .agentpacks import export_agentpack, import_agentpack
from .benchmarks import benchmark_provider
from .capabilities import CapabilityPolicy, normalized_capabilities
from .config import Settings
from .db import Database, utc_now
from .downloads import DownloadManager
from .hardware import hardware_assessment, resource_snapshot
from .model_catalog import CATALOG, catalog_item
from .mcp_client import MCPManager
from .provider_models import StarterModelInstaller
from .python_runtime import PythonRuntimeManager
from .providers import ProviderManager
from .repositories import Repositories
from .runtime_installer import LlamaRuntimeInstaller
from .scheduler import LocalScheduler
from .schemas import (
    Agent, AgentInput, AgentSkill, ApprovalRequest, EmailConfigInput, EmailTestInput,
    RunRequest, ScheduleInput, Workflow, WorkflowInput,
)
from .security import SecretBox
from .tools import ToolRegistry
from .workflows import WorkflowEngine, workflow_levels


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.prepare()
    database = Database(settings.database_path)
    secrets = SecretBox(settings.data_dir)
    repositories = Repositories(database, secrets)
    stored_gemini_key = database.setting("gemini_api_key_enc")
    gemini_api_key = secrets.decrypt(stored_gemini_key) if isinstance(stored_gemini_key, str) else None
    providers = ProviderManager(settings, gemini_api_key)
    workspace = settings.data_dir / "workspace"
    extra_folders = [
        Path(item).expanduser().resolve()
        for item in database.setting("approved_folders", [])
        if isinstance(item, str) and Path(item).expanduser().is_dir()
    ][:10]
    python_runtime = PythonRuntimeManager(database, workspace)
    mcp_manager = MCPManager(database, secrets)
    tools = ToolRegistry(
        [workspace, *extra_folders], database.setting("approved_domains", []),
        python_runtime=python_runtime, mcp_manager=mcp_manager,
    )
    saved_email = database.setting("email_config", {})
    saved_email_password = database.setting("email_password_enc")
    if saved_email and isinstance(saved_email_password, str):
        tools.configure_email({**saved_email, "password": secrets.decrypt(saved_email_password) or ""})
    downloads = DownloadManager()
    provider_models = StarterModelInstaller()
    capability_policy = CapabilityPolicy(database, repositories)
    engine = WorkflowEngine(repositories, providers, tools, capability_policy)
    scheduler = LocalScheduler(database, secrets, engine)
    runtime_installer = LlamaRuntimeInstaller(settings, lambda: providers.refresh_llama_cpp(settings))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler_task = asyncio.create_task(scheduler.run())
        yield
        scheduler.stop()
        scheduler_task.cancel()
        await providers.close()

    app = FastAPI(title="Local Agent Studio", version="0.5.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.repositories = repositories
    app.state.providers = providers
    app.state.engine = engine
    app.state.tools = tools
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["content-type", "x-studio-token"],
    )

    async def authorized(x_studio_token: Annotated[str | None, Header()] = None) -> None:
        if x_studio_token != settings.auth_token:
            raise HTTPException(status_code=401, detail="Invalid local application token")

    auth = Depends(authorized)

    async def prepare_run_input(
        input_text: str,
        local_paths: list[str] | None = None,
        uploads: list[UploadFile] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        capability_policy.require("attachments")
        local_paths = local_paths or []
        uploads = uploads or []
        if len(local_paths) + len(uploads) > 5:
            raise HTTPException(status_code=413, detail="A run can use at most five attachments")
        text_parts: list[str] = []
        images: list[dict[str, Any]] = []
        total_bytes = 0

        async def consume(name: str, media_type: str, content: bytes) -> None:
            nonlocal total_bytes
            total_bytes += len(content)
            if total_bytes > 12 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Attachments must total 12 MB or less")
            suffix = Path(name).suffix.casefold()
            if media_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                if len(content) > 5 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"{name} exceeds the 5 MB image limit")
                detected = media_type if media_type.startswith("image/") else mimetypes.guess_type(name)[0] or "image/png"
                images.append({
                    "name": Path(name).name, "media_type": detected, "size_bytes": len(content),
                    "data_base64": base64.b64encode(content).decode("ascii"),
                })
                return
            if suffix not in {".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".docx", ".xlsx"}:
                raise HTTPException(status_code=400, detail=f"Unsupported attachment type: {suffix or name}")
            if len(content) > 5 * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"{name} exceeds the 5 MB document limit")
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                    temporary.write(content)
                    temporary_path = Path(temporary.name)
                extracted = await asyncio.to_thread(tools._read_file_sync, temporary_path)
            except (ValueError, OSError, UnicodeError) as error:
                raise HTTPException(status_code=400, detail=f"Could not read {name}: {error}") from error
            finally:
                if temporary_path:
                    temporary_path.unlink(missing_ok=True)
            text_parts.append(f"\n\n--- Attached file: {Path(name).name} ---\n{extracted[:250_000]}")

        if local_paths:
            capability_policy.require("file_access")
        for raw_path in local_paths:
            try:
                path = tools._safe_path(raw_path)
                tools._bounded_file(path, 5 * 1024 * 1024)
                await consume(path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream", await asyncio.to_thread(path.read_bytes))
            except (ValueError, PermissionError, FileNotFoundError) as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        for upload in uploads:
            filename = Path(upload.filename or "attachment").name
            content = await upload.read(5 * 1024 * 1024 + 1)
            if len(content) > 5 * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"{filename} exceeds the 5 MB limit")
            await consume(filename, upload.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream", content)
        return input_text + "".join(text_parts), images

    @app.get("/health", dependencies=[auth])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    @app.get("/api/settings", dependencies=[auth])
    async def get_settings() -> dict[str, Any]:
        return {
            "onboarding_complete": database.setting("onboarding_complete", False),
            "offline_mode": database.setting("offline_mode", False),
            "models_dir": str(settings.models_dir),
            "workspace_dir": str(workspace),
            "approved_folders": [str(path) for path in tools.approved_folders[1:]],
            "approved_domains": database.setting("approved_domains", []),
            "capabilities": normalized_capabilities(database.setting("capabilities", {})),
        }

    @app.put("/api/settings", dependencies=[auth])
    async def put_settings(payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("onboarding_complete", "offline_mode"):
            if key in payload:
                database.set_setting(key, bool(payload[key]))
        if "approved_domains" in payload:
            domains = sorted({str(item).casefold().strip() for item in payload["approved_domains"] if str(item).strip()})
            database.set_setting("approved_domains", domains)
            tools.approved_domains = domains
        if "approved_folders" in payload:
            if not isinstance(payload["approved_folders"], list) or len(payload["approved_folders"]) > 10:
                raise HTTPException(status_code=400, detail="Approved folders must be a list of at most ten paths")
            folders: list[Path] = []
            for item in payload["approved_folders"]:
                path = Path(str(item).strip().strip('"')).expanduser()
                if not path.is_absolute() or not path.is_dir():
                    raise HTTPException(status_code=400, detail=f"Folder does not exist: {item}")
                folders.append(path.resolve())
            unique = list(dict.fromkeys(folders))
            database.set_setting("approved_folders", [str(path) for path in unique])
            tools.approved_folders = [workspace.resolve(), *unique]
        if "capabilities" in payload:
            current = normalized_capabilities(database.setting("capabilities", {}))
            updated = normalized_capabilities(payload["capabilities"], current)
            database.set_setting("capabilities", updated)
        return await get_settings()

    @app.get("/api/runtime/python", dependencies=[auth])
    async def python_status() -> dict[str, Any]:
        return await asyncio.to_thread(python_runtime.status)

    @app.put("/api/runtime/python/path", dependencies=[auth])
    async def python_custom_path(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(python_runtime.set_custom, str(payload.get("path", "")))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/runtime/python/install", dependencies=[auth])
    async def python_install(payload: dict[str, Any]) -> dict[str, Any]:
        if database.setting("offline_mode", False):
            raise HTTPException(status_code=409, detail="Turn off Offline mode before installing Python")
        if not payload.get("acknowledged"):
            raise HTTPException(status_code=400, detail="Confirm the official Python installation first")
        return python_runtime.start_install()

    @app.get("/api/mcp/servers", dependencies=[auth])
    async def mcp_servers() -> list[dict[str, Any]]:
        return mcp_manager.list_servers()

    @app.put("/api/mcp/servers", dependencies=[auth])
    async def save_mcp_server(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            capability_policy.require("mcp")
            return mcp_manager.save_server(payload)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.delete("/api/mcp/servers/{identifier}", dependencies=[auth])
    async def delete_mcp_server(identifier: str) -> dict[str, bool]:
        if not mcp_manager.delete_server(identifier):
            raise HTTPException(status_code=404, detail="MCP server not found")
        return {"deleted": True}

    @app.get("/api/mcp/servers/{identifier}/tools", dependencies=[auth])
    async def mcp_server_tools(identifier: str) -> list[dict[str, Any]]:
        try:
            capability_policy.require("mcp")
            return await asyncio.wait_for(mcp_manager.list_tools(identifier), timeout=20)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"MCP connection failed: {error}") from error

    @app.get("/api/system/hardware", dependencies=[auth])
    async def system_hardware() -> dict[str, Any]:
        return await asyncio.to_thread(hardware_assessment, settings.models_dir)

    @app.get("/api/system/resources", dependencies=[auth])
    async def system_resources() -> dict[str, Any]:
        snapshot = await asyncio.to_thread(resource_snapshot, settings.models_dir)
        snapshot["providers"] = [status.model_dump() for status in await providers.statuses()]
        snapshot["benchmarks"] = database.rows("SELECT * FROM benchmarks ORDER BY measured_at DESC LIMIT 20")
        return snapshot

    @app.get("/api/providers", dependencies=[auth])
    async def provider_statuses() -> list[dict[str, Any]]:
        return [status.model_dump() for status in await providers.statuses()]

    @app.get("/api/providers/gemini/config", dependencies=[auth])
    async def gemini_config() -> dict[str, Any]:
        provider = providers.get("gemini")
        return {
            "configured": bool(getattr(provider, "configured", False)),
            "model_id": "gemini-3.5-flash",
            "ai_studio_url": "https://aistudio.google.com/apikey",
            "quota_url": "https://aistudio.google.com/usage",
            "free_tier_note": "Google currently offers free-tier token usage, but your live RPM and daily quota are set by Google and may change.",
        }

    @app.put("/api/providers/gemini/config", dependencies=[auth])
    async def put_gemini_config(payload: dict[str, Any]) -> dict[str, Any]:
        api_key = str(payload.get("api_key", "")).strip()
        if len(api_key) < 20:
            raise HTTPException(status_code=400, detail="Paste the complete Gemini API key from Google AI Studio")
        provider = providers.get("gemini")
        previous = getattr(provider, "api_key", None)
        provider.configure(api_key)  # type: ignore[attr-defined]
        try:
            await provider.verify()  # type: ignore[attr-defined]
        except (ValueError, httpx.HTTPError) as error:
            provider.configure(previous)  # type: ignore[attr-defined]
            raise HTTPException(status_code=400, detail=str(error)) from error
        database.set_setting("gemini_api_key_enc", secrets.encrypt(api_key))
        return await gemini_config()

    @app.delete("/api/providers/gemini/config", dependencies=[auth])
    async def delete_gemini_config() -> dict[str, bool]:
        providers.get("gemini").configure(None)  # type: ignore[attr-defined]
        database.set_setting("gemini_api_key_enc", None)
        return {"disconnected": True}

    @app.get("/api/integrations/email", dependencies=[auth])
    async def email_config() -> dict[str, Any]:
        return tools.email_status()

    @app.put("/api/integrations/email", dependencies=[auth])
    async def put_email_config(payload: EmailConfigInput) -> dict[str, Any]:
        presets = {
            "gmail": {"host": "smtp.gmail.com", "port": 465, "security": "ssl"},
            "outlook": {"host": "smtp.office365.com", "port": 587, "security": "starttls"},
            "yahoo": {"host": "smtp.mail.yahoo.com", "port": 465, "security": "ssl"},
        }
        values = payload.model_dump()
        if payload.provider in presets:
            values.update(presets[payload.provider])
        if (
            "@" not in values["sender_email"]
            or not values["username"].strip()
            or any(character in values["sender_email"] + values["sender_name"] for character in "\r\n")
        ):
            raise HTTPException(status_code=400, detail="Enter the sending email address and login username")
        if not values["host"].strip() or any(character.isspace() for character in values["host"]):
            raise HTTPException(status_code=400, detail="Enter a valid SMTP server name")
        existing_password = tools.email_config.get("password", "")
        password = payload.password or str(existing_password)
        if not password:
            raise HTTPException(status_code=400, detail="Enter the account password or provider app password")
        public_values = {key: value for key, value in values.items() if key != "password"}
        database.set_setting("email_config", public_values)
        database.set_setting("email_password_enc", secrets.encrypt(password))
        tools.configure_email({**public_values, "password": password})
        return tools.email_status()

    @app.delete("/api/integrations/email", dependencies=[auth])
    async def delete_email_config() -> dict[str, bool]:
        database.set_setting("email_config", {})
        database.set_setting("email_password_enc", None)
        tools.configure_email({})
        return {"disconnected": True}

    @app.post("/api/integrations/email/test", dependencies=[auth])
    async def test_email_config(payload: EmailTestInput) -> dict[str, Any]:
        try:
            return await tools.execute(
                "send_email",
                {
                    "to": payload.to,
                    "subject": "Local Agent Studio email test",
                    "body": "Your sending account is connected and ready for approval-gated workflows.",
                },
                approved=True,
            )
        except (ValueError, RuntimeError, OSError, smtplib.SMTPException) as error:
            raise HTTPException(status_code=502, detail=f"Email test failed: {error}") from error

    @app.get("/api/runtime/llama-cpp", dependencies=[auth])
    async def llama_runtime_status() -> dict[str, object]:
        return runtime_installer.serialized()

    @app.post("/api/runtime/llama-cpp/install", dependencies=[auth])
    async def llama_runtime_install() -> dict[str, object]:
        if database.setting("offline_mode", False):
            raise HTTPException(status_code=409, detail="Runtime downloads are disabled in offline mode")
        return runtime_installer.start()

    @app.get("/api/models", dependencies=[auth])
    async def models(provider_id: str | None = None) -> list[dict[str, Any]]:
        try:
            return [model.model_dump() for model in await providers.models(provider_id)]
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/catalog", dependencies=[auth])
    async def model_catalog() -> list[dict[str, object]]:
        assessment = await asyncio.to_thread(hardware_assessment, settings.models_dir)
        free = int(assessment["disk_free_bytes"])
        recommended = str(assessment["recommended_profile"])
        return [
            {
                **item,
                "recommended": item["profile"] == recommended,
                "fits_disk": free > int(item["size_bytes"]) * 1.15,
                "installed": (settings.models_dir / str(item["filename"])).exists(),
            }
            for item in CATALOG
        ]

    @app.post("/api/models/download", dependencies=[auth])
    async def model_download(payload: dict[str, Any]) -> dict[str, Any]:
        if database.setting("offline_mode", False):
            raise HTTPException(status_code=409, detail="Downloads are disabled in offline mode")
        if not payload.get("license_acknowledged"):
            raise HTTPException(status_code=400, detail="Model license acknowledgement is required")
        item: dict[str, object] | None = None
        if payload.get("catalog_id"):
            try:
                item = catalog_item(str(payload["catalog_id"]))
            except ValueError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
        url = str(item["url"] if item else payload["url"])
        filename = Path(str(item["filename"] if item else payload.get("filename", "model.gguf"))).name
        if not filename.lower().endswith(".gguf"):
            raise HTTPException(status_code=400, detail="Only GGUF model files are accepted")
        expected_hash = payload.get("sha256")
        if not expected_hash:
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    head = await client.head(url)
                    head.raise_for_status()
                    for response in [*head.history, head]:
                        candidate = (response.headers.get("x-linked-etag") or response.headers.get("etag") or "").strip('"')
                        if len(candidate) == 64 and all(character in "0123456789abcdefABCDEF" for character in candidate):
                            expected_hash = candidate
                            break
            except httpx.HTTPError as error:
                raise HTTPException(status_code=502, detail=f"Could not verify the model source: {error}") from error
        if not expected_hash:
            raise HTTPException(status_code=409, detail="The publisher did not provide a verifiable SHA-256 digest")
        state = downloads.start(url, settings.models_dir / filename, expected_hash)
        return downloads.serialized(state.id)[0]

    @app.get("/api/downloads", dependencies=[auth])
    async def download_list() -> list[dict[str, object]]:
        return downloads.serialized()

    @app.get("/api/provider-model-installs", dependencies=[auth])
    async def provider_model_installs() -> list[dict[str, Any]]:
        return provider_models.serialized()

    @app.post("/api/providers/{provider_id}/models/install-starter", dependencies=[auth])
    async def install_provider_starter(provider_id: str) -> dict[str, Any]:
        if database.setting("offline_mode", False):
            raise HTTPException(status_code=409, detail="Model downloads are disabled in offline mode")
        status = await providers.get(provider_id).status()
        if not status.available:
            raise HTTPException(status_code=409, detail=f"Start {status.name} before downloading a model")
        try:
            return asdict(provider_models.start(provider_id))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/downloads/{identifier}/pause", dependencies=[auth])
    async def download_pause(identifier: str) -> dict[str, object]:
        try:
            return downloads.serialized(downloads.pause(identifier).id)[0]
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Download not found") from error

    @app.post("/api/benchmarks", dependencies=[auth])
    async def benchmark(payload: dict[str, str]) -> dict[str, object]:
        try:
            return await benchmark_provider(database, providers, payload["provider_id"], payload["model_id"])
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/api/tools", dependencies=[auth])
    async def tool_catalog() -> list[dict[str, Any]]:
        python_ready = python_runtime.status()["available"]
        mcp_ready = bool([server for server in mcp_manager.list_servers() if server["enabled"]])
        studio_capabilities = capability_policy.studio()
        result = []
        for tool in tools.catalog():
            item = tool.model_dump()
            capability = {
                "read_file": "file_access", "write_file": "file_access", "create_word": "file_access",
                "create_excel": "file_access", "search_files": "file_access", "http_request": "web_access",
                "python_code": "code_execution", "mcp_call": "mcp",
            }.get(tool.id)
            item["capability"] = capability
            item["available"] = bool(not capability or studio_capabilities[capability])
            if tool.id == "python_code":
                item["available"] = bool(item["available"] and python_ready)
                item["unavailable_reason"] = None if item["available"] else "Enable code execution and install Python first"
            elif tool.id == "mcp_call":
                item["available"] = bool(item["available"] and mcp_ready)
                item["unavailable_reason"] = None if item["available"] else "Enable MCP and connect a local stdio server first"
            result.append(item)
        return result

    @app.get("/api/agents", dependencies=[auth], response_model=list[Agent])
    async def agents() -> list[Agent]:
        return repositories.list_agents()

    @app.post("/api/agents", dependencies=[auth], response_model=Agent)
    async def create_agent(payload: AgentInput) -> Agent:
        return repositories.save_agent(payload)

    @app.put("/api/agents/{identifier}", dependencies=[auth], response_model=Agent)
    async def update_agent(identifier: str, payload: AgentInput) -> Agent:
        if not repositories.get_agent(identifier):
            raise HTTPException(status_code=404, detail="Agent not found")
        return repositories.save_agent(payload, identifier)

    @app.delete("/api/agents/{identifier}", dependencies=[auth])
    async def delete_agent(identifier: str) -> dict[str, bool]:
        if not repositories.get_agent(identifier):
            raise HTTPException(status_code=404, detail="Agent not found")
        used_by = repositories.workflows_using_agent(identifier)
        if used_by:
            names = ", ".join(used_by[:3])
            raise HTTPException(status_code=409, detail=f"Replace this agent in these workflows before deleting it: {names}")
        repositories.delete_agent(identifier)
        return {"deleted": True}

    @app.get("/api/agents/{identifier}/skills", dependencies=[auth], response_model=list[AgentSkill])
    async def agent_skills(identifier: str) -> list[AgentSkill]:
        if not repositories.get_agent(identifier):
            raise HTTPException(status_code=404, detail="Agent not found")
        return repositories.list_agent_skills(identifier)

    @app.post("/api/agents/{identifier}/skills", dependencies=[auth], response_model=AgentSkill)
    async def upload_agent_skill(identifier: str, file: Annotated[UploadFile, File()]) -> AgentSkill:
        if not repositories.get_agent(identifier):
            raise HTTPException(status_code=404, detail="Agent not found")
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.casefold()
        if not filename or suffix not in {".md", ".txt", ".json", ".yaml", ".yml"}:
            raise HTTPException(status_code=400, detail="Skill files must be Markdown, text, JSON, or YAML")
        content_bytes = await file.read(20_001)
        if len(content_bytes) > 20_000:
            raise HTTPException(status_code=413, detail="Each skill file must be 20 KB or smaller")
        try:
            content = content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=400, detail="Skill files must use UTF-8 text encoding") from error
        if "\x00" in content:
            raise HTTPException(status_code=400, detail="Skill files cannot contain binary data")
        existing = repositories.list_agent_skills(identifier)
        replacing = next((item for item in existing if item.name.casefold() == filename.casefold()), None)
        total = sum(item.size_bytes for item in existing) - (replacing.size_bytes if replacing else 0) + len(content_bytes)
        if (len(existing) >= 6 and not replacing) or total > 60_000:
            raise HTTPException(status_code=409, detail="An agent can use up to six skill files and 60 KB total")
        media_type = file.content_type or "text/plain"
        return repositories.save_agent_skill(identifier, filename, media_type, content)

    @app.delete("/api/agents/{agent_id}/skills/{skill_id}", dependencies=[auth])
    async def delete_agent_skill(agent_id: str, skill_id: str) -> dict[str, bool]:
        if not repositories.delete_agent_skill(agent_id, skill_id):
            raise HTTPException(status_code=404, detail="Skill file not found")
        return {"deleted": True}

    @app.get("/api/workflows", dependencies=[auth], response_model=list[Workflow])
    async def workflows() -> list[Workflow]:
        return repositories.list_workflows()

    @app.post("/api/workflows", dependencies=[auth], response_model=Workflow)
    async def create_workflow(payload: WorkflowInput) -> Workflow:
        workflow_levels(payload.spec)
        return repositories.save_workflow(payload)

    @app.post("/api/workflows/draft", dependencies=[auth], response_model=Workflow)
    async def draft_workflow(payload: dict[str, str]) -> Workflow:
        goal = str(payload.get("goal", "")).strip()
        if not goal:
            raise HTTPException(status_code=400, detail="Describe what the workflow should accomplish")
        available_agents = repositories.list_agents()
        if not available_agents:
            raise HTTPException(status_code=409, detail="Create at least one agent before drafting a workflow")
        lowered = goal.casefold()
        nodes: list[dict[str, Any]] = [
            {"id": "input", "type": "input", "label": "Your request", "position": {"x": 40, "y": 180}, "config": {}}
        ]
        edges: list[dict[str, str]] = []
        if any(word in lowered for word in ("compare", "parallel", "independent")) and len(available_agents) > 1:
            nodes.append({"id": "parallel", "type": "parallel", "label": "Work in parallel", "position": {"x": 260, "y": 180}, "config": {}})
            edges.append({"id": "e-input-parallel", "source": "input", "target": "parallel"})
            for index, agent in enumerate(available_agents[:3]):
                node_id = f"agent-{index}"
                nodes.append({"id": node_id, "type": "agent", "label": agent.name, "position": {"x": 500, "y": 70 + index * 150}, "config": {"agent_id": agent.id}})
                edges.append({"id": f"e-parallel-{index}", "source": "parallel", "target": node_id})
            previous = [f"agent-{index}" for index in range(min(3, len(available_agents)))]
        elif any(word in lowered for word in ("review", "revise", "critic")) and len(available_agents) > 1:
            nodes.append({"id": "review", "type": "review", "label": "Draft and review", "position": {"x": 330, "y": 180}, "config": {"agent_id": available_agents[0].id, "reviewer_agent_id": available_agents[1].id, "max_iterations": 3}})
            edges.append({"id": "e-input-review", "source": "input", "target": "review"})
            previous = ["review"]
        else:
            previous = ["input"]
            for index, agent in enumerate(available_agents[:3]):
                node_id = f"agent-{index}"
                nodes.append({"id": node_id, "type": "agent", "label": agent.name, "position": {"x": 290 + index * 240, "y": 180}, "config": {"agent_id": agent.id}})
                edges.append({"id": f"e-seq-{index}", "source": previous[-1], "target": node_id})
                previous = [node_id]
        if any(word in lowered for word in ("approve", "approval", "confirm")):
            nodes.append({"id": "approval", "type": "approval", "label": "Human approval", "position": {"x": 820, "y": 180}, "config": {"reason": "Review the draft before it becomes final"}})
            for source in previous:
                edges.append({"id": f"e-{source}-approval", "source": source, "target": "approval"})
            previous = ["approval"]
        nodes.append({"id": "output", "type": "output", "label": "Final result", "position": {"x": 1060, "y": 180}, "config": {}})
        for source in previous:
            edges.append({"id": f"e-{source}-output", "source": source, "target": "output"})
        draft = WorkflowInput.model_validate({
            "name": goal[:72], "description": f"Drafted locally from: {goal}",
            "spec": {"version": "1.0", "nodes": nodes, "edges": edges, "limits": {"max_iterations": 6, "timeout_seconds": 900}},
        })
        workflow_levels(draft.spec)
        return repositories.save_workflow(draft)

    @app.put("/api/workflows/{identifier}", dependencies=[auth], response_model=Workflow)
    async def update_workflow(identifier: str, payload: WorkflowInput) -> Workflow:
        if not repositories.get_workflow(identifier):
            raise HTTPException(status_code=404, detail="Workflow not found")
        workflow_levels(payload.spec)
        return repositories.save_workflow(payload, identifier)

    @app.delete("/api/workflows/{identifier}", dependencies=[auth])
    async def delete_workflow(identifier: str) -> dict[str, bool]:
        if not repositories.get_workflow(identifier):
            raise HTTPException(status_code=404, detail="Workflow not found")
        if repositories.workflow_has_active_runs(identifier):
            raise HTTPException(status_code=409, detail="Stop the active run before deleting this workflow")
        repositories.delete_workflow(identifier)
        return {"deleted": True}

    @app.post("/api/workflows/{identifier}/run", dependencies=[auth])
    async def run_workflow(identifier: str, payload: RunRequest) -> dict[str, Any]:
        if not repositories.get_workflow(identifier):
            raise HTTPException(status_code=404, detail="Workflow not found")
        if payload.local_paths:
            input_text, attachments = await prepare_run_input(payload.input, payload.local_paths)
            return engine.start(identifier, input_text, attachments)
        return engine.start(identifier, payload.input)

    @app.post("/api/workflows/{identifier}/run-with-files", dependencies=[auth])
    async def run_workflow_with_files(
        identifier: str,
        input: Annotated[str, Form(min_length=1, max_length=1_500_000)],
        local_paths: Annotated[str, Form()] = "[]",
        files: Annotated[list[UploadFile] | None, File()] = None,
    ) -> dict[str, Any]:
        if not repositories.get_workflow(identifier):
            raise HTTPException(status_code=404, detail="Workflow not found")
        try:
            parsed_paths = json.loads(local_paths)
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="Local attachment paths must be a JSON list") from error
        if not isinstance(parsed_paths, list) or any(not isinstance(item, str) for item in parsed_paths):
            raise HTTPException(status_code=400, detail="Local attachment paths must be a JSON list")
        input_text, attachments = await prepare_run_input(input, parsed_paths, files or [])
        return engine.start(identifier, input_text, attachments)

    @app.post("/api/hooks/{identifier}", dependencies=[auth])
    async def local_hook(identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not repositories.get_workflow(identifier):
            raise HTTPException(status_code=404, detail="Workflow not found")
        return engine.start(identifier, json.dumps(payload, ensure_ascii=False))

    @app.get("/api/runs", dependencies=[auth])
    async def runs() -> list[dict[str, Any]]:
        return repositories.list_runs()

    @app.get("/api/runs/{identifier}", dependencies=[auth])
    async def run_detail(identifier: str) -> dict[str, Any]:
        run = repositories.get_run(identifier)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.post("/api/runs/{identifier}/approval", dependencies=[auth])
    async def approve_run(identifier: str, payload: ApprovalRequest) -> dict[str, bool]:
        try:
            await engine.resume(identifier, payload.approved, payload.response)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"resumed": True}

    @app.post("/api/runs/{identifier}/cancel", dependencies=[auth])
    async def cancel_run(identifier: str) -> dict[str, bool]:
        try:
            cancelled = await engine.cancel(identifier)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"cancelled": cancelled}

    @app.get("/api/schedules", dependencies=[auth])
    async def schedules() -> list[dict[str, object]]:
        return scheduler.list()

    @app.post("/api/schedules", dependencies=[auth])
    async def create_schedule(payload: ScheduleInput) -> dict[str, object]:
        if not repositories.get_workflow(payload.workflow_id):
            raise HTTPException(status_code=404, detail="Workflow not found")
        return scheduler.create(payload.workflow_id, payload.interval_minutes, payload.input, payload.enabled)

    @app.get("/api/workflows/{identifier}/export", dependencies=[auth])
    async def export_workflow(identifier: str) -> FileResponse:
        destination = settings.exports_dir / f"{identifier}.agentpack"
        try:
            export_agentpack(repositories, identifier, destination)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(destination, media_type="application/zip", filename=destination.name)

    @app.post("/api/agentpacks/import", dependencies=[auth])
    async def import_workflow(file: Annotated[UploadFile, File()]) -> dict[str, str]:
        if not file.filename or not file.filename.lower().endswith(".agentpack"):
            raise HTTPException(status_code=400, detail="Choose a .agentpack file")
        with tempfile.NamedTemporaryFile(suffix=".agentpack", delete=False) as temporary:
            temporary.write(await file.read())
            path = Path(temporary.name)
        try:
            identifier = import_agentpack(repositories, path)
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        finally:
            path.unlink(missing_ok=True)
        return {"workflow_id": identifier}

    return app
