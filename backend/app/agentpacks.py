from __future__ import annotations

import json
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .repositories import Repositories
from .schemas import AgentInput, WorkflowInput


SAFE_AGENT_CONFIG = {"temperature", "top_p", "num_ctx", "num_predict", "max_tokens", "seed", "capabilities"}
SECRET_KEY = re.compile(r"(secret|password|token|api.?key|credential)", re.IGNORECASE)
PATH_KEY = re.compile(r"(path|directory|folder|file)", re.IGNORECASE)


def _scrub(value: Any, key: str = "") -> Any:
    if SECRET_KEY.search(key) or PATH_KEY.search(key):
        return "<removed>"
    if isinstance(value, dict):
        return {item_key: _scrub(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, key) for item in value]
    return value


def export_agentpack(repositories: Repositories, workflow_id: str, destination: Path) -> Path:
    workflow = repositories.get_workflow(workflow_id)
    if not workflow:
        raise ValueError("Workflow does not exist")
    referenced: set[str] = set()
    for node in workflow.spec.nodes:
        for key in ("agent_id", "reviewer_agent_id"):
            if node.config.get(key):
                referenced.add(str(node.config[key]))
    agents = []
    for identifier in referenced:
        agent = repositories.get_agent(identifier)
        if agent:
            payload = agent.model_dump(exclude={"created_at", "updated_at"})
            payload["config"] = {key: value for key, value in agent.config.items() if key in SAFE_AGENT_CONFIG}
            agents.append(payload)
    workflow_payload = workflow.model_dump(exclude={"created_at", "updated_at"})
    workflow_payload["spec"] = _scrub(workflow_payload["spec"])
    manifest = {
        "format": "local-agent-studio.agentpack",
        "version": "1.0",
        "name": workflow.name,
        "contains_secrets": False,
        "contains_models": False,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("agents.json", json.dumps(agents, indent=2))
        archive.writestr("workflow.json", json.dumps(workflow_payload, indent=2))
    return destination


def import_agentpack(repositories: Repositories, source: Path) -> str:
    with zipfile.ZipFile(source, "r") as archive:
        names = set(archive.namelist())
        if not {"manifest.json", "agents.json", "workflow.json"}.issubset(names):
            raise ValueError("This file is not a complete .agentpack")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != "local-agent-studio.agentpack" or manifest.get("version") != "1.0":
            raise ValueError("Unsupported .agentpack format")
        agents = json.loads(archive.read("agents.json"))
        workflow = json.loads(archive.read("workflow.json"))
    identifiers: dict[str, str] = {}
    for item in agents:
        old_id = item.pop("id")
        saved = repositories.save_agent(AgentInput.model_validate(item))
        identifiers[old_id] = saved.id
    for node in workflow["spec"]["nodes"]:
        for key in ("agent_id", "reviewer_agent_id"):
            if node.get("config", {}).get(key) in identifiers:
                node["config"][key] = identifiers[node["config"][key]]
    workflow.pop("id", None)
    workflow["name"] = f"{workflow['name']} (imported)"
    return repositories.save_workflow(WorkflowInput.model_validate(workflow)).id
