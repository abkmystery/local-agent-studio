from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ModelDescriptor(BaseModel):
    id: str
    name: str
    provider_id: str
    publisher: str = "Unknown"
    source_url: str | None = None
    license_name: str = "Unknown"
    license_url: str | None = None
    commercial_use: bool | None = None
    redistribution: bool | None = None
    acceptance_required: bool = False
    quantization: str | None = None
    size_bytes: int | None = None
    context_length: int | None = None
    memory_estimate_bytes: int | None = None
    capabilities: list[str] = Field(default_factory=list)
    installed: bool = True
    loaded: bool = False


class ProviderStatus(BaseModel):
    id: str
    name: str
    kind: Literal["embedded", "external"]
    available: bool
    base_url: str
    detail: str
    license_name: str
    redistributable: bool


class AgentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    provider_id: str
    model_id: str
    instructions: str = Field(min_length=1, max_length=50_000)
    config: dict[str, Any] = Field(default_factory=dict)


class Agent(AgentInput):
    id: str
    created_at: str
    updated_at: str


class AgentSkill(BaseModel):
    id: str
    agent_id: str
    name: str
    media_type: str
    size_bytes: int
    created_at: str


class EmailConfigInput(BaseModel):
    provider: Literal["gmail", "outlook", "yahoo", "custom"] = "gmail"
    sender_email: str = Field(min_length=3, max_length=320)
    sender_name: str = Field(default="", max_length=120)
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(default="", max_length=1_000)
    host: str = Field(default="", max_length=253)
    port: int = Field(default=465, ge=1, le=65535)
    security: Literal["ssl", "starttls"] = "ssl"


class EmailTestInput(BaseModel):
    to: str = Field(min_length=3, max_length=320)


class WorkflowNode(BaseModel):
    id: str
    type: Literal["input", "agent", "function", "parallel", "router", "approval", "review", "output"]
    label: str
    position: dict[str, float] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    condition: str | None = None


class WorkflowSpec(BaseModel):
    version: Literal["1.0"] = "1.0"
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    limits: dict[str, int] = Field(
        default_factory=lambda: {"max_iterations": 6, "timeout_seconds": 900}
    )

    @field_validator("nodes")
    @classmethod
    def unique_nodes(cls, nodes: list[WorkflowNode]) -> list[WorkflowNode]:
        identifiers = [node.id for node in nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Workflow node identifiers must be unique")
        return nodes


class WorkflowInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    spec: WorkflowSpec


class Workflow(WorkflowInput):
    id: str
    created_at: str
    updated_at: str


class RunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=1_500_000)
    local_paths: list[str] = Field(default_factory=list, max_length=5)


class ApprovalRequest(BaseModel):
    approved: bool
    response: str = ""


class ScheduleInput(BaseModel):
    workflow_id: str
    interval_minutes: int = Field(ge=1, le=525_600)
    input: str
    enabled: bool = True


class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str
    approval_policy: Literal["never", "mutating", "always"]
    execution: Literal["local"] = "local"
    input_schema: dict[str, Any]
