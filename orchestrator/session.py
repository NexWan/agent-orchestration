from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from orchestrator.agents.base import AgentAdapter, AgentResult, FeedbackRequest
from orchestrator.agents.claude_agent import ArchitectClaudeAgent, FrontendClaudeAgent
from orchestrator.agents.codex_agent import BackendCodexAgent, QaCodexAgent
from orchestrator.artifacts import ArtifactStore, ArtifactType
from orchestrator.project import ProjectSpec, WorkspacePlan, build_workspace_plan, render_project_brief


FeedbackProvider = Callable[[FeedbackRequest], Awaitable[str | None] | str | None]


@dataclass(slots=True)
class OrchestrationResults:
    workspace_plan: WorkspacePlan
    artifact_store: ArtifactStore
    results: list[AgentResult]


class OrchestrationSession:
    def __init__(self, spec: ProjectSpec):
        self.spec = spec
        self.workspace_plan = build_workspace_plan(spec)
        self.workspace_plan.ensure_directories()
        self.artifact_store = ArtifactStore(self.workspace_plan.metadata_dir)

    async def run(
        self,
        *,
        event_handler=None,
        feedback_provider: FeedbackProvider | None = None,
        agents: dict[str, AgentAdapter] | None = None,
    ) -> OrchestrationResults:
        self._write_product_brief()
        results: list[AgentResult] = []
        stage_agents = agents or self._build_default_agents()

        architect_result = await self._run_stage(
            agent=stage_agents["architect"],
            prompt=(
                "Create ARCHITECTURE.md as the source of truth for the project. "
                "Cover system structure, backend/frontend responsibilities, data flow, "
                "testing strategy, and how the selected frameworks should be used."
            ),
            artifact_types=[ArtifactType.PRODUCT_BRIEF],
            event_handler=event_handler,
            feedback_provider=feedback_provider,
        )
        results.append(architect_result)
        self._register_stage_outputs("architect", ArtifactType.ARCHITECTURE, self.workspace_plan.specs_dir)

        backend_result = await self._run_stage(
            agent=stage_agents["backend"],
            prompt=(
                "Implement the backend using the architecture and project brief. "
                "Write all backend files inside the backend workspace."
            ),
            artifact_types=[ArtifactType.PRODUCT_BRIEF, ArtifactType.ARCHITECTURE],
            event_handler=event_handler,
            feedback_provider=feedback_provider,
        )
        results.append(backend_result)
        self._register_stage_outputs("backend", ArtifactType.BACKEND_SOURCE, self.workspace_plan.backend_dir)

        frontend_result = await self._run_stage(
            agent=stage_agents["frontend"],
            prompt=(
                "Implement the frontend using the architecture, project brief, and backend outputs. "
                "Write all frontend files inside the frontend workspace."
            ),
            artifact_types=[
                ArtifactType.PRODUCT_BRIEF,
                ArtifactType.ARCHITECTURE,
                ArtifactType.BACKEND_SOURCE,
            ],
            event_handler=event_handler,
            feedback_provider=feedback_provider,
        )
        results.append(frontend_result)
        self._register_stage_outputs("frontend", ArtifactType.FRONTEND_SOURCE, self.workspace_plan.frontend_dir)

        qa_result = await self._run_stage(
            agent=stage_agents["qa"],
            prompt=(
                "Create tests for the backend and frontend implementations. "
                "Write tests into the relevant backend/frontend test folders and a QA summary report "
                "under the QA metadata directory."
            ),
            artifact_types=[
                ArtifactType.PRODUCT_BRIEF,
                ArtifactType.ARCHITECTURE,
                ArtifactType.BACKEND_SOURCE,
                ArtifactType.FRONTEND_SOURCE,
            ],
            event_handler=event_handler,
            feedback_provider=feedback_provider,
        )
        results.append(qa_result)
        self._register_stage_outputs("qa", ArtifactType.TEST_SUITE, self.workspace_plan.root)
        self._register_qa_report()

        return OrchestrationResults(
            workspace_plan=self.workspace_plan,
            artifact_store=self.artifact_store,
            results=results,
        )

    def _build_default_agents(self) -> dict[str, AgentAdapter]:
        return {
            "architect": ArchitectClaudeAgent(self.workspace_plan.architect_dir),
            "backend": BackendCodexAgent(self.workspace_plan.backend_dir),
            "frontend": FrontendClaudeAgent(self.workspace_plan.frontend_dir),
            "qa": QaCodexAgent(self.workspace_plan.qa_scope_dir),
        }

    async def _run_stage(
        self,
        *,
        agent: AgentAdapter,
        prompt: str,
        artifact_types: list[ArtifactType],
        event_handler,
        feedback_provider: FeedbackProvider | None,
    ) -> AgentResult:
        context = {
            "project_description": self.spec.project_description,
            "workspace_plan": self.workspace_plan,
            "artifacts": self.artifact_store.export_for_prompt(artifact_types),
            "stage_name": agent.role.value,
        }
        return await agent.execute(
            prompt,
            context,
            event_handler=event_handler,
            feedback_provider=feedback_provider,
        )

    def _write_product_brief(self) -> Path:
        product_brief_path = self.workspace_plan.specs_dir / "PRODUCT_BRIEF.md"
        product_brief_path.write_text(
            render_project_brief(self.spec, self.workspace_plan),
            encoding="utf-8",
        )
        self.artifact_store.register_file(
            ArtifactType.PRODUCT_BRIEF,
            "orchestrator",
            product_brief_path,
        )
        return product_brief_path

    def _register_stage_outputs(
        self,
        producer: str,
        artifact_type: ArtifactType,
        root: Path,
    ) -> None:
        self.artifact_store.register_tree(artifact_type, producer, root)

    def _register_qa_report(self) -> None:
        for candidate in [
            self.workspace_plan.qa_dir / "QA_REPORT.md",
            self.workspace_plan.root / "QA_REPORT.md",
        ]:
            if candidate.exists():
                self.artifact_store.register_file(ArtifactType.QA_REPORT, "qa", candidate)
