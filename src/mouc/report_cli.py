"""Report CLI commands."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from .loader import load_feature_map
from .models import Entity, FeatureMap
from .scheduler.lock import ScheduleLock, read_lock_file
from .scheduler.timeframes import parse_timeframe
from .scheduler.validator import SchedulerInputValidator

# Create report sub-app
report_app = typer.Typer(help="Generate reports from scheduled data")


def _parse_date_option(value: str | None, option_name: str) -> date | None:
    """Parse a date option string to a date object."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise typer.BadParameter(f"Invalid date format for --{option_name}: {value}") from e


def _validate_and_parse_time_range(
    timeframe: str | None, start: str | None, end: str | None
) -> tuple[date, date]:
    """Validate time range options and return (range_start, range_end)."""
    if timeframe and (start or end):
        typer.echo("Error: Cannot specify both --timeframe and --start/--end", err=True)
        raise typer.Exit(1)

    if not timeframe and not (start and end):
        typer.echo("Error: Must specify either --timeframe or both --start and --end", err=True)
        raise typer.Exit(1)

    if (start and not end) or (end and not start):
        typer.echo("Error: Both --start and --end are required when using date range", err=True)
        raise typer.Exit(1)

    if timeframe:
        range_start, range_end = parse_timeframe(timeframe)
        if not range_start or not range_end:
            typer.echo(f"Error: Invalid timeframe format: {timeframe}", err=True)
            raise typer.Exit(1)
    else:
        range_start = _parse_date_option(start, "start")
        range_end = _parse_date_option(end, "end")
        if not range_start or not range_end:
            typer.echo("Error: Invalid date format", err=True)
            raise typer.Exit(1)

    return range_start, range_end


def _calculate_effort_rows(
    feature_map: FeatureMap,
    schedule_lock: ScheduleLock,
    range_start: date,
    range_end: date,
) -> list[tuple[str, str, float]]:
    """Calculate effort per task in the given time range."""
    validator = SchedulerInputValidator()
    rows: list[tuple[str, str, float]] = []

    for entity in feature_map.entities:
        effort = _calculate_entity_effort(entity, schedule_lock, range_start, range_end, validator)
        if effort is not None:
            rows.append((entity.id, entity.name, effort))

    return rows


def _calculate_entity_effort(
    entity: Entity,
    schedule_lock: ScheduleLock,
    range_start: date,
    range_end: date,
    validator: SchedulerInputValidator,
) -> float | None:
    """Calculate effort for a single entity in the time range. Returns None if no overlap."""
    if entity.id not in schedule_lock.locks:
        return None

    lock = schedule_lock.locks[entity.id]
    task_start, task_end = lock.start_date, lock.end_date

    # Check overlap with range
    if task_start >= range_end or task_end <= range_start:
        return None

    # Calculate proportional effort
    overlap_start = max(task_start, range_start)
    overlap_end = min(task_end, range_end)
    overlap_days = (overlap_end - overlap_start).days
    total_days = (task_end - task_start).days

    if total_days <= 0:
        return None

    proportion = overlap_days / total_days
    effort_str = str(entity.meta.get("effort", "1w")) if entity.meta else "1w"
    effort_days = validator.parse_effort(effort_str)
    effort_in_range = effort_days * proportion
    effort_weeks = effort_in_range / 7.0

    return round(effort_weeks, 2)


@report_app.command("effort")
def effort(  # noqa: PLR0913 - CLI commands need all parameters for typer
    file: Annotated[Path, typer.Argument(help="Path to YAML roadmap file")],
    lock_file: Annotated[
        Path,
        typer.Argument(help="Path to schedule lock file (from mouc schedule --output-lock)"),
    ],
    timeframe: Annotated[
        str | None,
        typer.Option(
            "--timeframe",
            "-t",
            help="Timeframe string (e.g., '2025q1', '2025h1', '2025w01', '2025-03')",
        ),
    ] = None,
    start: Annotated[
        str | None,
        typer.Option("--start", help="Start date (YYYY-MM-DD) - use with --end"),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option("--end", help="End date (YYYY-MM-DD) - use with --start"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output CSV file path (required)"),
    ] = None,
) -> None:
    """Generate effort report for a time range.

    Shows tasks and their effort (in weeks) within the specified time range.
    Effort is calculated proportionally for tasks that span range boundaries.

    Requires a lock file from a previous scheduling run:
        mouc schedule roadmap.yaml --output-lock schedule.lock
        mouc report effort roadmap.yaml schedule.lock --timeframe 2025q1 -o effort.csv
    """
    if output is None:
        typer.echo("Error: --output is required", err=True)
        raise typer.Exit(1)

    range_start, range_end = _validate_and_parse_time_range(timeframe, start, end)

    # Validate files exist
    if not file.exists():
        typer.echo(f"Error: YAML file not found: {file}", err=True)
        raise typer.Exit(1)

    if not lock_file.exists():
        typer.echo(f"Error: Lock file not found: {lock_file}", err=True)
        raise typer.Exit(1)

    # Load entities from YAML (for effort values and names)
    feature_map = load_feature_map(file)

    # Load scheduled dates from lock file
    try:
        schedule_lock = read_lock_file(lock_file)
    except ValueError as e:
        typer.echo(f"Error reading lock file: {e}", err=True)
        raise typer.Exit(1) from None

    # Calculate effort per task in range
    rows = _calculate_effort_rows(feature_map, schedule_lock, range_start, range_end)

    # Write CSV
    with output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["task_id", "task_name", "effort_weeks"])
        writer.writerows(rows)

    typer.echo(f"Effort report written to {output} ({len(rows)} tasks)")
