from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

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


@dataclass(slots=True)
class OrchestratorViewSnapshot:
    current_agent: str = ""
    mode: str = "idle"
    agents: dict[str, AgentViewState] = field(default_factory=dict)


class SessionStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, snapshot: OrchestratorViewSnapshot) -> None:
        payload = {
            "current_agent": snapshot.current_agent,
            "mode": snapshot.mode,
            "agents": {
                name: asdict(state)
                for name, state in snapshot.agents.items()
            },
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def read(self) -> OrchestratorViewSnapshot:
        if not self.path.exists():
            return OrchestratorViewSnapshot()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        agents = {
            name: AgentViewState(**state)
            for name, state in payload.get("agents", {}).items()
        }
        return OrchestratorViewSnapshot(
            current_agent=payload.get("current_agent", ""),
            mode=payload.get("mode", "idle"),
            agents=agents,
        )


class RichStatusRenderer:
    def __init__(self) -> None:
        self._snapshot = OrchestratorViewSnapshot()

    def handle_event(self, event: AgentEvent) -> None:
        state = self._snapshot.agents.setdefault(event.agent_name, AgentViewState())
        self._snapshot.current_agent = event.agent_name
        self._snapshot.mode = "running"
        if event.status is not None:
            state.status = event.status.value
        if event.message:
            state.latest_message = event.message.strip()
        if event.event_type is AgentEventType.TOOL_ACTIVITY:
            command = event.details.get("command", "")
            tool_name = event.details.get("tool_name", event.message)
            state.latest_task = command or str(tool_name)
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
        elif state.approvals_pending and event.event_type is AgentEventType.STATUS_CHANGED:
            state.approvals_pending = max(state.approvals_pending - 1, 0)

    def snapshot(self) -> OrchestratorViewSnapshot:
        return self._snapshot

    def load_snapshot(self, snapshot: OrchestratorViewSnapshot) -> None:
        self._snapshot = snapshot

    def render(self) -> Panel:
        table = Table(title="Sub-Agent Progress")
        table.add_column("Agent")
        table.add_column("Status")
        table.add_column("Current Task")
        table.add_column("Latest Output")
        table.add_column("Files Touched")
        table.add_column("Approvals")

        for agent_name, state in self._snapshot.agents.items():
            files = ", ".join(state.files_touched[-3:]) if state.files_touched else "-"
            message = state.latest_message or "-"
            task = state.latest_task or "-"
            table.add_row(
                agent_name,
                state.status,
                task[:120],
                message[:120],
                files,
                str(state.approvals_pending),
            )

        if not self._snapshot.agents:
            table.add_row("-", AgentStatus.PENDING.value, "-", "-", "-", "0")

        title = "Sub-Agent Progress"
        if self._snapshot.current_agent:
            title = f"Current Agent: {self._snapshot.current_agent}"

        return Panel(table, border_style="cyan", title=title, subtitle=f"Mode: {self._snapshot.mode}")
