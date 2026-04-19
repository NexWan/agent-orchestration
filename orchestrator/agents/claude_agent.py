# orchestrator/agents/claude_agent.py
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from orchestrator.agents.base import AgentAdapter, AgentResult, AgentRole

_ARCHITECT_TOOLS = ["Read", "Write", "Glob", "Grep"]


class ClaudeArchitectAgent(AgentAdapter):

    def __init__(self, working_dir: str | Path = "./output"):
        self.cwd = Path(working_dir)
        self.cwd.mkdir(parents=True, exist_ok=True)
        self._files_written: list[str] = []

    @property
    def name(self) -> str:
        return "ClaudeArchitectAgent"

    @property
    def role(self) -> AgentRole:
        return AgentRole.ARCHITECT

    def build_prompt(self, task: str, context: dict[str, Any]) -> str:
        project = context.get("project_description", "")
        artifacts = context.get("artifacts", {})
        phase = context.get("current_phase", 0)

        artifact_summary = ""
        if artifacts:
            artifact_summary = "\n\nArtifacts from previous phases:\n"
            for name, content in artifacts.items():
                preview = str(content)[:300] + "..." if len(str(content)) > 300 else str(content)
                artifact_summary += f"- {name}: {preview}\n"

        return f"""Project: {project}
Current Phase: {phase}
Your Role: architect
{artifact_summary}
Your task: {task}

IMPORTANT:
- Your MAIN output is a single markdown file: ARCHITECTURE.md
- This file will serve as the blueprint for the implementer agent, so it must be clear and detailed about the components, their interactions, and the overall structure of the project.
- Do NOT create any source code, configuration, or other files — those are handled by a separate implementer agent that will read your plan.
- Write ARCHITECTURE.md to the workspace. Do not return its contents in chat.
- Be concise. No lengthy explanations outside the file.
"""

    async def execute(self, prompt: str, context: dict[str, Any]) -> AgentResult:
        full_prompt = self.build_prompt(prompt, context)
        self._files_written = [] # reset for this execution
        output_parts = []
        tokens_used = 0

        try:
            async for message in query(
                prompt=full_prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=_ARCHITECT_TOOLS,
                    permission_mode="acceptEdits",
                    cwd=self.cwd,
                ),
            ):
                # Texto y tool calls del agente
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"  [{self.name}] {block.text}")
                            output_parts.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            await self._handle_tool_use(block)

                # Resultado final con métricas
                elif isinstance(message, ResultMessage):
                    tokens_used = getattr(message, "total_cost_usd", 0)

            return AgentResult(
                success=True,
                agent_name=self.name,
                role=self.role,
                output="\n".join(output_parts),
                files_written=self._files_written,
                tokens_used=tokens_used,
            )

        except Exception as e:
            return AgentResult(
                success=False,
                agent_name=self.name,
                role=self.role,
                error=str(e),
            )

    async def execute_interactive(
        self,
        prompt: str,
        context: dict[str, Any],
        plan_mode: bool = False,
    ) -> AgentResult:
        """
        Interactive back-and-forth loop, like Claude Code's plan mode.

        Uses ClaudeSDKClient to keep a single persistent session across all
        turns. Each turn the agent runs, then pauses for user input.

        If plan_mode=True the session starts in 'plan' permission mode so the
        agent can only read files and propose changes. After the user presses
        Enter to approve, the mode switches to 'acceptEdits' and the agent
        executes its plan within the same conversation.
        """
        self._files_written = []
        output_parts: list[str] = []
        tokens_used = 0
        in_plan_phase = plan_mode

        initial_prompt = self.build_prompt(prompt, context)
        if plan_mode:
            initial_prompt += (
                "\n\nIMPORTANT: This is the PLANNING phase. "
                "Do NOT write any files yet. Describe the architecture you would "
                "implement and list every file you plan to create. "
                "Wait for approval before writing anything."
            )

        options = ClaudeAgentOptions(
            allowed_tools=_ARCHITECT_TOOLS,
            permission_mode="plan" if plan_mode else "acceptEdits",
            cwd=self.cwd,
        )

        try:
            async with ClaudeSDKClient(options=options) as client:
                # Kick off the first turn
                await client.query(initial_prompt)

                while True:
                    # Drain messages until the agent finishes this turn
                    async for message in client.receive_response():
                        if isinstance(message, AssistantMessage):
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    print(f"  [{self.name}] {block.text}")
                                    output_parts.append(block.text)
                                elif isinstance(block, ToolUseBlock):
                                    await self._handle_tool_use(block)
                        elif isinstance(message, ResultMessage):
                            tokens_used = getattr(message, "total_cost_usd", 0)

                    # Prompt the user
                    print("\n" + "─" * 60)
                    if in_plan_phase:
                        print("PLAN MODE  |  approve to execute, or type feedback to refine")
                    else:
                        print("Type feedback to refine, or press Enter to finish")
                    print("  [Enter]       approve / finish")
                    print("  [your text]   send feedback to the agent")
                    print("  quit          cancel")
                    print("─" * 60)

                    user_input = input("> ").strip()

                    if not user_input:
                        if in_plan_phase:
                            # Switch to execute mode and continue in the same session
                            await client.set_permission_mode("acceptEdits")
                            in_plan_phase = False
                            await client.query(
                                "The plan is approved. Now execute it: "
                                "write all the files you proposed."
                            )
                            continue
                        break  # User is satisfied — done

                    if user_input.lower() in ("quit", "exit", "cancel"):
                        return AgentResult(
                            success=False,
                            agent_name=self.name,
                            role=self.role,
                            error="Cancelled by user",
                        )

                    # Send feedback; agent replies in the same session
                    await client.query(user_input)

            return AgentResult(
                success=True,
                agent_name=self.name,
                role=self.role,
                output="\n".join(output_parts),
                files_written=self._files_written,
                tokens_used=tokens_used,
            )

        except Exception as e:
            return AgentResult(
                success=False,
                agent_name=self.name,
                role=self.role,
                error=str(e),
            )

    async def _handle_tool_use(self, block: ToolUseBlock) -> None:
        """Loggea y trackea cada tool call del agente."""
        tool_name = block.name
        tool_input = getattr(block, "input", {})

        match tool_name:
            case "Write" | "Edit":
                path = tool_input.get("file_path", "?")
                self._files_written.append(path)
                print(f"  📝 {tool_name}: {path}")
            case "Bash":
                cmd = tool_input.get("command", "?")
                print(f"  ⚡ Bash: {cmd[:80]}")
            case "Read" | "Glob" | "Grep":
                target = tool_input.get("file_path") or tool_input.get("pattern", "?")
                print(f"  🔍 {tool_name}: {target}")
            case _:
                print(f"  🔧 {tool_name}")