from __future__ import annotations

from dataclasses import dataclass, field

from rich.panel import Panel
from rich.table import Table

from orchestrator.agents.base import AgentEvent, AgentEventType, AgentStatus


@dataclass(slots=True)
class AgentViewState:
    status: str = AgentStatus.PENDING.value
    latest_message: str = ""
    latest_task: str = ""
    files_touched: list[str] = field(default_factory=list)
    approvals_pending: int = 0


class RichStatusRenderer:
    def __init__(self) -> None:
        self._states: dict[str, AgentViewState] = {}

    def handle_event(self, event: AgentEvent) -> None:
        state = self._states.setdefault(event.agent_name, AgentViewState())
        if event.status is not None:
            state.status = event.status.value
        if event.message:
            state.latest_message = event.message.strip()
        if event.event_type is AgentEventType.TOOL_ACTIVITY:
            state.latest_task = event.details.get("tool_name", event.message)
        elif event.event_type is AgentEventType.STATUS_CHANGED and event.message:
            state.latest_task = event.message
        elif event.event_type is AgentEventType.TURN_COMPLETED:
            state.latest_task = "turn completed"
        elif event.event_type is AgentEventType.AGENT_STARTED:
            state.latest_task = "started"

        if event.event_type is AgentEventType.FILE_CHANGED and event.path:
            if event.path not in state.files_touched:
                state.files_touched.append(event.path)

        if event.event_type is AgentEventType.APPROVAL_REQUESTED:
            state.approvals_pending += 1

    def render(self) -> Panel:
        table = Table(title="Sub-Agent Progress")
        table.add_column("Agent")
        table.add_column("Status")
        table.add_column("Current Task")
        table.add_column("Latest Output")
        table.add_column("Files Touched")
        table.add_column("Approvals")

        for agent_name, state in self._states.items():
            files = ", ".join(state.files_touched[-3:]) if state.files_touched else "-"
            message = state.latest_message or "-"
            task = state.latest_task or "-"
            table.add_row(
                agent_name,
                state.status,
                task,
                message[:120],
                files,
                str(state.approvals_pending),
            )

        if not self._states:
            table.add_row("-", AgentStatus.PENDING.value, "-", "-", "-", "0")

        return Panel(table, border_style="cyan")
