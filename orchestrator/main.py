import asyncio
from orchestrator.agents.claude_agent import ClaudeArchitectAgent

async def main():
    agent = ClaudeArchitectAgent(working_dir="./test_output")

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
    result = await agent.execute_interactive(prompt, context, plan_mode=True)

    print("\n" + "=" * 60)
    print("Agent Result:")
    print(f"  Success:       {result.success}")
    print(f"  Agent:         {result.agent_name}")
    print(f"  Role:          {result.role.value}")
    print(f"  Files written: {result.files_written}")
    print(f"  Cost (USD):    {result.tokens_used}")
    if result.error:
        print(f"  Error:         {result.error}")


asyncio.run(main())
