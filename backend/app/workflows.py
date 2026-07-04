from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from .db import utc_now
from .providers import ProviderManager
from .repositories import Repositories
from .schemas import WorkflowEdge, WorkflowNode, WorkflowSpec
from .tools import ApprovalRequired, ToolRegistry
from .capabilities import CapabilityPolicy


class WorkflowValidationError(ValueError):
    pass


def workflow_levels(spec: WorkflowSpec) -> list[list[WorkflowNode]]:
    nodes = {node.id: node for node in spec.nodes}
    if not nodes:
        raise WorkflowValidationError("A workflow needs at least one node")
    indegree = {identifier: 0 for identifier in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in spec.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise WorkflowValidationError("Every edge must reference an existing node")
        indegree[edge.target] += 1
        outgoing[edge.source].append(edge.target)
    frontier = [identifier for identifier, count in indegree.items() if count == 0]
    levels: list[list[WorkflowNode]] = []
    visited = 0
    while frontier:
        levels.append([nodes[identifier] for identifier in frontier])
        next_frontier: list[str] = []
        for identifier in frontier:
            visited += 1
            for target in outgoing[identifier]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    next_frontier.append(target)
        frontier = next_frontier
    if visited != len(nodes):
        raise WorkflowValidationError("Free-form cycles are not allowed; use a bounded Review node")
    return levels


def optimized_inference_options(config: dict[str, Any]) -> dict[str, Any]:
    """Keep local-agent defaults responsive on ordinary 16 GB computers."""
    options = dict(config)
    try:
        requested_context = int(options.get("num_ctx", 4096))
    except (TypeError, ValueError):
        requested_context = 4096
    try:
        requested_output = int(options.get("num_predict", options.get("max_tokens", 128)))
    except (TypeError, ValueError):
        requested_output = 128
    options["num_ctx"] = max(512, min(requested_context, 4096))
    options["num_predict"] = max(32, min(requested_output, 256))
    options.pop("max_tokens", None)
    return options


class WorkflowEngine:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def __init__(
        self,
        repositories: Repositories,
        providers: ProviderManager,
        tools: ToolRegistry,
        capability_policy: CapabilityPolicy | None = None,
    ) -> None:
        self.repositories = repositories
        self.providers = providers
        self.tools = tools
        self.capability_policy = capability_policy or CapabilityPolicy(repositories.db, repositories)
        self.tasks: dict[str, asyncio.Task[None]] = {}

    @staticmethod
    def _initial_state(spec: WorkflowSpec) -> dict[str, Any]:
        return {
            "level": 0,
            "results": {},
            "inactive_edges": [],
            "steps": [
                {
                    "node_id": node.id,
                    "label": node.label,
                    "type": node.type,
                    "status": "pending",
                }
                for node in spec.nodes
            ],
        }

    def start(
        self, workflow_id: str, input_text: str, attachments: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        workflow = self.repositories.get_workflow(workflow_id)
        if not workflow:
            raise ValueError("Workflow does not exist")
        initial_state = self._initial_state(workflow.spec)
        initial_state["attachments"] = attachments or []
        run = self.repositories.create_run(workflow_id, input_text, initial_state)
        self.tasks[run["id"]] = asyncio.create_task(self.execute(run["id"]))
        return run

    async def cancel(self, run_id: str) -> bool:
        run = self.repositories.get_run(run_id, include_private=True)
        if not run:
            raise ValueError("Run not found")
        if run["status"] in self.TERMINAL_STATUSES:
            return False
        state = run["state"]
        for step in state.get("steps", []):
            if step.get("status") in {"running", "waiting_approval"}:
                step.update({"status": "cancelled", "finished_at": utc_now()})
            elif step.get("status") == "pending":
                step["status"] = "skipped"
        state.pop("pending_approval", None)
        self.repositories.update_run(
            run_id, status="cancelled", state=state, error="Stopped by user", finished_at=utc_now()
        )
        task = self.tasks.get(run_id)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return True

    async def resume(self, run_id: str, approved: bool, response: str = "") -> None:
        run = self.repositories.get_run(run_id, include_private=True)
        if not run or run["status"] != "waiting_approval":
            raise ValueError("This run is not waiting for approval")
        state = run["state"]
        pending = state.get("pending_approval") or {}
        node_id = str(pending.get("node_id", ""))
        if not approved:
            self._update_step(state, node_id, status="cancelled", finished_at=utc_now(), error="Rejected by user")
            state.pop("pending_approval", None)
            self.repositories.update_run(
                run_id, status="cancelled", state=state, error="Approval rejected by user", finished_at=utc_now()
            )
            return
        state["approval"] = {"approved": True, "response": response, **pending}
        state.pop("pending_approval", None)
        self.repositories.update_run(run_id, status="queued", state=state)
        self.tasks[run_id] = asyncio.create_task(self.execute(run_id))

    @staticmethod
    def _update_step(state: dict[str, Any], node_id: str, **changes: Any) -> None:
        for step in state.get("steps", []):
            if step.get("node_id") == node_id:
                step.update(changes)
                return

    @staticmethod
    def _step_status(state: dict[str, Any], node_id: str) -> str:
        for step in state.get("steps", []):
            if step.get("node_id") == node_id:
                return str(step.get("status", "pending"))
        return "pending"

    @staticmethod
    def _preview(value: Any, limit: int = 1200) -> str:
        text = str(value)
        return text if len(text) <= limit else text[:limit] + "…"

    @staticmethod
    async def _node_result(
        node: WorkflowNode,
        execution: Any,
    ) -> tuple[WorkflowNode, tuple[str, Any, tuple[int, int], set[str]] | None, Exception | None]:
        try:
            return node, await execution, None
        except Exception as error:
            return node, None, error

    def _persist_progress(
        self,
        run_id: str,
        state: dict[str, Any],
        results: dict[str, Any],
        inactive_edges: set[str],
        prompt_tokens: int,
        completion_tokens: int,
        **changes: Any,
    ) -> None:
        state.update({"results": results, "inactive_edges": list(inactive_edges)})
        self.repositories.update_run(
            run_id,
            state=state,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            **changes,
        )

    async def execute(self, run_id: str) -> None:
        run = self.repositories.get_run(run_id, include_private=True)
        if not run:
            return
        workflow = self.repositories.get_workflow(run["workflow_id"])
        if not workflow:
            self.repositories.update_run(run_id, status="failed", error="Workflow no longer exists", finished_at=utc_now())
            return
        current_task = asyncio.current_task()
        state = run["state"]
        state.setdefault("steps", self._initial_state(workflow.spec)["steps"])
        results: dict[str, Any] = state.get("results", {})
        inactive_edges = set(state.get("inactive_edges", []))
        prompt_tokens = int(run["prompt_tokens"])
        completion_tokens = int(run["completion_tokens"])
        try:
            levels = workflow_levels(workflow.spec)
            self.repositories.update_run(run_id, status="running", state=state)

            for level_index in range(int(state.get("level", 0)), len(levels)):
                level = levels[level_index]
                reachable = [
                    node for node in level
                    if self._is_reachable(node.id, workflow.spec.edges, results, inactive_edges)
                    and self._step_status(state, node.id) != "completed"
                ]
                for node in level:
                    if node not in reachable and self._step_status(state, node.id) == "pending":
                        self._update_step(state, node.id, status="skipped")

                approval_nodes = [node for node in reachable if node.type == "approval"]
                if approval_nodes and "approval" not in state:
                    node = approval_nodes[0]
                    preview = self._inputs(node.id, workflow.spec, run["input"], results, inactive_edges)
                    pending = {
                        "node_id": node.id,
                        "reason": node.config.get("reason", node.label),
                        "instructions": node.config.get("instructions", "Review the incoming result before continuing."),
                        "allow_response": bool(node.config.get("allow_response", False)),
                        "response_label": node.config.get("response_label", "Optional note"),
                    }
                    if node.config.get("show_preview", True):
                        pending["preview"] = self._preview(preview, 4000)
                    state.update({"level": level_index, "pending_approval": pending})
                    self._update_step(state, node.id, status="waiting_approval", started_at=utc_now())
                    self._persist_progress(
                        run_id, state, results, inactive_edges, prompt_tokens, completion_tokens,
                        status="waiting_approval",
                    )
                    return

                for node in reachable:
                    self._update_step(state, node.id, status="running", started_at=utc_now(), error=None)
                self._persist_progress(run_id, state, results, inactive_edges, prompt_tokens, completion_tokens)

                tasks = [
                    asyncio.create_task(self._node_result(
                        node,
                        self._execute_node(node, workflow.spec, run["input"], results, inactive_edges, state),
                    ))
                    for node in reachable
                ]
                paused = False
                for completed in asyncio.as_completed(tasks):
                    node, outcome, error = await completed
                    if error:
                        if isinstance(error, ApprovalRequired):
                            pending = {
                                "node_id": node.id,
                                "tool_id": error.tool_id,
                                "arguments": error.arguments,
                                "reason": error.reason,
                                "instructions": "Check the exact tool and arguments before allowing this action.",
                                "allow_response": False,
                                "preview": self._preview(json.dumps(error.arguments, ensure_ascii=False, indent=2), 4000),
                            }
                            state.update({"level": level_index, "pending_approval": pending})
                            self._update_step(state, node.id, status="waiting_approval")
                            for task in tasks:
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
                            self._persist_progress(
                                run_id, state, results, inactive_edges, prompt_tokens, completion_tokens,
                                status="waiting_approval",
                            )
                            paused = True
                            break
                        self._update_step(
                            state, node.id, status="failed", finished_at=utc_now(), error=str(error)
                        )
                        self._persist_progress(run_id, state, results, inactive_edges, prompt_tokens, completion_tokens)
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        raise error
                    assert outcome is not None
                    node_id, value, usage, disabled = outcome
                    results[node_id] = value
                    prompt_tokens += usage[0]
                    completion_tokens += usage[1]
                    inactive_edges.update(disabled)
                    self._update_step(
                        state,
                        node_id,
                        status="completed",
                        finished_at=utc_now(),
                        output_preview=self._preview(value),
                        prompt_tokens=usage[0],
                        completion_tokens=usage[1],
                    )
                    self._persist_progress(run_id, state, results, inactive_edges, prompt_tokens, completion_tokens)
                if paused:
                    return
                if approval_nodes:
                    state.pop("approval", None)
                state["level"] = level_index + 1
                self._persist_progress(run_id, state, results, inactive_edges, prompt_tokens, completion_tokens)

            output_nodes = [node for node in workflow.spec.nodes if node.type == "output"]
            output = results.get(output_nodes[-1].id) if output_nodes else list(results.values())[-1]
            self._persist_progress(
                run_id, state, results, inactive_edges, prompt_tokens, completion_tokens,
                status="completed", output=str(output), finished_at=utc_now(),
            )
        except asyncio.CancelledError:
            latest = self.repositories.get_run(run_id, include_private=True)
            if latest and latest["status"] != "cancelled":
                self.repositories.update_run(run_id, status="cancelled", state=state, error="Stopped", finished_at=utc_now())
            raise
        except Exception as error:
            self.repositories.update_run(run_id, status="failed", state=state, error=str(error), finished_at=utc_now())
        finally:
            if self.tasks.get(run_id) is current_task:
                self.tasks.pop(run_id, None)

    def _is_reachable(
        self, node_id: str, edges: list[WorkflowEdge], results: dict[str, Any], inactive_edges: set[str]
    ) -> bool:
        incoming = [edge for edge in edges if edge.target == node_id]
        if not incoming:
            return True
        active = [edge for edge in incoming if edge.id not in inactive_edges]
        return bool(active) and all(edge.source in results for edge in active)

    def _inputs(self, node_id: str, spec: WorkflowSpec, initial: str, results: dict[str, Any], inactive: set[str]) -> str:
        incoming = [edge for edge in spec.edges if edge.target == node_id and edge.id not in inactive]
        values = [results[edge.source] for edge in incoming if edge.source in results]
        return "\n\n".join(str(value) for value in values) if values else initial

    def _tool_arguments(self, tool_id: str, configured: dict[str, Any], input_value: str) -> dict[str, Any]:
        arguments: dict[str, Any] = {}
        schema = self.tools.definitions.get(tool_id).input_schema if tool_id in self.tools.definitions else {}
        for key, raw in configured.items():
            value = input_value if raw == "$input" else raw
            if schema.get(key) in {"object", "any"} and isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            arguments[key] = value
        return arguments

    async def _execute_node(
        self,
        node: WorkflowNode,
        spec: WorkflowSpec,
        initial: str,
        results: dict[str, Any],
        inactive_edges: set[str],
        state: dict[str, Any],
    ) -> tuple[str, Any, tuple[int, int], set[str]]:
        value = self._inputs(node.id, spec, initial, results, inactive_edges)
        disabled: set[str] = set()
        if node.type == "input":
            return node.id, initial, (0, 0), disabled
        if node.type in {"parallel", "output"}:
            return node.id, value, (0, 0), disabled
        if node.type == "approval":
            approval = state.get("approval", {})
            if not approval.get("approved") or approval.get("node_id") != node.id:
                raise PermissionError("The workflow action was rejected")
            state.pop("approval", None)
            return node.id, approval.get("response") or value, (0, 0), disabled
        if node.type == "router":
            selected = node.config.get("default_target")
            lowered = value.casefold()
            for route in node.config.get("routes", []):
                if str(route.get("contains", "")).casefold() in lowered:
                    selected = route.get("target")
                    break
            for edge in spec.edges:
                if edge.source == node.id and edge.target != selected:
                    disabled.add(edge.id)
            return node.id, value, (0, 0), disabled
        if node.type == "function":
            tool_id = str(node.config.get("tool_id", ""))
            if not tool_id:
                raise WorkflowValidationError(f"Function node '{node.label}' needs a tool")
            arguments = self._tool_arguments(tool_id, dict(node.config.get("arguments", {})), value)
            permission_agent_id = str(node.config.get("agent_id", "")).strip() or None
            self.capability_policy.require_tool(tool_id, permission_agent_id)
            approval = state.get("approval", {})
            approved = bool(
                approval.get("approved")
                and approval.get("node_id") == node.id
                and approval.get("tool_id") == tool_id
                and approval.get("arguments") == arguments
            )
            result = await self.tools.execute(tool_id, arguments, approved=approved)
            if approved:
                state.pop("approval", None)
            return node.id, json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result, (0, 0), disabled
        if node.type == "agent":
            result = await self._agent_call(
                str(node.config.get("agent_id", "")), value, list(state.get("attachments", []))
            )
            return node.id, result[0], result[1], disabled
        if node.type == "review":
            primary = str(node.config["agent_id"])
            reviewer = str(node.config["reviewer_agent_id"])
            maximum = min(int(node.config.get("max_iterations", 3)), int(spec.limits.get("max_iterations", 6)))
            total_prompt = total_completion = 0
            draft = value
            for _ in range(maximum):
                draft, usage = await self._agent_call(primary, draft, list(state.get("attachments", [])))
                total_prompt += usage[0]
                total_completion += usage[1]
                critique, usage = await self._agent_call(
                    reviewer,
                    "Reply APPROVED if this satisfies the goal. Otherwise give concise revision instructions.\n\n" + draft,
                    list(state.get("attachments", [])),
                )
                total_prompt += usage[0]
                total_completion += usage[1]
                if critique.strip().upper().startswith("APPROVED"):
                    break
                draft = f"Revise the draft using this feedback:\n{critique}\n\nDraft:\n{draft}"
            return node.id, draft, (total_prompt, total_completion), disabled
        raise WorkflowValidationError(f"Unsupported node type: {node.type}")

    async def _agent_call(
        self, agent_id: str, input_text: str, attachments: list[dict[str, Any]] | None = None
    ) -> tuple[str, tuple[int, int]]:
        agent = self.repositories.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id or '(not selected)'} does not exist")
        if attachments:
            self.capability_policy.require("attachments", agent.id)
        provider = self.providers.get(agent.provider_id)
        if getattr(provider, "cloud", False) and self.repositories.db.setting("offline_mode", False):
            raise RuntimeError("Offline mode is enabled. Turn it off before using a cloud provider.")
        provider_tools: list[dict[str, Any]] | None = None
        if agent.provider_id == "gemini" and self.capability_policy.agent(agent.id)["web_access"]:
            provider_tools = [{"type": "google_search"}]
        skill_context = self.repositories.agent_skill_context(agent.id)
        system_instructions = agent.instructions
        if skill_context:
            system_instructions += (
                "\n\nThe user attached the following skill/reference files to this agent. "
                "Use them as supplementary operating instructions when relevant."
                + skill_context
            )
        async with self.providers.semaphore:
            result = await provider.chat(
                agent.model_id,
                [
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": input_text, "attachments": attachments or []},
                ],
                tools=provider_tools,
                options=optimized_inference_options(agent.config),
            )
        return result.content, (result.prompt_tokens, result.completion_tokens)
