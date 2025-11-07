"""Command-line interface for Mouc."""

from __future__ import annotations

import importlib
import importlib.util
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from .exceptions import MoucError
from .gantt import GanttScheduler
from .graph import GraphGenerator, GraphView
from .jira_cli import jira_app
from .markdown import MarkdownGenerator
from .parser import FeatureMapParser

app = typer.Typer(
    name="mouc",
    help="Mapping Outcomes User stories and Capabilities - A lightweight dependency tracking system",
    add_completion=False,
)

# Global state for verbosity level and config path
_verbosity_level = 0
_config_path: Path | None = None


def get_verbosity() -> int:
    """Get the current verbosity level."""
    return _verbosity_level


def get_config_path() -> Path | None:
    """Get the global config path."""
    return _config_path


@app.callback()
def main_callback(
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            help="Verbosity level: 0=silent (default), 1=show changes, 2=show all checks, 3=debug",
            min=0,
            max=3,
        ),
    ] = 0,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to unified config file (default: mouc_config.yaml)",
        ),
    ] = None,
) -> None:
    """Global options for mouc commands."""
    global _verbosity_level, _config_path
    _verbosity_level = verbose
    _config_path = config


@app.command()
def graph(
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    view: Annotated[
        GraphView, typer.Option("--view", help="Type of graph to generate")
    ] = GraphView.ALL,
    target: Annotated[
        str | None, typer.Option("--target", "-t", help="Target for critical path view")
    ] = None,
    tags: Annotated[list[str] | None, typer.Option("--tags", help="Tags for filtered view")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path")] = None,
    style_module: Annotated[
        str | None,
        typer.Option("--style-module", help="Python module path for styling functions"),
    ] = None,
    style_file: Annotated[
        Path | None,
        typer.Option("--style-file", help="Python file path for styling functions"),
    ] = None,
) -> None:
    """Generate dependency graphs in DOT format."""
    try:
        # Validate arguments
        if view == GraphView.CRITICAL_PATH and not target:
            typer.echo("Error: Critical path view requires --target", err=True)
            raise typer.Exit(1) from None

        if view == GraphView.FILTERED and not tags:
            typer.echo("Error: Filtered view requires --tags", err=True)
            raise typer.Exit(1) from None

        if style_module and style_file:
            typer.echo("Error: Cannot specify both --style-module and --style-file", err=True)
            raise typer.Exit(1) from None

        # Load styling module if specified
        if style_module or style_file:
            _load_styling(style_module, style_file)

        # Parse the feature map
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        # Generate the graph
        generator = GraphGenerator(feature_map)
        dot_output = generator.generate(view, target=target, tags=tags)

        # Output the result
        if output:
            output.write_text(dot_output, encoding="utf-8")
            typer.echo(f"Graph written to {output}")
        else:
            typer.echo(dot_output)

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        import traceback

        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


@app.command()
def doc(
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path")] = None,
    style_module: Annotated[
        str | None,
        typer.Option("--style-module", help="Python module path for styling functions"),
    ] = None,
    style_file: Annotated[
        Path | None,
        typer.Option("--style-file", help="Python file path for styling functions"),
    ] = None,
) -> None:
    """Generate documentation in Markdown format."""
    try:
        if style_module and style_file:
            typer.echo("Error: Cannot specify both --style-module and --style-file", err=True)
            raise typer.Exit(1) from None

        # Load styling module if specified
        if style_module or style_file:
            _load_styling(style_module, style_file)

        # Parse the feature map
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        # Generate the markdown
        generator = MarkdownGenerator(feature_map)
        markdown_output = generator.generate()

        # Output the result
        if output:
            output.write_text(markdown_output, encoding="utf-8")
            typer.echo(f"Documentation written to {output}")
        else:
            typer.echo(markdown_output)

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        import traceback

        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


@app.command()
def gantt(
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    start_date: Annotated[
        str | None,
        typer.Option(
            "--start-date",
            "-s",
            help="Chart start date (left edge of visualization, YYYY-MM-DD). "
            "Defaults to min(first fixed task date, current date)",
        ),
    ] = None,
    current_date: Annotated[
        str | None,
        typer.Option(
            "--current-date",
            "-c",
            help="Current/as-of date for scheduling (YYYY-MM-DD). Defaults to today",
        ),
    ] = None,
    title: Annotated[str, typer.Option("--title", "-t", help="Chart title")] = "Project Schedule",
    group_by: Annotated[
        str,
        typer.Option(
            "--group-by",
            "-g",
            help="Group tasks by 'type' (capability/user story/outcome) or 'resource' (person/team)",
        ),
    ] = "type",
    tick_interval: Annotated[
        str | None,
        typer.Option(
            "--tick-interval",
            help="Mermaid tickInterval for x-axis (e.g., '1week', '1month', '3month' for quarters)",
        ),
    ] = None,
    axis_format: Annotated[
        str | None,
        typer.Option(
            "--axis-format",
            help="Mermaid axisFormat for date display (e.g., '%%Y-%%m-%%d', '%%b %%Y')",
        ),
    ] = None,
    vertical_dividers: Annotated[
        str | None,
        typer.Option(
            "--vertical-dividers",
            help="Add vertical dividers at intervals: 'quarter', 'halfyear', or 'year'",
        ),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            help="Use compact display mode to show multiple tasks in same row when possible",
        ),
    ] = False,
    resources: Annotated[
        Path | None,
        typer.Option(
            "--resources",
            "-r",
            help="[DEPRECATED] Use --config instead. Path to resources.yaml file for automatic resource assignment",
        ),
    ] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path")] = None,
) -> None:
    """Generate Gantt chart in Mermaid format."""
    try:
        # Validate group_by parameter
        if group_by not in ("type", "resource"):
            typer.echo(
                f"Error: Invalid group-by value '{group_by}'. Must be 'type' or 'resource'.",
                err=True,
            )
            raise typer.Exit(1) from None

        # Validate vertical_dividers parameter
        if vertical_dividers and vertical_dividers not in ("quarter", "halfyear", "year"):
            typer.echo(
                f"Error: Invalid vertical-dividers value '{vertical_dividers}'. "
                "Must be 'quarter', 'halfyear', or 'year'.",
                err=True,
            )
            raise typer.Exit(1) from None

        # Parse start date if provided
        parsed_start_date: date | None = None
        if start_date:
            try:
                parsed_start_date = date.fromisoformat(start_date)
            except ValueError:
                typer.echo(
                    f"Error: Invalid date format '{start_date}'. Use YYYY-MM-DD format.",
                    err=True,
                )
                raise typer.Exit(1) from None

        # Parse current date if provided
        parsed_current_date: date | None = None
        if current_date:
            try:
                parsed_current_date = date.fromisoformat(current_date)
            except ValueError:
                typer.echo(
                    f"Error: Invalid date format '{current_date}'. Use YYYY-MM-DD format.",
                    err=True,
                )
                raise typer.Exit(1) from None

        # Parse the feature map
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        # Determine which config to use for resources
        # Priority: --resources flag > global --config > default mouc_config.yaml
        resource_config_path = resources
        if not resource_config_path:
            global_config_path = get_config_path()
            if global_config_path:
                resource_config_path = global_config_path
            elif Path("mouc_config.yaml").exists():
                resource_config_path = Path("mouc_config.yaml")

        # Schedule tasks
        scheduler = GanttScheduler(
            feature_map,
            start_date=parsed_start_date,
            current_date=parsed_current_date,
            resource_config_path=resource_config_path,
        )
        result = scheduler.schedule()

        # Generate Mermaid chart
        mermaid_output = scheduler.generate_mermaid(
            result,
            title=title,
            group_by=group_by,
            tick_interval=tick_interval,
            axis_format=axis_format,
            vertical_dividers=vertical_dividers,
            compact=compact,
        )

        # Output the result
        if output:
            # Wrap in markdown code fence if output is a .md file
            if output.suffix.lower() == ".md":
                output_content = f"```mermaid\n{mermaid_output}\n```\n"
            else:
                output_content = mermaid_output
            output.write_text(output_content, encoding="utf-8")
            typer.echo(f"Gantt chart written to {output}")
        else:
            typer.echo(mermaid_output)

        # Show warnings if any
        if result.warnings:
            typer.echo("\nWarnings:", err=True)
            for warning in result.warnings:
                typer.echo(f"  - {warning}", err=True)

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        import traceback

        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


@app.command()
def status(
    target: Annotated[str, typer.Argument(help="Outcome ID to check status for")],
    file: Annotated[
        Path, typer.Option("--file", "-f", help="Path to the feature map YAML file")
    ] = Path("feature_map.yaml"),
) -> None:
    """Show status of an outcome and its dependencies."""
    typer.echo(f"Status query for '{target}' not yet implemented", err=True)
    raise typer.Exit(1)


@app.command()
def audit(
    check: Annotated[str, typer.Argument(help="Type of audit check (e.g., 'no-design-doc')")],
    tags: Annotated[list[str] | None, typer.Option("--tags", help="Filter by tags")] = None,
    file: Annotated[
        Path, typer.Option("--file", "-f", help="Path to the feature map YAML file")
    ] = Path("feature_map.yaml"),
) -> None:
    """Run audit checks on the feature map."""
    typer.echo(f"Audit check '{check}' not yet implemented", err=True)
    raise typer.Exit(1)


# Register Jira subcommands (defined in jira_cli.py)
app.add_typer(jira_app, name="jira")


def _load_styling(style_module: str | None, style_file: Path | None) -> None:
    """Load user styling module or file."""
    from . import styling

    # Clear any previous registrations
    styling.clear_registrations()

    if style_module:
        # Import from module path
        importlib.import_module(style_module)
    elif style_file:
        # Import from file path
        style_path = style_file.resolve()
        spec = importlib.util.spec_from_file_location("user_styles", style_path)
        if spec is None or spec.loader is None:
            raise MoucError(f"Could not load styling file: {style_file}")
        user_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(user_module)


def main() -> int:
    """Main entry point."""
    # Typer handles sys.exit() internally
    app()
    return 0


if __name__ == "__main__":
    main()
