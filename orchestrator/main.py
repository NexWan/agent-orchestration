from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.live import Live
from rich.prompt import Confirm, Prompt
from rich.table import Table

from orchestrator.agents.base import AgentEvent, AgentResult, FeedbackRequest
from orchestrator.config import get_settings
from orchestrator.project import FrameworkPreferences, ProjectLayout, ProjectSpec
from orchestrator.session import OrchestrationSession
from orchestrator.ui import RichStatusRenderer, SessionStateStore

app = typer.Typer(help="Interactive multi-agent project orchestrator.")
console = Console()


def choose_cli_mode() -> str:
    return Prompt.ask(
        "What do you want to do?",
        choices=["start", "monitor", "exit"],
        default="start",
    )


def collect_project_spec(default_root: Path | None = None) -> ProjectSpec:
    settings = get_settings()
    base_root = default_root or settings.generated_projects_dir
    project_description = Prompt.ask("Describe the project you want to build")
    destination = Path(
        Prompt.ask(
            "Where should the generated project live?",
            default=str(base_root / "my-project"),
        )
    )
    is_monorepo = Confirm.ask("Should the generated project be a monorepo?", default=True)
    frontend_framework = Prompt.ask("Preferred frontend framework", default="React")
    backend_framework = Prompt.ask("Preferred backend framework", default="FastAPI")

    product_answers = {
        "target users": Prompt.ask("Who is the target user?", default="General users"),
        "core features": Prompt.ask(
            "What are the must-have features?",
            default="Core CRUD, authentication, and polished UX",
        ),
        "non-functional requirements": Prompt.ask(
            "Any non-functional requirements?",
            default="Responsive UI, maintainable code, and automated tests",
        ),
    }

    return ProjectSpec(
        project_description=project_description,
        target_path=destination,
        layout=ProjectLayout.MONOREPO if is_monorepo else ProjectLayout.MULTIREPO,
        frameworks=FrameworkPreferences(
            backend=backend_framework,
            frontend=frontend_framework,
        ),
        product_answers=product_answers,
    )


def collect_monitor_root(default_root: Path | None = None) -> Path:
    settings = get_settings()
    base_root = default_root or settings.generated_projects_dir
    return Path(
        Prompt.ask(
            "Which generated project do you want to monitor?",
            default=str(base_root / "my-project"),
        )
    )


def build_state_store(project_root: Path) -> SessionStateStore:
    return SessionStateStore(project_root / ".orchestrator" / "session_state.json")


def prompt_for_feedback(
    request: FeedbackRequest,
    *,
    live: Live | None = None,
    renderer: RichStatusRenderer | None = None,
    state_store: SessionStateStore | None = None,
) -> str | None:
    if renderer is not None and state_store is not None:
        snapshot = renderer.snapshot()
        snapshot.mode = "feedback_requested"
        snapshot.current_agent = request.agent_name
        state_store.write(snapshot)

    if live is not None and live.is_started:
        live.stop()

    console.print()
    console.print(f"[bold cyan]{request.agent_name}[/bold cyan] is ready for your feedback.")
    answer = Prompt.ask(
        "Type feedback for this agent, or press Enter to continue to the next turn/stage",
        default="",
    ).strip() or None

    if renderer is not None and state_store is not None:
        snapshot = renderer.snapshot()
        agent_state = snapshot.agents.get(request.agent_name)
        if agent_state is not None:
            agent_state.approvals_pending = max(agent_state.approvals_pending - 1, 0)
        snapshot.mode = "running"
        state_store.write(snapshot)

    if live is not None:
        live.start()

    return answer


def summarize_results(results: list[AgentResult]) -> Table:
    table = Table(title="Execution Summary")
    table.add_column("Agent")
    table.add_column("Success")
    table.add_column("Files Written")
    table.add_column("Duration (s)")
    table.add_column("Tokens")
    table.add_column("Cost (USD)")

    for result in results:
        table.add_row(
            result.agent_name,
            "yes" if result.success else "no",
            str(len(result.files_written)),
            f"{result.duration_seconds:.2f}",
            str(result.usage.total_tokens),
            f"{result.usage.cost_usd:.4f}",
        )

    return table


@app.command()
def run() -> None:
    asyncio.run(run_async())


async def run_async(mode: str | None = None) -> None:
    while True:
        try:
            chosen_mode = mode or choose_cli_mode()
        except (KeyboardInterrupt, EOFError):
            break
        mode = None  # reset so subsequent iterations always re-prompt

        if chosen_mode == "exit":
            break

        if chosen_mode == "monitor":
            project_root = collect_monitor_root()
            try:
                await monitor_async(project_root)
            except KeyboardInterrupt:
                console.print()
            console.print("[dim]Returned to main menu.[/dim]\n")
            continue

        spec = collect_project_spec()
        session = OrchestrationSession(spec)
        renderer = RichStatusRenderer()
        state_store = build_state_store(session.workspace_plan.root)

        async def event_handler(event: AgentEvent) -> None:
            renderer.handle_event(event)
            state_store.write(renderer.snapshot())
            live.update(renderer.render())

        console.print(f"Project root: [bold]{session.workspace_plan.root}[/bold]")
        console.print("Starting orchestrator...\n")

        with Live(renderer.render(), console=console, refresh_per_second=4) as live:
            results = await session.run(
                event_handler=event_handler,
                feedback_provider=lambda request: prompt_for_feedback(
                    request,
                    live=live,
                    renderer=renderer,
                    state_store=state_store,
                ),
            )
            final_snapshot = renderer.snapshot()
            final_snapshot.mode = "completed"
            state_store.write(final_snapshot)

        console.print()
        console.print(summarize_results(results.results))
        console.print(f"Artifacts manifest: {results.artifact_store.manifest_path}")
        console.print(f"Live session state: {state_store.path}")
        console.print("Finished.\n")


async def monitor_async(project_root: Path, iterations: int | None = None) -> None:
    state_store = build_state_store(project_root)
    renderer = RichStatusRenderer()
    count = 0

    console.print("[dim]Press Ctrl+C to return to the main menu.[/dim]\n")
    with Live(renderer.render(), console=console, refresh_per_second=2) as live:
        while True:
            try:
                snapshot = state_store.read()
                renderer.load_snapshot(snapshot)
                live.update(renderer.render())
                count += 1
                if iterations is not None and count >= iterations:
                    break
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break


def app_main() -> None:
    app()


if __name__ == "__main__":
    app_main()
