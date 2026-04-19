from __future__ import annotations

from pathlib import Path
from typing import Any

from codex_app_server import AsyncCodex, AppServerConfig
from codex_app_server._inputs import TextInput
from codex_app_server.generated.v2_all import (
    AgentMessageThreadItem,
    AskForApproval,
    AskForApprovalValue,
    CommandExecutionThreadItem,
    FileChangeThreadItem,
    Personality,
    ReasoningEffort,
    SandboxMode,
    ThreadTokenUsage,
    TurnCompletedNotification,
)
from codex_app_server.models import Notification
from codex_app_server.generated.v2_all import (
    AgentMessageDeltaNotification,
    CommandExecutionOutputDeltaNotification,
    FileChangeOutputDeltaNotification,
    ItemCompletedNotification,
)

from orchestrator.agents.base import AgentAdapter, AgentResult, AgentRole
from orchestrator.config import settings


class CodexDeveloperAgent(AgentAdapter):
    def __init__(self, working_dir: str | Path = "./output", model: str | None = None):
        self.cwd = Path(working_dir)
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.model = model

    @property
    def name(self) -> str:
        return "CodexDeveloperAgent"

    @property
    def role(self) -> AgentRole:
        return AgentRole.IMPLEMENTER

    def discover_context_files(self, context: dict[str, Any]) -> list[str]:
        discovered: list[str] = []
        configured_paths = context.get("artifact_paths", [])

        if isinstance(configured_paths, (str, Path)):
            configured_paths = [configured_paths]

        for raw_path in configured_paths:
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.cwd / path
            if path.exists():
                discovered.append(self._display_path(path))

        for candidate in sorted(self.cwd.glob("*")):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml"}:
                continue
            discovered.append(self._display_path(candidate))

        return list(dict.fromkeys(discovered))

    def build_prompt(self, task: str, context: dict[str, Any]) -> str:
        base_prompt = super().build_prompt(task, context)
        context_files = self.discover_context_files(context)

        file_instructions = ""
        if context_files:
            file_list = "\n".join(f"- {path}" for path in context_files)
            file_instructions = f"""
Context files to read from disk before implementing:
{file_list}

Implementation workflow:
- Read the context files first and use them as the source of truth for the implementation.
- Prefer creating or updating real project files in this workspace instead of describing code in prose.
- Keep the final response short and include a concise implementation summary.
"""
        else:
            file_instructions = """
Implementation workflow:
- Inspect the workspace first so you understand the current project state before editing files.
- Prefer creating or updating real project files in this workspace instead of describing code in prose.
- Keep the final response short and include a concise implementation summary.
"""

        return f"{base_prompt}\n{file_instructions}".strip()

    async def execute(self, prompt: str, context: dict[str, Any]) -> AgentResult:
        full_prompt = self.build_prompt(prompt, context)
        before_snapshot = self._snapshot_workspace()

        try:
            async with AsyncCodex(config=self._app_server_config()) as codex:
                thread = await codex.thread_start(
                    cwd=str(self.cwd.resolve()),
                    model=self.model or self._default_model(),
                    approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
                    personality=Personality.pragmatic,
                    sandbox=SandboxMode.workspace_write,
                )
                turn = await thread.turn(
                    TextInput(full_prompt),
                    effort=ReasoningEffort.medium,
                )
                output, items, usage = await self._collect_turn_result(turn.stream(), turn.id)

            tokens_used = usage.total.total_tokens if usage else 0
            files_written = self._extract_files_written(items)
            if not files_written:
                files_written = self._detect_workspace_changes(before_snapshot)

            return AgentResult(
                success=True,
                agent_name=self.name,
                role=self.role,
                output=output,
                files_written=files_written,
                tokens_used=tokens_used,
            )
        except Exception as exc:
            return AgentResult(
                success=False,
                agent_name=self.name,
                role=self.role,
                error=str(exc),
            )

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.cwd.resolve()))
        except ValueError:
            return str(path.resolve())

    def _default_model(self) -> str:
        return settings.codex_model

    def _app_server_config(self) -> AppServerConfig:
        return AppServerConfig(
            codex_bin=str(settings.codex_bin) if settings.codex_bin else None,
            cwd=str(self.cwd.resolve()),
        )

    async def _collect_turn_result(
        self,
        stream: Any,
        turn_id: str,
    ) -> tuple[str, list[Any], ThreadTokenUsage | None]:
        items: list[Any] = []
        usage: ThreadTokenUsage | None = None
        message_parts: list[str] = []
        seen_agent_messages: set[str] = set()
        active_agent_item_id: str | None = None

        async for event in stream:
            payload = event.payload

            if isinstance(payload, AgentMessageDeltaNotification) and payload.turn_id == turn_id:
                print(payload.delta, end="", flush=True)
                active_agent_item_id = payload.item_id
                continue

            if isinstance(payload, CommandExecutionOutputDeltaNotification) and payload.turn_id == turn_id:
                if payload.delta:
                    print(payload.delta, end="", flush=True)
                continue

            if isinstance(payload, FileChangeOutputDeltaNotification) and payload.turn_id == turn_id:
                continue

            if isinstance(payload, ItemCompletedNotification) and payload.turn_id == turn_id:
                items.append(payload.item)
                thread_item = getattr(payload.item, "root", payload.item)
                if isinstance(thread_item, AgentMessageThreadItem):
                    if thread_item.id != active_agent_item_id and thread_item.text:
                        if thread_item.id not in seen_agent_messages:
                            print(thread_item.text)
                    if thread_item.text and thread_item.id not in seen_agent_messages:
                        message_parts.append(thread_item.text)
                        seen_agent_messages.add(thread_item.id)
                elif isinstance(thread_item, CommandExecutionThreadItem):
                    if thread_item.command:
                        print(f"\n[Codex command] {thread_item.command}")
                continue

            if event.method == "thread/tokenUsageUpdated" and getattr(payload, "turn_id", None) == turn_id:
                usage = payload.token_usage
                continue

            if isinstance(payload, TurnCompletedNotification) and payload.turn.id == turn_id:
                print()
                break

        final_output = "\n".join(part.strip() for part in message_parts if part.strip())
        return final_output, items, usage

    def _snapshot_workspace(self) -> dict[str, int]:
        snapshot: dict[str, int] = {}
        for path in self.cwd.rglob("*"):
            if not path.is_file():
                continue
            snapshot[self._display_path(path)] = path.stat().st_mtime_ns
        return snapshot

    def _detect_workspace_changes(self, before_snapshot: dict[str, int]) -> list[str]:
        changed: list[str] = []
        after_snapshot = self._snapshot_workspace()

        for path, mtime in after_snapshot.items():
            if before_snapshot.get(path) != mtime:
                changed.append(path)

        return sorted(changed)

    def _extract_files_written(self, items: list[Any]) -> list[str]:
        files_written: list[str] = []

        for item in items:
            thread_item = getattr(item, "root", item)
            if not isinstance(thread_item, FileChangeThreadItem):
                continue

            for change in thread_item.changes:
                if change.path not in files_written:
                    files_written.append(change.path)

        return files_written
