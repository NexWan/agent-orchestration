from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ProjectLayout(Enum):
    MONOREPO = "monorepo"
    MULTIREPO = "multirepo"


@dataclass(slots=True)
class FrameworkPreferences:
    backend: str
    frontend: str


@dataclass(slots=True)
class ProjectSpec:
    project_description: str
    target_path: Path
    layout: ProjectLayout
    frameworks: FrameworkPreferences
    product_answers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class WorkspacePlan:
    root: Path
    metadata_dir: Path
    specs_dir: Path
    backend_dir: Path
    frontend_dir: Path
    qa_dir: Path
    validation_dir: Path

    @property
    def architect_dir(self) -> Path:
        return self.specs_dir

    @property
    def qa_scope_dir(self) -> Path:
        return self.root

    @property
    def docker_scope_dir(self) -> Path:
        return self.root

    @property
    def validator_scope_dir(self) -> Path:
        return self.root

    def ensure_directories(self) -> None:
        for path in [
            self.root,
            self.metadata_dir,
            self.specs_dir,
            self.backend_dir,
            self.frontend_dir,
            self.qa_dir,
            self.validation_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def build_workspace_plan(spec: ProjectSpec) -> WorkspacePlan:
    root = spec.target_path.expanduser().resolve()
    metadata_dir = root / ".orchestrator"
    specs_dir = metadata_dir / "specs"
    qa_dir = metadata_dir / "qa"
    validation_dir = metadata_dir / "validation"

    if spec.layout is ProjectLayout.MONOREPO:
        backend_dir = root / "backend"
        frontend_dir = root / "frontend"
    else:
        backend_dir = root / "backend"
        frontend_dir = root / "frontend"

    return WorkspacePlan(
        root=root,
        metadata_dir=metadata_dir,
        specs_dir=specs_dir,
        backend_dir=backend_dir,
        frontend_dir=frontend_dir,
        qa_dir=qa_dir,
        validation_dir=validation_dir,
    )


def render_project_brief(spec: ProjectSpec, workspace_plan: WorkspacePlan) -> str:
    question_lines = "\n".join(
        f"- {question}: {answer}" for question, answer in spec.product_answers.items()
    )
    if not question_lines:
        question_lines = "- No additional answers were provided."

    return (
        f"# Product Brief\n\n"
        f"## Project Description\n{spec.project_description}\n\n"
        f"## Layout\n{spec.layout.value}\n\n"
        f"## Preferred Frameworks\n"
        f"- Backend: {spec.frameworks.backend}\n"
        f"- Frontend: {spec.frameworks.frontend}\n\n"
        f"## Product Answers\n{question_lines}\n\n"
        f"## Workspace Paths\n"
        f"- Root: {workspace_plan.root}\n"
        f"- Specs: {workspace_plan.specs_dir}\n"
        f"- Backend: {workspace_plan.backend_dir}\n"
        f"- Frontend: {workspace_plan.frontend_dir}\n"
        f"- QA metadata: {workspace_plan.qa_dir}\n"
        f"- Validation metadata: {workspace_plan.validation_dir}\n"
    )
