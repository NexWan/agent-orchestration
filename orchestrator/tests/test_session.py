from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.agents.base import (
    AgentAdapter,
    AgentEvent,
    AgentEventType,
    AgentRole,
    AgentStatus,
)
from orchestrator.project import FrameworkPreferences, ProjectLayout, ProjectSpec
from orchestrator.session import OrchestrationSession


class FakeAgent(AgentAdapter):
    def __init__(self, working_dir: Path, name: str, role: AgentRole, marker_file: str, calls: list[tuple[str, list[str]]]):
        super().__init__(working_dir)
        self._name = name
        self._role = role
        self.marker_file = marker_file
        self.calls = calls

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> AgentRole:
        return self._role

    async def execute(
        self,
        prompt: str,
        context: dict[str, Any],
        event_handler=None,
        feedback_provider=None,
    ):
        artifact_types = [artifact["artifact_type"] for artifact in context["artifacts"]]
        self.calls.append((self.name, artifact_types))
        target = self.cwd / self.marker_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.name, encoding="utf-8")
        if event_handler is not None:
            await event_handler(
                AgentEvent(
                    event_type=AgentEventType.TURN_COMPLETED,
                    agent_name=self.name,
                    role=self.role,
                    message="done",
                    status=AgentStatus.COMPLETED,
                )
            )
        return self._new_result(
            success=True,
            files_written=[self.marker_file],
            workspace_path=str(self.cwd),
            final_status=AgentStatus.COMPLETED,
            started_at=0.0,
        )


async def test_orchestration_session_respects_stage_dependencies(tmp_path):
    spec = ProjectSpec(
        project_description="Build a platform",
        target_path=tmp_path / "product",
        layout=ProjectLayout.MONOREPO,
        frameworks=FrameworkPreferences(backend="FastAPI", frontend="React"),
        product_answers={"target users": "Teams"},
    )
    session = OrchestrationSession(spec)
    calls: list[tuple[str, list[str]]] = []
    agents = {
        "architect": FakeAgent(session.workspace_plan.architect_dir, "architect", AgentRole.ARCHITECT, "ARCHITECTURE.md", calls),
        "backend": FakeAgent(session.workspace_plan.backend_dir, "backend", AgentRole.BACKEND, "app.py", calls),
        "frontend": FakeAgent(session.workspace_plan.frontend_dir, "frontend", AgentRole.FRONTEND, "index.html", calls),
        "qa": FakeAgent(session.workspace_plan.qa_scope_dir, "qa", AgentRole.QA, "QA_REPORT.md", calls),
        "docker": FakeAgent(session.workspace_plan.docker_scope_dir, "docker", AgentRole.DOCKER, "docker-compose.yml", calls),
        "validator": FakeAgent(session.workspace_plan.validator_scope_dir, "validator", AgentRole.VALIDATOR, "VALIDATION_REPORT.md", calls),
    }
    seen_events: list[str] = []

    async def handler(event: AgentEvent):
        seen_events.append(event.agent_name)

    results = await session.run(agents=agents, event_handler=handler, feedback_provider=lambda request: None)

    assert [name for name, _ in calls] == ["architect", "backend", "frontend", "qa", "docker", "validator"]
    assert calls[0][1] == ["product_brief"]
    assert "architecture" in calls[1][1]
    assert "backend_source" in calls[2][1]
    assert "frontend_source" in calls[3][1]
    assert "frontend_source" in calls[4][1]
    assert "docker_assets" in calls[5][1]
    assert len(results.results) == 6
    assert seen_events == ["architect", "backend", "frontend", "qa", "docker", "validator"]
