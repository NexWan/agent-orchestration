import asyncio
from orchestrator.agents.claude_agent import ClaudeArchitectAgent

async def main():
    agent = ClaudeArchitectAgent(working_dir="./test_output")

    context = {
        "project_description": "Build a simple web visualizer of how Xpath works, using Python and Flask.",
        "current_phase": 1,
        "artifacts": {},
    }

    prompt = "Design the architecture for the project, including a list of components and their interactions. Provide a high-level overview of how you would implement this. Focus on the overall structure and key components, rather than detailed implementation steps. Use markdown formatting for clarity."

    print("Executing Architect Agent...")
    result = await agent.execute(prompt, context)

    print("\nAgent Result:")
    print(f"Success: {result.success}")
    print(f"Agent Name: {result.agent_name}")
    print(f"Role: {result.role.value}")
    print(f"Output:\n{result.output}")
    print(f"Files Written: {result.files_written}")
    print(f"Tokens Used: {result.tokens_used}")
    if result.error:
        print(f"Error: {result.error}")
    else:
        print(f"\nOutput:\n{result.output}")


asyncio.run(main())