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
from orchestrator.ui import RichStatusRenderer

app = typer.Typer(help="Interactive multi-agent project orchestrator.")
console = Console()


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


def prompt_for_feedback(request: FeedbackRequest) -> str | None:
    return Prompt.ask(f"{request.prompt}", default="").strip() or None


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


async def run_async() -> None:
    spec = collect_project_spec()
    session = OrchestrationSession(spec)
    renderer = RichStatusRenderer()

    async def event_handler(event: AgentEvent) -> None:
        renderer.handle_event(event)
        live.update(renderer.render())

    console.print(f"Project root: [bold]{session.workspace_plan.root}[/bold]")
    console.print("Starting orchestrator...\n")

    with Live(renderer.render(), console=console, refresh_per_second=4) as live:
        results = await session.run(
            event_handler=event_handler,
            feedback_provider=prompt_for_feedback,
        )

    console.print()
    console.print(summarize_results(results.results))
    console.print(f"Artifacts manifest: {results.artifact_store.manifest_path}")
    console.print("Finished.")


def app_main() -> None:
    app()


if __name__ == "__main__":
    app_main()
