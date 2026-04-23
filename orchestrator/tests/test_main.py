import json
from pathlib import Path

from orchestrator.main import choose_cli_mode, collect_project_spec, monitor_async
from orchestrator.project import ProjectLayout


def test_choose_cli_mode_uses_prompt(monkeypatch):
    monkeypatch.setattr("orchestrator.main.Prompt.ask", lambda *args, **kwargs: "monitor")

    assert choose_cli_mode() == "monitor"


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


async def test_monitor_async_reads_existing_state(tmp_path):
    state_dir = tmp_path / "product" / ".orchestrator"
    state_dir.mkdir(parents=True)
    (state_dir / "session_state.json").write_text(
        json.dumps(
            {
                "current_agent": "RuntimeValidationClaudeAgent",
                "mode": "running",
                "agents": {
                    "RuntimeValidationClaudeAgent": {
                        "status": "running",
                        "latest_message": "Trying npm install",
                        "latest_task": "npm install",
                        "files_touched": [],
                        "approvals_pending": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    await monitor_async(tmp_path / "product", iterations=1)
