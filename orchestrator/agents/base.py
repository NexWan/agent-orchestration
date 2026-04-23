from __future__ import annotations

import inspect
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable


class AgentRole(Enum):
    ARCHITECT = "architect"
    BACKEND = "backend"
    FRONTEND = "frontend"
    QA = "qa"


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_FEEDBACK = "waiting_for_feedback"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentEventType(Enum):
    AGENT_STARTED = "agent_started"
    STATUS_CHANGED = "status_changed"
    MESSAGE = "message"
    TOOL_ACTIVITY = "tool_activity"
    FILE_CHANGED = "file_changed"
    APPROVAL_REQUESTED = "approval_requested"
    TURN_COMPLETED = "turn_completed"
    AGENT_FAILED = "agent_failed"


@dataclass(slots=True)
class UsageMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def merge(self, other: "UsageMetrics") -> "UsageMetrics":
        return UsageMetrics(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass(slots=True)
class AgentEvent:
    event_type: AgentEventType
    agent_name: str
    role: AgentRole
    message: str = ""
    status: AgentStatus | None = None
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FeedbackRequest:
    agent_name: str
    role: AgentRole
    prompt: str
    required: bool = False


@dataclass(slots=True)
class AgentResult:
    success: bool
    agent_name: str
    role: AgentRole
    output: str = ""
    files_written: list[str] = field(default_factory=list)
    error: str | None = None
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    duration_seconds: float = 0.0
    workspace_path: str = ""
    artifact_ids: list[str] = field(default_factory=list)
    final_status: AgentStatus = AgentStatus.PENDING

    @property
    def tokens_used(self) -> int:
        return self.usage.total_tokens

    def __bool__(self) -> bool:
        return self.success


EventHandler = Callable[[AgentEvent], Awaitable[None] | None]
FeedbackProvider = Callable[[FeedbackRequest], Awaitable[str | None] | str | None]


class AgentAdapter(ABC):
    def __init__(self, working_dir: str | Path):
        self.cwd = Path(working_dir)
        self.cwd.mkdir(parents=True, exist_ok=True)

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def role(self) -> AgentRole:
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        context: dict[str, Any],
        event_handler: EventHandler | None = None,
        feedback_provider: FeedbackProvider | None = None,
    ) -> AgentResult:
        raise NotImplementedError

    def build_prompt(self, task: str, context: dict[str, Any]) -> str:
        project = context.get("project_description", "")
        stage = context.get("stage_name", self.role.value)
        workspace_plan = context.get("workspace_plan")
        artifact_summary = self._artifact_summary(context.get("artifacts", []))

        workspace_summary = ""
        if workspace_plan is not None:
            workspace_summary = (
                f"\nWorkspace root: {workspace_plan.root}\n"
                f"Your writable workspace: {self.cwd}\n"
            )

        return (
            f"Project Description: {project}\n"
            f"Stage: {stage}\n"
            f"Role: {self.role.value}\n"
            f"{workspace_summary}"
            f"{artifact_summary}\n"
            f"Task:\n{task}\n\n"
            "Important constraints:\n"
            "- Read the provided artifacts before making changes.\n"
            "- Write real files to the filesystem instead of returning code in prose.\n"
            "- Stay inside your assigned workspace unless the task explicitly instructs otherwise.\n"
            "- Keep final chat output short and summarize what you changed.\n"
        )

    async def _emit(self, event_handler: EventHandler | None, event: AgentEvent) -> None:
        if event_handler is None:
            return
        result = event_handler(event)
        if inspect.isawaitable(result):
            await result

    async def _request_feedback(
        self,
        feedback_provider: FeedbackProvider | None,
        prompt: str,
        required: bool = False,
    ) -> str | None:
        if feedback_provider is None:
            return None
        result = feedback_provider(
            FeedbackRequest(
                agent_name=self.name,
                role=self.role,
                prompt=prompt,
                required=required,
            )
        )
        if inspect.isawaitable(result):
            return await result
        return result

    def _artifact_summary(self, artifacts: list[dict[str, Any]]) -> str:
        if not artifacts:
            return ""
        lines = ["Artifacts available to you:"]
        for artifact in artifacts:
            artifact_type = artifact.get("artifact_type", "artifact")
            path = artifact.get("path", "")
            producer = artifact.get("producer", "")
            lines.append(f"- {artifact_type}: {path} (from {producer})")
        return "\n".join(lines)

    def _snapshot_workspace(self) -> dict[str, int]:
        snapshot: dict[str, int] = {}
        for path in self.cwd.rglob("*"):
            if path.is_file():
                snapshot[self._display_path(path)] = path.stat().st_mtime_ns
        return snapshot

    def _detect_workspace_changes(self, before_snapshot: dict[str, int]) -> list[str]:
        changed: list[str] = []
        after_snapshot = self._snapshot_workspace()
        for path, mtime in after_snapshot.items():
            if before_snapshot.get(path) != mtime:
                changed.append(path)
        return sorted(changed)

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.cwd.resolve()))
        except ValueError:
            return str(path.resolve())

    def _new_result(
        self,
        *,
        success: bool,
        output: str = "",
        files_written: list[str] | None = None,
        error: str | None = None,
        usage: UsageMetrics | None = None,
        workspace_path: str | None = None,
        artifact_ids: list[str] | None = None,
        final_status: AgentStatus,
        started_at: float,
    ) -> AgentResult:
        return AgentResult(
            success=success,
            agent_name=self.name,
            role=self.role,
            output=output,
            files_written=files_written or [],
            error=error,
            usage=usage or UsageMetrics(),
            duration_seconds=max(time.perf_counter() - started_at, 0.0),
            workspace_path=workspace_path or str(self.cwd),
            artifact_ids=artifact_ids or [],
            final_status=final_status,
        )
