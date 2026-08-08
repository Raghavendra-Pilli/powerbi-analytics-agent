"""CLI entry point for the Power BI Analytics Agent."""

import json
from pathlib import Path

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
@click.option("--summary", "-s", is_flag=True, help="Show only counts and AI analysis, skip the itemized findings list")
@click.pass_context
def inspect(ctx, path, llm, json_output, summary):
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
    elif summary:
        s = result.get("summary", {})
        counts = result.get("counts", {})
        console.print(f"[bold]Model:[/bold] {s.get('table_count', '?')} tables, "
                       f"{s.get('total_columns', '?')} columns, {s.get('total_measures', '?')} measures, "
                       f"{s.get('relationship_count', '?')} relationships")
        console.print(f"[bold]Issues:[/bold] {counts.get('errors', 0)} errors, "
                       f"{counts.get('warnings', 0)} warnings, {counts.get('info', 0)} info\n")
        if result.get("llm_analysis"):
            console.print(result["llm_analysis"])
        else:
            console.print("[dim]No AI analysis available. Re-run with --llm to include it.[/dim]")
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


@cli.command()
@click.argument("path")
@click.option("--output", "-o", default=None, help="Output markdown file path")
@click.pass_context
def document(ctx, path, output):
    """Generate plain-language business documentation for a PBIP project (requires API key)."""
    from pbi_agent.inspector.business_doc import BusinessDocGenerator
    from pbi_agent.llm.client import LLMClient

    config = ctx.obj["config"]
    llm_client = LLMClient(config.llm)
    generator = BusinessDocGenerator(llm_client)

    with console.status("[bold yellow]Generating business documentation (this can take a minute)...[/bold yellow]"):
        markdown = generator.generate(path)

    out_path = output or (Path(path).name.replace(".pbip", "") + "_business_doc.md")
    Path(out_path).write_text(markdown, encoding="utf-8")

    console.print(f"[green]Business documentation saved to: {out_path}[/green]")


@cli.command()
@click.argument("path")
@click.option("--output", "-o", default=None, help="Output directory for the fixed copy (ignored with --in-place)")
@click.option("--in-place", is_flag=True, default=False, help="Modify the original project files directly (default: writes a safe copy)")
@click.pass_context
def remediate(ctx, path, output, in_place):
    """Fix model gaps: generate missing DAX, fix the date table, and report a before/after health score."""
    from pbi_agent.remediate.model_fixer import ModelFixer
    from pbi_agent.llm.client import LLMClient

    config = ctx.obj["config"]
    llm_client = LLMClient(config.llm)
    fixer = ModelFixer(llm_client)

    if in_place:
        console.print("[yellow]--in-place: modifying your original project files directly.[/yellow]")

    with console.status("[bold yellow]Analyzing and fixing the model (this can take a minute)...[/bold yellow]"):
        result = fixer.remediate(path, output_dir=output, in_place=in_place)

    if not result.success:
        console.print(f"[red]Remediation failed: {result.error}[/red]")
        return

    console.print(f"[bold]Before:[/bold] {result.before_score}")
    console.print(f"[bold]After:[/bold]  {result.after_score}\n")

    console.print("[bold]Changes made:[/bold]")
    for c in result.changes:
        console.print(f"  - [{c.category}] {c.description}")

    console.print(f"\n[green]Fixed project written to: {result.output_path}[/green]")

    spec_path = Path(result.output_path).parent / (Path(result.output_path).name + "_dashboard_spec.md")
    spec_path.write_text(result.dashboard_spec, encoding="utf-8")
    console.print(f"[green]Dashboard page specification written to: {spec_path}[/green]")


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
@click.option("--output", "-o", default=".", help="Output directory for the new PBIP project")
@click.option("--name", "-n", default=None, help="Project name (default: derived from file name)")
@click.pass_context
def scaffold(ctx, path, output, name):
    """Generate a starter .pbip project from a connected CSV/Excel file."""
    from pbi_agent.connectors.csv_connector import FileConnector
    from pbi_agent.export.pbip_scaffolder import PbipScaffolder

    connector = FileConnector()
    with console.status("[bold yellow]Reading source file...[/bold yellow]"):
        file_result = connector.connect(path)

    if not file_result.success:
        console.print(f"[red]Could not read source file: {file_result.error}[/red]")
        return

    scaffolder = PbipScaffolder()
    with console.status("[bold yellow]Generating PBIP project...[/bold yellow]"):
        result = scaffolder.scaffold(file_result, output, name)

    if result.success:
        console.print(f"[green]{result.message}[/green]")
        for w in result.warnings:
            console.print(f"[yellow]Note: {w}[/yellow]")
    else:
        console.print(f"[red]Scaffold failed: {result.error}[/red]")


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
