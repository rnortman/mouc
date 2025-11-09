"""Command-line interface for Mouc."""

from __future__ import annotations

import importlib
import importlib.util
import traceback
from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from . import context, styling
from .exceptions import MoucError
from .gantt import GanttScheduler
from .graph import GraphGenerator, GraphView
from .jira_cli import jira_app, write_feature_map
from .markdown import MarkdownGenerator
from .models import FeatureMap
from .parser import FeatureMapParser
from .resources import ResourceConfig
from .scheduler import SchedulingResult, SchedulingService
from .unified_config import load_unified_config

app = typer.Typer(
    name="mouc",
    help="Mapping Outcomes User stories and Capabilities - A lightweight dependency tracking system",
    add_completion=False,
)


# Backwards compatibility wrappers for global state access
def get_verbosity() -> int:
    """Get the current verbosity level."""
    return context.get_verbosity()


def get_config_path() -> Path | None:
    """Get the global config path."""
    return context.get_config_path()


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
    context.set_verbosity(verbose)
    context.set_config_path(config)


@app.command()
def graph(  # noqa: PLR0913 - CLI command needs multiple options
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    *,
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
        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


@app.command()
def doc(  # noqa: PLR0913 - CLI command needs multiple options
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    *,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path")] = None,
    schedule: Annotated[
        bool,
        typer.Option(
            "--schedule",
            help="Run scheduler and populate schedule annotations for use in styling functions",
        ),
    ] = False,
    current_date: Annotated[
        str | None,
        typer.Option(
            "--current-date",
            help="Current/as-of date for scheduling (YYYY-MM-DD). Only used with --schedule",
        ),
    ] = None,
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

        # Load unified config if available
        unified_config = None
        config_path = get_config_path() or Path("mouc_config.yaml")
        if config_path.exists():
            unified_config = load_unified_config(config_path)

        # Optionally run scheduler to populate annotations
        if schedule:
            # Parse current date if provided
            parsed_current_date: date | None = None
            if current_date:
                try:
                    parsed_current_date = date.fromisoformat(current_date)
                except ValueError:
                    typer.echo(
                        f"Error: Invalid date format '{current_date}'. Use YYYY-MM-DD",
                        err=True,
                    )
                    raise typer.Exit(1) from None

            # Get resource config from unified config if available
            resource_config = unified_config.resources if unified_config else None

            # Run scheduling and populate annotations
            service = SchedulingService(feature_map, parsed_current_date, resource_config)
            service.populate_feature_map_annotations()

        # Generate the markdown
        markdown_config = unified_config.markdown if unified_config else None
        generator = MarkdownGenerator(feature_map, markdown_config)
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
        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


def _validate_gantt_params(group_by: str, vertical_dividers: str | None) -> None:
    """Validate gantt command parameters."""
    if group_by not in ("type", "resource"):
        typer.echo(
            f"Error: Invalid group-by value '{group_by}'. Must be 'type' or 'resource'.",
            err=True,
        )
        raise typer.Exit(1) from None

    if vertical_dividers and vertical_dividers not in ("quarter", "halfyear", "year"):
        typer.echo(
            f"Error: Invalid vertical-dividers value '{vertical_dividers}'. "
            "Must be 'quarter', 'halfyear', or 'year'.",
            err=True,
        )
        raise typer.Exit(1) from None


def _parse_date_option(date_str: str | None, option_name: str) -> date | None:
    """Parse a date string from CLI option.

    Args:
        date_str: Date string in YYYY-MM-DD format or None
        option_name: Name of the option for error messages

    Returns:
        Parsed date object or None if date_str is None
    """
    if date_str is None:
        return None

    try:
        return date.fromisoformat(date_str)
    except ValueError:
        typer.echo(
            f"Error: Invalid date format '{date_str}'. Use YYYY-MM-DD format.",
            err=True,
        )
        raise typer.Exit(1) from None


def _resolve_gantt_config_path(resources: Path | None) -> Path | None:
    """Resolve resource config path with priority: --resources > global --config > default."""
    if resources:
        return resources

    global_config_path = get_config_path()
    if global_config_path:
        return global_config_path

    default_path = Path("mouc_config.yaml")
    if default_path.exists():
        return default_path

    return None


def _load_gantt_markdown_url(config_path: Path | None) -> str | None:
    """Load markdown base URL from gantt config."""
    if not config_path:
        return None

    with suppress(FileNotFoundError, ValueError):
        unified_config = load_unified_config(config_path)
        if unified_config.gantt and unified_config.gantt.markdown_base_url:
            return unified_config.gantt.markdown_base_url

    return None


def _format_gantt_output(mermaid_output: str, output_path: Path | None) -> None:
    """Output or write Gantt chart result."""
    if output_path:
        # Wrap in markdown code fence if output is a .md file
        if output_path.suffix.lower() == ".md":
            output_content = f"```mermaid\n{mermaid_output}\n```\n"
        else:
            output_content = mermaid_output
        output_path.write_text(output_content, encoding="utf-8")
        typer.echo(f"Gantt chart written to {output_path}")
    else:
        typer.echo(mermaid_output)


@app.command()
def gantt(  # noqa: PLR0913 - CLI command needs multiple options
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    *,
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
    markdown_base_url: Annotated[
        str | None,
        typer.Option(
            "--markdown-base-url",
            help="Base URL for markdown links (e.g., './feature_map.md' or 'https://github.com/user/repo/blob/main/feature_map.md')",
        ),
    ] = None,
    style_module: Annotated[
        str | None,
        typer.Option("--style-module", help="Python module path for styling functions"),
    ] = None,
    style_file: Annotated[
        Path | None,
        typer.Option("--style-file", help="Python file path for styling functions"),
    ] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path")] = None,
) -> None:
    """Generate Gantt chart in Mermaid format."""
    try:
        if style_module and style_file:
            typer.echo("Error: Cannot specify both --style-module and --style-file", err=True)
            raise typer.Exit(1) from None

        # Load styling module if specified
        if style_module or style_file:
            _load_styling(style_module, style_file)

        # Validate parameters
        _validate_gantt_params(group_by, vertical_dividers)

        # Parse dates
        parsed_start_date = _parse_date_option(start_date, "start-date")
        parsed_current_date = _parse_date_option(current_date, "current-date")

        # Parse the feature map
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        # Resolve config path and load markdown URL
        resource_config_path = _resolve_gantt_config_path(resources)
        gantt_config_markdown_url = _load_gantt_markdown_url(resource_config_path)
        final_markdown_url = markdown_base_url or gantt_config_markdown_url

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
            markdown_base_url=final_markdown_url,
        )

        # Output the result
        _format_gantt_output(mermaid_output, output)

        # Show warnings if any
        if result.warnings:
            typer.echo("\nWarnings:", err=True)
            for warning in result.warnings:
                typer.echo(f"  - {warning}", err=True)

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


def _load_schedule_resource_config() -> tuple[Path | None, ResourceConfig | None]:
    """Load resource config for schedule command.

    Returns:
        Tuple of (config_path, resource_config)
    """
    config_path = get_config_path() or Path("mouc_config.yaml")
    if not config_path.exists():
        return None, None

    unified = load_unified_config(config_path)
    return config_path, unified.resources


def _annotate_feature_map(feature_map: FeatureMap, result: SchedulingResult, file: Path) -> None:
    """Write schedule annotations back to feature map YAML file."""
    for entity in feature_map.entities:
        if entity.id in result.annotations:
            annot = result.annotations[entity.id]
            if annot.estimated_start:
                entity.meta["estimated_start"] = annot.estimated_start.isoformat()
            if annot.estimated_end:
                entity.meta["estimated_end"] = annot.estimated_end.isoformat()

    write_feature_map(file, feature_map)
    typer.echo(f"Annotations written to {file}")


def _display_schedule_results(feature_map: FeatureMap, result: SchedulingResult) -> None:
    """Display schedule results to stdout."""
    typer.echo("Schedule Results")
    typer.echo("=" * 80)
    typer.echo("")

    for entity in feature_map.entities:
        if entity.id not in result.annotations:
            continue

        annot = result.annotations[entity.id]
        typer.echo(f"{entity.name} ({entity.id})")
        typer.echo(f"  Estimated Start:  {annot.estimated_start}")
        typer.echo(f"  Estimated End:    {annot.estimated_end}")
        if annot.computed_deadline:
            typer.echo(f"  Computed Deadline: {annot.computed_deadline}")
        if annot.deadline_violated:
            typer.echo("  ⚠️  DEADLINE VIOLATED")
        typer.echo(f"  Resources: {', '.join(f'{r}:{a}' for r, a in annot.resource_assignments)}")
        if annot.resources_were_computed:
            typer.echo("  (resources auto-assigned)")
        if annot.was_fixed:
            typer.echo("  (fixed dates, not scheduled)")
        typer.echo("")


@app.command()
def schedule(
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    current_date: Annotated[
        str | None,
        typer.Option(
            "--current-date",
            "-c",
            help="Current/as-of date for scheduling (YYYY-MM-DD). Defaults to today",
        ),
    ] = None,
    annotate_yaml: Annotated[
        bool,
        typer.Option(
            "--annotate-yaml",
            help="Write estimated_start/estimated_end back to YAML file",
        ),
    ] = False,
) -> None:
    """Run scheduling algorithm and display or persist results."""
    try:
        # Parse current date if provided
        parsed_current_date = _parse_date_option(current_date, "current-date")

        # Parse the feature map
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        # Load resource config if available
        _, resource_config = _load_schedule_resource_config()

        # Run scheduling service
        service = SchedulingService(feature_map, parsed_current_date, resource_config)
        result = service.schedule()

        # Display or persist results
        if annotate_yaml:
            _annotate_feature_map(feature_map, result, file)
        else:
            _display_schedule_results(feature_map, result)

        # Display warnings
        if result.warnings:
            typer.echo("\nWarnings:", err=True)
            for warning in result.warnings:
                typer.echo(f"  - {warning}", err=True)

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
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
