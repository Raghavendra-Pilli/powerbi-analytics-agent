"""CLI entry point for the Power BI Analytics Agent."""

import json
import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from pbi_agent.config import load_config
from pbi_agent.logging import setup_logger

console = Console()


@click.group()
@click.option("--config", default="config/settings.yaml", help="Path to config file")
@click.option("--env", default=".env", help="Path to .env file")
@click.pass_context
def cli(ctx, config, env):
    """Power BI Analytics Agent — connect, inspect, review, export."""
    ctx.ensure_object(dict)
    cfg = load_config(config, env)
    setup_logger(level=cfg.logging.level, log_file=cfg.logging.file, console=cfg.logging.console)
    ctx.obj["config"] = cfg


def _get_orchestrator(ctx):
    """Lazy-load orchestrator (requires API key for LLM features)."""
    if "orchestrator" not in ctx.obj:
        from pbi_agent.orchestrator import Orchestrator
        ctx.obj["orchestrator"] = Orchestrator(ctx.obj["config"])
    return ctx.obj["orchestrator"]


# ── Interactive chat (requires LLM) ─────────────────────────────────────────

@cli.command()
@click.pass_context
def chat(ctx):
    """Start an interactive chat session with the agent."""
    orch = _get_orchestrator(ctx)

    console.print(Panel(
        "[bold green]Power BI Analytics Agent[/bold green]\n"
        "Commands: connect, inspect, review, export, help, quit\n"
        "Or just describe what you want in natural language.",
        title="Welcome",
        border_style="blue",
    ))

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if not user_input.strip():
            continue

        with console.status("[bold yellow]Thinking...[/bold yellow]"):
            response = orch.process(user_input)

        console.print(f"\n[bold green]Agent[/bold green]: {response}")


# ── Offline commands (no LLM required) ───────────────────────────────────────

@cli.command()
@click.argument("path")
@click.option("--llm/--no-llm", default=False, help="Include LLM analysis (requires API key)")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.pass_context
def inspect(ctx, path, llm, json_output):
    """Inspect a PBIP project's semantic model."""
    from pbi_agent.inspector.model_inspector import ModelInspector

    config = ctx.obj["config"]
    llm_client = None
    if llm:
        from pbi_agent.llm.client import LLMClient
        llm_client = LLMClient(config.llm)

    inspector = ModelInspector(config.inspector, llm_client)

    with console.status("[bold yellow]Inspecting model...[/bold yellow]"):
        result = inspector.inspect(path, use_llm=llm)

    if json_output:
        console.print_json(json.dumps(result))
    else:
        console.print(result.get("report", "No report generated."))


@cli.command()
@click.argument("path")
@click.option("--llm/--no-llm", default=False, help="Include LLM analysis (requires API key)")
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.pass_context
def review(ctx, path, llm, json_output):
    """Review a PBIP project's report health."""
    from pbi_agent.reviewer.report_reviewer import ReportReviewer

    config = ctx.obj["config"]
    llm_client = None
    if llm:
        from pbi_agent.llm.client import LLMClient
        llm_client = LLMClient(config.llm)

    reviewer = ReportReviewer(config.reviewer, llm_client)

    with console.status("[bold yellow]Reviewing report...[/bold yellow]"):
        result = reviewer.review(path, use_llm=llm)

    if json_output:
        console.print_json(json.dumps(result))
    else:
        console.print(result.get("report", "No report generated."))


@cli.command(name="export")
@click.argument("path")
@click.option("--format", "fmt", type=click.Choice(["pbix", "pbip"]), default="pbip",
              help="Export format")
@click.option("--output", "-o", default=None, help="Output directory")
@click.pass_context
def export_cmd(ctx, path, fmt, output):
    """Export a PBIP project to PBIX or a documentation package."""
    from pbi_agent.export.export_engine import ExportEngine

    config = ctx.obj["config"]
    config.export.default_format = fmt

    engine = ExportEngine(config.export, config.pbi_tools)

    with console.status(f"[bold yellow]Exporting as {fmt.upper()}...[/bold yellow]"):
        result = engine.export(path, output)

    if result.get("success"):
        console.print(f"[green]{result['message']}[/green]")
        if result.get("artifacts"):
            console.print("\nArtifacts:")
            for a in result["artifacts"]:
                console.print(f"  - {a}")
    else:
        console.print(f"[red]Export failed: {result.get('error')}[/red]")


@cli.command()
@click.argument("path")
@click.option("--output", "-o", default=None, help="Output directory")
@click.pass_context
def extract(ctx, path, output):
    """Extract a PBIX file to TMDL format (requires pbi-tools)."""
    from pbi_agent.export.export_engine import ExportEngine

    config = ctx.obj["config"]
    engine = ExportEngine(config.export, config.pbi_tools)

    with console.status("[bold yellow]Extracting PBIX to TMDL...[/bold yellow]"):
        result = engine.extract_to_tmdl(path, output)

    if result.success:
        console.print(f"[green]{result.message}[/green]")
    else:
        console.print(f"[red]Extraction failed: {result.error}[/red]")


@cli.command()
@click.argument("path")
@click.pass_context
def connect(ctx, path):
    """Connect to a data source (CSV, Excel, or directory)."""
    from pbi_agent.connectors.csv_connector import FileConnector

    connector = FileConnector()

    with console.status("[bold yellow]Connecting...[/bold yellow]"):
        result = connector.connect(path)

    if result.success:
        console.print(f"[green]Connected: {result.table_count} table(s)[/green]")
        for t in result.tables:
            console.print(f"  - {t.name}: {t.row_count:,} rows, {t.column_count} columns ({t.file_type})")
    else:
        console.print(f"[red]Failed: {result.error}[/red]")


@cli.command()
def version():
    """Show agent version."""
    from pbi_agent import __version__
    console.print(f"Power BI Analytics Agent v{__version__}")


if __name__ == "__main__":
    cli()
