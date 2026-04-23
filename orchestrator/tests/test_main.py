from pathlib import Path

from orchestrator.main import collect_project_spec
from orchestrator.project import ProjectLayout


def test_collect_project_spec_uses_answers(monkeypatch, tmp_path):
    answers = iter(
        [
            "Build a dashboard",
            str(tmp_path / "product"),
            "Vue",
            "FastAPI",
            "Product managers",
            "Dashboards, exports",
            "Accessibility and tests",
        ]
    )

    monkeypatch.setattr("orchestrator.main.Prompt.ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr("orchestrator.main.Confirm.ask", lambda *args, **kwargs: False)

    spec = collect_project_spec(default_root=Path(tmp_path))

    assert spec.project_description == "Build a dashboard"
    assert spec.target_path == tmp_path / "product"
    assert spec.layout is ProjectLayout.MULTIREPO
    assert spec.frameworks.frontend == "Vue"
    assert spec.frameworks.backend == "FastAPI"
