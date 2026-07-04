from __future__ import annotations

from typing import Any


CAPABILITY_DEFAULTS: dict[str, bool] = {
    "attachments": True,
    "file_access": True,
    "web_access": False,
    "code_execution": False,
    "mcp": False,
}

TOOL_CAPABILITIES: dict[str, str] = {
    "read_file": "file_access",
    "write_file": "file_access",
    "create_word": "file_access",
    "create_excel": "file_access",
    "search_files": "file_access",
    "http_request": "web_access",
    "python_code": "code_execution",
    "mcp_call": "mcp",
}


def normalized_capabilities(value: Any, defaults: dict[str, bool] | None = None) -> dict[str, bool]:
    baseline = dict(defaults or CAPABILITY_DEFAULTS)
    if isinstance(value, dict):
        for key in baseline:
            if key in value:
                baseline[key] = bool(value[key])
    return baseline


class CapabilityPolicy:
    def __init__(self, database: Any, repositories: Any) -> None:
        self.database = database
        self.repositories = repositories

    def studio(self) -> dict[str, bool]:
        return normalized_capabilities(self.database.setting("capabilities", {}))

    def agent(self, agent_id: str) -> dict[str, bool]:
        agent = self.repositories.get_agent(agent_id)
        if not agent:
            raise ValueError("Choose an agent permission profile for this function")
        requested = normalized_capabilities(agent.config.get("capabilities", {}))
        studio = self.studio()
        return {key: bool(studio[key] and requested[key]) for key in CAPABILITY_DEFAULTS}

    def require(self, capability: str, agent_id: str | None = None) -> None:
        if capability not in CAPABILITY_DEFAULTS:
            raise ValueError(f"Unknown capability: {capability}")
        if not self.studio()[capability]:
            raise PermissionError(
                f"{capability.replace('_', ' ').title()} is disabled for the whole studio. Enable it in Settings first."
            )
        if agent_id and not self.agent(agent_id)[capability]:
            raise PermissionError(
                f"{capability.replace('_', ' ').title()} is disabled for the selected agent. Edit that agent's permissions."
            )

    def require_tool(self, tool_id: str, agent_id: str | None) -> None:
        capability = TOOL_CAPABILITIES.get(tool_id)
        if not capability:
            return
        # Network and executable extensions must be attributed to an agent so a
        # workflow cannot silently bypass its per-agent policy.
        if capability in {"web_access", "code_execution", "mcp"} and not agent_id:
            raise PermissionError("Choose which agent authorizes this privileged function")
        self.require(capability, agent_id)
