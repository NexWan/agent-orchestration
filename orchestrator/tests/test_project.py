from pathlib import Path

from orchestrator.project import (
    FrameworkPreferences,
    ProjectLayout,
    ProjectSpec,
    build_workspace_plan,
    render_project_brief,
)


def make_spec(tmp_path: Path, layout: ProjectLayout) -> ProjectSpec:
    return ProjectSpec(
        project_description="Build a project",
        target_path=tmp_path / "demo",
        layout=layout,
        frameworks=FrameworkPreferences(backend="FastAPI", frontend="React"),
        product_answers={"target users": "Developers"},
    )


def test_build_workspace_plan_for_monorepo(tmp_path):
    plan = build_workspace_plan(make_spec(tmp_path, ProjectLayout.MONOREPO))

    assert plan.root == (tmp_path / "demo").resolve()
    assert plan.backend_dir == plan.root / "backend"
    assert plan.frontend_dir == plan.root / "frontend"
    assert plan.specs_dir == plan.root / ".orchestrator" / "specs"


def test_build_workspace_plan_for_multirepo(tmp_path):
    plan = build_workspace_plan(make_spec(tmp_path, ProjectLayout.MULTIREPO))

    assert plan.root == (tmp_path / "demo").resolve()
    assert plan.backend_dir == plan.root / "backend"
    assert plan.frontend_dir == plan.root / "frontend"


def test_render_project_brief_includes_frameworks(tmp_path):
    spec = make_spec(tmp_path, ProjectLayout.MONOREPO)
    plan = build_workspace_plan(spec)

    brief = render_project_brief(spec, plan)

    assert "Backend: FastAPI" in brief
    assert "Frontend: React" in brief
    assert "target users: Developers" in brief
