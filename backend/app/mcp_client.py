from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class MCPManager:
    """A deliberately small stdio-only MCP client boundary."""

    def __init__(self, database: Any, secrets: Any) -> None:
        self.database = database
        self.secrets = secrets

    def _load(self) -> list[dict[str, Any]]:
        encrypted = self.database.setting("mcp_servers_enc")
        if isinstance(encrypted, str):
            try:
                value = json.loads(self.secrets.decrypt(encrypted) or "[]")
                return value if isinstance(value, list) else []
            except (ValueError, json.JSONDecodeError):
                return []
        # One-time migration from the early plaintext development schema.
        legacy = self.database.setting("mcp_servers", [])
        if legacy:
            self._save(legacy)
            self.database.set_setting("mcp_servers", [])
        return legacy if isinstance(legacy, list) else []

    def _save(self, servers: list[dict[str, Any]]) -> None:
        self.database.set_setting(
            "mcp_servers_enc", self.secrets.encrypt(json.dumps(servers, ensure_ascii=False))
        )

    def list_servers(self) -> list[dict[str, Any]]:
        servers = self._load()
        return [
            {
                "id": item["id"], "name": item["name"], "command": item["command"],
                "args": item.get("args", []), "enabled": bool(item.get("enabled", False)),
                "transport": "stdio", "warning_acknowledged": bool(item.get("warning_acknowledged", False)),
            }
            for item in servers if isinstance(item, dict)
        ]

    def save_server(self, value: dict[str, Any]) -> dict[str, Any]:
        identifier = str(value.get("id", "")).strip() or os.urandom(12).hex()
        name = str(value.get("name", "")).strip()[:120]
        command = str(value.get("command", "")).strip().strip('"')
        args = value.get("args", [])
        if not name or not command or not isinstance(args, list) or len(args) > 30:
            raise ValueError("Enter a name, executable path, and at most 30 arguments")
        if any(not isinstance(item, str) or len(item) > 1000 for item in args):
            raise ValueError("Every MCP argument must be plain text under 1,000 characters")
        resolved = Path(command).expanduser()
        if not resolved.is_absolute() or not resolved.is_file():
            raise ValueError("Use the full path to an existing MCP executable")
        command = str(resolved.resolve())
        item = {
            "id": identifier, "name": name, "command": command, "args": args,
            "enabled": bool(value.get("enabled", False)), "transport": "stdio",
            "warning_acknowledged": bool(value.get("warning_acknowledged", False)),
        }
        if item["enabled"] and not item["warning_acknowledged"]:
            raise PermissionError("Acknowledge that this MCP server runs with your Windows account permissions")
        servers = self._load()
        servers = [existing for existing in servers if existing.get("id") != identifier] + [item]
        self._save(servers)
        return next(server for server in self.list_servers() if server["id"] == identifier)

    def delete_server(self, identifier: str) -> bool:
        servers = self._load()
        remaining = [item for item in servers if item.get("id") != identifier]
        if len(remaining) == len(servers):
            return False
        self._save(remaining)
        return True

    def _server(self, identifier: str) -> dict[str, Any]:
        server = next((item for item in self._load() if item.get("id") == identifier), None)
        if not server or not server.get("enabled") or not server.get("warning_acknowledged"):
            raise PermissionError("This MCP server is missing, disabled, or awaiting risk acknowledgement")
        return server

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        return {
            key: os.environ[key]
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
            if os.environ.get(key)
        }

    async def list_tools(self, identifier: str) -> list[dict[str, Any]]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server = self._server(identifier)
        parameters = StdioServerParameters(
            command=server["command"], args=server.get("args", []), env=self._minimal_environment()
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    {"name": tool.name, "description": tool.description or "", "input_schema": tool.inputSchema}
                    for tool in result.tools
                ]

    async def call(self, identifier: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server = self._server(identifier)
        parameters = StdioServerParameters(
            command=server["command"], args=server.get("args", []), env=self._minimal_environment()
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                content = [item.model_dump(mode="json") for item in result.content]
                if len(json.dumps(content)) > 262_144:
                    raise ValueError("MCP result exceeded the 256 KB safety limit")
                return {"content": content, "is_error": bool(result.isError)}
