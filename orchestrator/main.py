import asyncio
from pathlib import Path

from orchestrator.agents.claude_agent import ClaudeArchitectAgent
from orchestrator.agents.codex_agent import CodexDeveloperAgent

async def main():
    working_dir = Path("./output")
    architect = ClaudeArchitectAgent(working_dir=working_dir)
    developer = CodexDeveloperAgent(working_dir=working_dir)

    context = {
        "project_description": "Build a simple web visualizer of how Xpath works, using Python and Flask.",
        "current_phase": 1,
        "artifacts": {},
    }

    prompt = (
        "Design the architecture for the project, including a list of components and their "
        "interactions. Provide a high-level overview of how you would implement this. Focus on "
        "the overall structure and key components, rather than detailed implementation steps. "
        "Use markdown formatting for clarity."
    )

    print("Executing Architect Agent (interactive plan mode)...")
    print("The agent will propose an architecture. You can refine it before files are written.\n")

    # plan_mode=True  →  agent proposes first (read-only), you approve, then it writes
    # plan_mode=False →  agent runs freely; you can still give feedback each turn
    architect_result = await architect.execute_interactive(prompt, context, plan_mode=False)

    print("\n" + "=" * 60)
    print("Architect Result:")
    print(f"  Success:       {architect_result.success}")
    print(f"  Agent:         {architect_result.agent_name}")
    print(f"  Role:          {architect_result.role.value}")
    print(f"  Files written: {architect_result.files_written}")
    print(f"  Cost (USD):    {architect_result.tokens_used}")
    if architect_result.error:
        print(f"  Error:         {architect_result.error}")
        return

    architecture_path = working_dir / "ARCHITECTURE.md"
    architecture_text = architecture_path.read_text(encoding="utf-8") if architecture_path.exists() else ""
    developer_context = {
        **context,
        "current_phase": 2,
        "artifacts": {
            **context["artifacts"],
            "ARCHITECTURE.md": architecture_text,
        },
        "artifact_paths": [architecture_path.name],
    }
    developer_prompt = (
        "Implement the project described in ARCHITECTURE.md. Read the architecture file first, "
        "then create the application files needed for a first working version."
    )

    print("\nExecuting Developer Agent with Codex...")
    developer_result = await developer.execute(developer_prompt, developer_context)

    print("\n" + "=" * 60)
    print("Developer Result:")
    print(f"  Success:       {developer_result.success}")
    print(f"  Agent:         {developer_result.agent_name}")
    print(f"  Role:          {developer_result.role.value}")
    print(f"  Files written: {developer_result.files_written}")
    print(f"  Tokens used:   {developer_result.tokens_used}")
    if developer_result.error:
        print(f"  Error:         {developer_result.error}")


def app() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    app()
