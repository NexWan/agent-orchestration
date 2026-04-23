from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from typing import cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
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


class ClaudeWorkspaceAgent(AgentAdapter):
    def __init__(
        self,
        *,
        working_dir: str | Path,
        agent_name: str,
        role: AgentRole,
        allowed_tools: list[str],
        task_guidance: str,
    ):
        super().__init__(working_dir=working_dir)
        self._name = agent_name
        self._role = role
        self.allowed_tools = allowed_tools
        self.task_guidance = task_guidance

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> AgentRole:
        return self._role

    def build_prompt(self, task: str, context: dict[str, Any]) -> str:
        base_prompt = super().build_prompt(task, context)
        return (
            f"{base_prompt}\n"
            f"Role-specific guidance:\n{self.task_guidance}\n"
        )

    async def execute(
        self,
        prompt: str,
        context: dict[str, Any],
        event_handler: EventHandler | None = None,
        feedback_provider: FeedbackProvider | None = None,
    ) -> AgentResult:
        started_at = time.perf_counter()
        before_snapshot = self._snapshot_workspace()
        output_parts: list[str] = []
        files_written: list[str] = []
        usage = UsageMetrics()
        full_prompt = self.build_prompt(prompt, context)
        settings = get_settings()

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

        options = ClaudeAgentOptions(
            allowed_tools=self.allowed_tools,
            permission_mode=cast(Any, settings.claude_permission_mode),
            cwd=self.cwd,
        )

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(full_prompt)

                while True:
                    usage = usage.merge(
                        await self._drain_response(
                            client=client,
                            event_handler=event_handler,
                            output_parts=output_parts,
                            files_written=files_written,
                        )
                    )

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
                    await client.query(feedback)

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

    async def _drain_response(
        self,
        *,
        client: ClaudeSDKClient,
        event_handler: EventHandler | None,
        output_parts: list[str],
        files_written: list[str],
    ) -> UsageMetrics:
        usage = UsageMetrics()
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text = block.text.strip()
                        if text:
                            output_parts.append(text)
                            await self._emit(
                                event_handler,
                                AgentEvent(
                                    event_type=AgentEventType.MESSAGE,
                                    agent_name=self.name,
                                    role=self.role,
                                    message=text,
                                    status=AgentStatus.RUNNING,
                                ),
                            )
                    elif isinstance(block, ToolUseBlock):
                        tool_name = block.name
                        tool_input = getattr(block, "input", {}) or {}
                        path = tool_input.get("file_path")
                        if tool_name in {"Write", "Edit"} and path and path not in files_written:
                            files_written.append(path)
                            await self._emit(
                                event_handler,
                                AgentEvent(
                                    event_type=AgentEventType.FILE_CHANGED,
                                    agent_name=self.name,
                                    role=self.role,
                                    message=f"{tool_name} {path}",
                                    path=path,
                                    status=AgentStatus.RUNNING,
                                ),
                            )

                        await self._emit(
                            event_handler,
                            AgentEvent(
                                event_type=AgentEventType.TOOL_ACTIVITY,
                                agent_name=self.name,
                                role=self.role,
                                message=tool_name,
                                status=AgentStatus.RUNNING,
                                details={"tool_name": tool_name, "input": tool_input},
                            ),
                        )

            elif isinstance(message, ResultMessage):
                usage = usage.merge(UsageMetrics(cost_usd=float(message.total_cost_usd or 0.0)))
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
                return usage

        return usage


class ArchitectClaudeAgent(ClaudeWorkspaceAgent):
    def __init__(self, working_dir: str | Path):
        super().__init__(
            working_dir=working_dir,
            agent_name="ArchitectClaudeAgent",
            role=AgentRole.ARCHITECT,
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            task_guidance=(
                "- Your primary output is ARCHITECTURE.md inside the specs directory.\n"
                "- Do not implement source code.\n"
                "- Capture system structure, backend/frontend responsibilities, and testing strategy."
            ),
        )


class FrontendClaudeAgent(ClaudeWorkspaceAgent):
    def __init__(self, working_dir: str | Path):
        super().__init__(
            working_dir=working_dir,
            agent_name="FrontendClaudeAgent",
            role=AgentRole.FRONTEND,
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
            task_guidance=(
                "- Build the frontend inside the assigned frontend workspace.\n"
                "- Follow the architecture and integrate with the backend contract.\n"
                "- Prefer production-ready files over prose descriptions."
            ),
        )
