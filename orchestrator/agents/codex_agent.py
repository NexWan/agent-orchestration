from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from codex_app_server import AsyncCodex, AppServerConfig
from codex_app_server._inputs import TextInput
from codex_app_server.generated.v2_all import (
    AgentMessageDeltaNotification,
    AgentMessageThreadItem,
    AskForApproval,
    AskForApprovalValue,
    CommandExecutionOutputDeltaNotification,
    CommandExecutionThreadItem,
    FileChangeOutputDeltaNotification,
    FileChangeThreadItem,
    ItemCompletedNotification,
    Personality,
    ReasoningEffort,
    SandboxMode,
    ThreadTokenUsage,
    TurnCompletedNotification,
)

from orchestrator.agents.base import (
    AgentAdapter,
    AgentEvent,
    AgentEventType,
    AgentResult,
    AgentRole,
    AgentStatus,
    EventHandler,
    FeedbackProvider,
    UsageMetrics,
)
from orchestrator.config import get_settings


class CodexWorkspaceAgent(AgentAdapter):
    def __init__(
        self,
        *,
        working_dir: str | Path,
        agent_name: str,
        role: AgentRole,
        task_guidance: str,
        model: str | None = None,
    ):
        super().__init__(working_dir=working_dir)
        self._name = agent_name
        self._role = role
        self.task_guidance = task_guidance
        self.model = model

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> AgentRole:
        return self._role

    def build_prompt(self, task: str, context: dict[str, Any]) -> str:
        return f"{super().build_prompt(task, context)}\nRole-specific guidance:\n{self.task_guidance}\n"

    async def execute(
        self,
        prompt: str,
        context: dict[str, Any],
        event_handler: EventHandler | None = None,
        feedback_provider: FeedbackProvider | None = None,
    ) -> AgentResult:
        full_prompt = self.build_prompt(prompt, context)
        before_snapshot = self._snapshot_workspace()
        started_at = time.perf_counter()
        settings = get_settings()
        output_parts: list[str] = []
        files_written: list[str] = []
        usage = UsageMetrics()

        await self._emit(
            event_handler,
            AgentEvent(
                event_type=AgentEventType.AGENT_STARTED,
                agent_name=self.name,
                role=self.role,
                message=f"Working in {self.cwd}",
                status=AgentStatus.RUNNING,
            ),
        )

        try:
            async with AsyncCodex(config=self._app_server_config()) as codex:
                thread = await codex.thread_start(
                    cwd=str(self.cwd.resolve()),
                    model=self.model or settings.codex_model,
                    approval_policy=AskForApproval(root=AskForApprovalValue.never),
                    personality=Personality.pragmatic,
                    sandbox=SandboxMode.workspace_write,
                )

                next_prompt = full_prompt
                while True:
                    turn = await thread.turn(
                        TextInput(next_prompt),
                        effort=ReasoningEffort.medium,
                    )
                    turn_output, turn_files, turn_usage = await self._collect_turn_result(
                        turn.stream(),
                        turn.id,
                        event_handler=event_handler,
                    )
                    if turn_output:
                        output_parts.append(turn_output)
                    for path in turn_files:
                        if path not in files_written:
                            files_written.append(path)
                    if turn_usage is not None:
                        usage = usage.merge(self._usage_from_thread(turn_usage))

                    await self._emit(
                        event_handler,
                        AgentEvent(
                            event_type=AgentEventType.STATUS_CHANGED,
                            agent_name=self.name,
                            role=self.role,
                            message="Waiting for feedback",
                            status=AgentStatus.WAITING_FOR_FEEDBACK,
                        ),
                    )
                    feedback = await self._request_feedback(
                        feedback_provider,
                        f"Feedback for {self.name}. Press Enter to continue.",
                    )
                    if not feedback:
                        break
                    next_prompt = feedback
                    await self._emit(
                        event_handler,
                        AgentEvent(
                            event_type=AgentEventType.STATUS_CHANGED,
                            agent_name=self.name,
                            role=self.role,
                            message="Applying user feedback",
                            status=AgentStatus.RUNNING,
                        ),
                    )

            if not files_written:
                files_written = self._detect_workspace_changes(before_snapshot)

            return self._new_result(
                success=True,
                output="\n".join(part for part in output_parts if part.strip()),
                files_written=files_written,
                usage=usage,
                workspace_path=str(self.cwd),
                final_status=AgentStatus.COMPLETED,
                started_at=started_at,
            )
        except Exception as exc:
            await self._emit(
                event_handler,
                AgentEvent(
                    event_type=AgentEventType.AGENT_FAILED,
                    agent_name=self.name,
                    role=self.role,
                    message=str(exc),
                    status=AgentStatus.FAILED,
                ),
            )
            return self._new_result(
                success=False,
                error=str(exc),
                usage=usage,
                workspace_path=str(self.cwd),
                final_status=AgentStatus.FAILED,
                started_at=started_at,
            )

    def _app_server_config(self) -> AppServerConfig:
        settings = get_settings()
        return AppServerConfig(
            codex_bin=str(settings.codex_bin) if settings.codex_bin else None,
            cwd=str(self.cwd.resolve()),
        )

    async def _collect_turn_result(
        self,
        stream: Any,
        turn_id: str,
        *,
        event_handler: EventHandler | None,
    ) -> tuple[str, list[str], ThreadTokenUsage | None]:
        files_written: list[str] = []
        usage: ThreadTokenUsage | None = None
        message_parts: list[str] = []
        seen_agent_messages: set[str] = set()

        async for event in stream:
            payload = event.payload

            if isinstance(payload, AgentMessageDeltaNotification) and payload.turn_id == turn_id:
                if payload.delta:
                    await self._emit(
                        event_handler,
                        AgentEvent(
                            event_type=AgentEventType.MESSAGE,
                            agent_name=self.name,
                            role=self.role,
                            message=payload.delta,
                            status=AgentStatus.RUNNING,
                        ),
                    )
                continue

            if isinstance(payload, CommandExecutionOutputDeltaNotification) and payload.turn_id == turn_id:
                if payload.delta:
                    await self._emit(
                        event_handler,
                        AgentEvent(
                            event_type=AgentEventType.MESSAGE,
                            agent_name=self.name,
                            role=self.role,
                            message=payload.delta,
                            status=AgentStatus.RUNNING,
                        ),
                    )
                continue

            if isinstance(payload, FileChangeOutputDeltaNotification) and payload.turn_id == turn_id:
                continue

            if isinstance(payload, ItemCompletedNotification) and payload.turn_id == turn_id:
                thread_item = getattr(payload.item, "root", payload.item)
                if isinstance(thread_item, AgentMessageThreadItem):
                    if thread_item.text and thread_item.id not in seen_agent_messages:
                        message_parts.append(thread_item.text)
                        seen_agent_messages.add(thread_item.id)
                elif isinstance(thread_item, CommandExecutionThreadItem):
                    command = thread_item.command or ""
                    await self._emit(
                        event_handler,
                        AgentEvent(
                            event_type=AgentEventType.TOOL_ACTIVITY,
                            agent_name=self.name,
                            role=self.role,
                            message=command,
                            status=AgentStatus.RUNNING,
                            details={"tool_name": "command", "command": command},
                        ),
                    )
                elif isinstance(thread_item, FileChangeThreadItem):
                    for change in thread_item.changes:
                        if change.path not in files_written:
                            files_written.append(change.path)
                            await self._emit(
                                event_handler,
                                AgentEvent(
                                    event_type=AgentEventType.FILE_CHANGED,
                                    agent_name=self.name,
                                    role=self.role,
                                    message=f"Updated {change.path}",
                                    path=change.path,
                                    status=AgentStatus.RUNNING,
                                ),
                            )
                continue

            if event.method == "thread/tokenUsageUpdated" and getattr(payload, "turn_id", None) == turn_id:
                usage = payload.token_usage
                continue

            if isinstance(payload, TurnCompletedNotification) and payload.turn.id == turn_id:
                await self._emit(
                    event_handler,
                    AgentEvent(
                        event_type=AgentEventType.TURN_COMPLETED,
                        agent_name=self.name,
                        role=self.role,
                        message="Turn completed",
                        status=AgentStatus.RUNNING,
                    ),
                )
                break

        final_output = "\n".join(part.strip() for part in message_parts if part.strip())
        return final_output, files_written, usage

    def _usage_from_thread(self, usage: ThreadTokenUsage) -> UsageMetrics:
        total = getattr(usage, "total", None)
        input_tokens = getattr(total, "input_tokens", 0) if total else 0
        output_tokens = getattr(total, "output_tokens", 0) if total else 0
        total_tokens = getattr(total, "total_tokens", input_tokens + output_tokens) if total else 0
        return UsageMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )


class BackendCodexAgent(CodexWorkspaceAgent):
    def __init__(self, working_dir: str | Path, model: str | None = None):
        super().__init__(
            working_dir=working_dir,
            agent_name="BackendCodexAgent",
            role=AgentRole.BACKEND,
            task_guidance=(
                "- Build the backend implementation in the assigned backend workspace.\n"
                "- Follow the architecture and preferred backend framework.\n"
                "- Produce runnable backend project files, not just notes."
            ),
            model=model,
        )


class QaCodexAgent(CodexWorkspaceAgent):
    def __init__(self, working_dir: str | Path, model: str | None = None):
        super().__init__(
            working_dir=working_dir,
            agent_name="QaCodexAgent",
            role=AgentRole.QA,
            task_guidance=(
                "- Create tests for both backend and frontend based on the architecture and implementation.\n"
                "- Prefer writing tests into backend and frontend test directories.\n"
                "- Write a short QA summary report in the QA metadata area."
            ),
            model=model,
        )
