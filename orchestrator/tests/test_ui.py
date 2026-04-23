from orchestrator.agents.base import AgentEvent, AgentEventType, AgentRole, AgentStatus
from orchestrator.ui import RichStatusRenderer


def test_status_renderer_tracks_messages_and_files():
    renderer = RichStatusRenderer()
    renderer.handle_event(
        AgentEvent(
            event_type=AgentEventType.AGENT_STARTED,
            agent_name="BackendCodexAgent",
            role=AgentRole.BACKEND,
            message="started",
            status=AgentStatus.RUNNING,
        )
    )
    renderer.handle_event(
        AgentEvent(
            event_type=AgentEventType.FILE_CHANGED,
            agent_name="BackendCodexAgent",
            role=AgentRole.BACKEND,
            message="Updated app.py",
            path="app.py",
            status=AgentStatus.RUNNING,
        )
    )

    panel = renderer.render()
    table = panel.renderable

    assert table.row_count == 1
