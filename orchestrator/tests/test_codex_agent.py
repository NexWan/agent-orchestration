from codex_app_server.generated.v2_all import FileChangeThreadItem, ThreadItem

from orchestrator.agents.codex_agent import CodexDeveloperAgent


def test_discover_context_files_includes_architecture(tmp_path):
    (tmp_path / "ARCHITECTURE.md").write_text("# Plan", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("extra context", encoding="utf-8")

    agent = CodexDeveloperAgent(working_dir=tmp_path)

    files = agent.discover_context_files({"artifact_paths": ["ARCHITECTURE.md"]})

    assert files == ["ARCHITECTURE.md", "notes.txt"]


def test_build_prompt_tells_codex_to_read_context_files(tmp_path):
    (tmp_path / "ARCHITECTURE.md").write_text("# Plan", encoding="utf-8")
    agent = CodexDeveloperAgent(working_dir=tmp_path)

    prompt = agent.build_prompt(
        "Implement the project",
        {
            "project_description": "Test project",
            "current_phase": 2,
            "artifacts": {},
            "artifact_paths": ["ARCHITECTURE.md"],
        },
    )

    assert "Context files to read from disk before implementing" in prompt
    assert "- ARCHITECTURE.md" in prompt
    assert "Read the context files first" in prompt


def test_extract_files_written_from_file_change_items(tmp_path):
    agent = CodexDeveloperAgent(working_dir=tmp_path)
    item = ThreadItem.model_validate(
        {
            "id": "item_123",
            "type": "fileChange",
            "status": "completed",
            "changes": [
                {
                    "path": "app.py",
                    "diff": "*** Add File: app.py\n+print('hello')\n",
                    "kind": {"type": "add"},
                },
                {
                    "path": "templates/index.html",
                    "diff": "*** Add File: templates/index.html\n+<h1>Hello</h1>\n",
                    "kind": {"type": "add"},
                },
            ],
        }
    )

    files = agent._extract_files_written([item, FileChangeThreadItem.model_validate(item.root.model_dump())])

    assert files == ["app.py", "templates/index.html"]
