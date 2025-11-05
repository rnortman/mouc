"""Gantt chart scheduling for Mouc - data preparation and rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .scheduler import UNASSIGNED_RESOURCE, ParallelScheduler, Task

if TYPE_CHECKING:
    from .models import Entity, FeatureMap
    from .resources import ResourceConfig


def parse_timeframe(
    timeframe_str: str, fiscal_year_start: int = 1
) -> tuple[date | None, date | None]:
    """Parse timeframe string to (start_date, end_date).

    Supported formats:
    - "2025q1", "2025Q1" - Calendar quarter (Q1=Jan-Mar, Q2=Apr-Jun, etc)
    - "2025w01", "2025W52" - Calendar week (ISO week numbers)
    - "2025h1", "2025H2" - Calendar half (H1=Jan-Jun, H2=Jul-Dec)
    - "2025" - Full year
    - "2025-01" - Month

    Args:
        timeframe_str: The timeframe string to parse
        fiscal_year_start: Month number (1-12) when fiscal year starts (default: 1 = January)

    Returns:
        Tuple of (start_date, end_date), or (None, None) if unparseable
    """
    timeframe_str = timeframe_str.strip()

    # Quarter: 2025q1, 2025Q3
    quarter_match = re.match(r"^(\d{4})[qQ]([1-4])$", timeframe_str)
    if quarter_match:
        year = int(quarter_match.group(1))
        quarter = int(quarter_match.group(2))

        # Calculate quarter start month (adjusted for fiscal year)
        quarter_start_month = ((quarter - 1) * 3 + fiscal_year_start - 1) % 12 + 1
        quarter_start_year = year if quarter_start_month >= fiscal_year_start else year - 1

        start_date = date(quarter_start_year, quarter_start_month, 1)

        # End is last day of third month in quarter
        end_month = quarter_start_month + 2
        end_year = quarter_start_year
        if end_month > 12:
            end_month -= 12
            end_year += 1

        # Get last day of month
        if end_month == 12:
            end_date = date(end_year, 12, 31)
        else:
            end_date = date(end_year, end_month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Week: 2025w01, 2025W52
    week_match = re.match(r"^(\d{4})[wW](\d{2})$", timeframe_str)
    if week_match:
        year = int(week_match.group(1))
        week = int(week_match.group(2))

        if week < 1 or week > 53:
            return (None, None)

        # ISO week date: get Monday of the week
        # Jan 4 is always in week 1
        jan4 = date(year, 1, 4)
        week1_monday = jan4 - timedelta(days=jan4.weekday())
        start_date = week1_monday + timedelta(weeks=week - 1)
        end_date = start_date + timedelta(days=6)  # Sunday

        return (start_date, end_date)

    # Half: 2025h1, 2025H2
    half_match = re.match(r"^(\d{4})[hH]([12])$", timeframe_str)
    if half_match:
        year = int(half_match.group(1))
        half = int(half_match.group(2))

        # Calculate half start month (adjusted for fiscal year)
        half_start_month = ((half - 1) * 6 + fiscal_year_start - 1) % 12 + 1
        half_start_year = year if half_start_month >= fiscal_year_start else year - 1

        start_date = date(half_start_year, half_start_month, 1)

        # End is last day of sixth month in half
        end_month = half_start_month + 5
        end_year = half_start_year
        if end_month > 12:
            end_month -= 12
            end_year += 1

        # Get last day of month
        if end_month == 12:
            end_date = date(end_year, 12, 31)
        else:
            end_date = date(end_year, end_month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Month: 2025-01
    month_match = re.match(r"^(\d{4})-(\d{2})$", timeframe_str)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))

        if month < 1 or month > 12:
            return (None, None)

        start_date = date(year, month, 1)

        # Get last day of month
        if month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Year: 2025
    year_match = re.match(r"^(\d{4})$", timeframe_str)
    if year_match:
        year = int(year_match.group(1))
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        return (start_date, end_date)

    # Unparseable
    return (None, None)


class GanttMetadata(BaseModel):
    """Validated metadata for gantt scheduling."""

    effort: str = "1w"
    resources: list[str | tuple[str, float]] = Field(default_factory=list[str | tuple[str, float]])
    start_date: str | date | None = None  # Fixed start date (task won't be scheduled)
    end_date: str | date | None = None  # Fixed end date (task won't be scheduled)
    start_after: str | date | None = None  # Constraint: earliest possible start
    end_before: str | date | None = None  # Constraint: hard deadline
    timeframe: str | None = None  # Convenience: sets start_after and end_before from timeframe


@dataclass(slots=True, frozen=True)
class ScheduledTask:
    """A task with calculated start and end dates."""

    entity_id: str
    start_date: date
    end_date: date
    duration_days: float
    resources: list[str]


@dataclass(slots=True, frozen=True)
class ScheduleResult:
    """Result of scheduling operation."""

    tasks: list[ScheduledTask] = field(default_factory=list[ScheduledTask])
    warnings: list[str] = field(default_factory=list[str])


class GanttScheduler:
    """Resource-aware deadline-driven scheduler for Mouc entities.

    This class handles data preparation and rendering. The core scheduling
    algorithm is implemented in the scheduler module.
    """

    def __init__(
        self,
        feature_map: FeatureMap,
        start_date: date | None = None,
        current_date: date | None = None,
        resource_config: ResourceConfig | None = None,
        resource_config_path: Path | str | None = None,
    ):
        """Initialize scheduler with a feature map and optional dates.

        Args:
            feature_map: The feature map to schedule
            start_date: Chart start date (left edge of visualization).
                       If None, defaults to min(first fixed task date, current_date)
            current_date: Current/as-of date for scheduling.
                         If None, defaults to today
            resource_config: Optional pre-loaded resource configuration
            resource_config_path: Optional path to resources.yaml file
        """
        self.feature_map = feature_map
        self.current_date = current_date or date.today()  # noqa: DTZ011

        # Load resource config if path provided
        if resource_config is None and resource_config_path is not None:
            from contextlib import suppress

            from .resources import load_resource_config

            with suppress(FileNotFoundError):
                resource_config = load_resource_config(resource_config_path)

        self.resource_config = resource_config

        # Calculate start_date if not provided
        if start_date is None:
            self.start_date = self._calculate_chart_start_date()
        else:
            self.start_date = start_date

    def _calculate_chart_start_date(self) -> date:
        """Calculate chart start date from fixed task dates and current date.

        Returns minimum of:
        - All explicit start_date values from fixed tasks
        - current_date

        If no fixed tasks exist, returns current_date.
        """
        min_date = self.current_date

        # Check all entities for fixed start_date
        for entity in self.feature_map.entities:
            gantt_meta = self._get_gantt_meta(entity)
            if gantt_meta.start_date is not None:
                parsed_date = self._parse_date(gantt_meta.start_date)
                if parsed_date is not None:
                    min_date = min(min_date, parsed_date)

        return min_date

    def _get_gantt_meta(self, entity: Entity) -> GanttMetadata:
        """Extract and validate gantt metadata from entity."""
        return GanttMetadata(**entity.meta)

    def schedule(self) -> ScheduleResult:
        """Schedule all entities respecting dependencies, resources, and deadlines."""
        result = ScheduleResult()
        entities_by_id = {e.id: e for e in self.feature_map.entities}

        # Convert all entities to scheduler tasks
        tasks_to_schedule: list[Task] = []

        for entity in self.feature_map.entities:
            gantt_meta = self._get_gantt_meta(entity)
            resources, resource_spec = self._parse_resources(gantt_meta.resources)

            # Handle fixed tasks (with explicit start_date or end_date)
            if gantt_meta.start_date is not None or gantt_meta.end_date is not None:
                start, end = self._schedule_fixed_task(entity)

                task = Task(
                    id=entity.id,
                    duration_days=(end - start).days,
                    resources=resources,
                    dependencies=list(entity.requires),
                    start_on=start,
                    end_on=end,
                    resource_spec=resource_spec,
                )
                tasks_to_schedule.append(task)
            else:
                # Regular task: calculate duration and constraints
                duration = self._calculate_duration(entity)
                start_after = None
                end_before = None

                if gantt_meta.start_after:
                    start_after = self._parse_date(gantt_meta.start_after)
                elif gantt_meta.timeframe:
                    timeframe_start, _ = parse_timeframe(gantt_meta.timeframe)
                    if timeframe_start:
                        start_after = timeframe_start

                if gantt_meta.end_before:
                    end_before = self._parse_date(gantt_meta.end_before)
                elif gantt_meta.timeframe:
                    _, timeframe_end = parse_timeframe(gantt_meta.timeframe)
                    if timeframe_end:
                        end_before = timeframe_end

                task = Task(
                    id=entity.id,
                    duration_days=duration,
                    resources=resources,
                    dependencies=list(entity.requires),
                    start_after=start_after,
                    end_before=end_before,
                    resource_spec=resource_spec,
                )
                tasks_to_schedule.append(task)

        # Run the scheduler
        try:
            scheduler = ParallelScheduler(
                tasks_to_schedule, self.current_date, resource_config=self.resource_config
            )
            scheduled_tasks = scheduler.schedule()

            # Convert scheduler results to our format
            for scheduled_task in scheduled_tasks:
                result.tasks.append(
                    ScheduledTask(
                        entity_id=scheduled_task.task_id,
                        start_date=scheduled_task.start_date,
                        end_date=scheduled_task.end_date,
                        duration_days=scheduled_task.duration_days,
                        resources=scheduled_task.resources,
                    )
                )

            # Check for deadline violations
            for task in result.tasks:
                entity = entities_by_id[task.entity_id]
                gantt_meta = self._get_gantt_meta(entity)

                deadline = None
                if gantt_meta.end_before:
                    deadline = self._parse_date(gantt_meta.end_before)
                elif gantt_meta.timeframe:
                    _, deadline = parse_timeframe(gantt_meta.timeframe)

                if deadline and task.end_date > deadline:
                    days_late = (task.end_date - deadline).days
                    result.warnings.append(
                        f"Entity '{task.entity_id}' finishes {days_late} days after required date "
                        f"({task.end_date} vs {deadline})"
                    )

        except ValueError as e:
            result.warnings.append(str(e))

        return result

    def _schedule_fixed_task(self, entity: Entity) -> tuple[date, date]:
        """Schedule a task with fixed start_date and/or end_date.

        Args:
            entity: The entity to schedule

        Returns:
            Tuple of (start_date, end_date)
        """
        gantt_meta = self._get_gantt_meta(entity)

        start = self._parse_date(gantt_meta.start_date) if gantt_meta.start_date else None
        end = self._parse_date(gantt_meta.end_date) if gantt_meta.end_date else None

        # If both are specified, use them
        if start is not None and end is not None:
            return (start, end)

        # If only start_date is specified, compute end_date from effort
        if start is not None:
            duration = self._calculate_duration(entity)
            end = start + timedelta(days=duration)
            return (start, end)

        # If only end_date is specified, compute start_date from effort
        if end is not None:
            duration = self._calculate_duration(entity)
            start = end - timedelta(days=duration)
            return (start, end)

        # Shouldn't reach here
        raise ValueError(f"Entity {entity.id} has neither start_date nor end_date")

    def _calculate_duration(self, entity: Entity) -> float:
        """Calculate duration in days from effort and resource allocation."""
        gantt_meta = self._get_gantt_meta(entity)
        effort_days = self._parse_effort(gantt_meta.effort)
        resources, resource_spec = self._parse_resources(gantt_meta.resources)

        # Total capacity = sum of resource allocations
        # If resource_spec is set (wildcard/group), assume 1.0 capacity for duration calc
        if resource_spec:
            total_capacity = 1.0
        else:
            total_capacity = sum(capacity for _, capacity in resources)
            if total_capacity == 0:
                total_capacity = 1.0

        return effort_days / total_capacity

    def _parse_effort(self, effort_str: str) -> float:
        """Parse effort string to calendar days for scheduling.

        Supported formats:
        - "5d" = 5 calendar days
        - "2w" = 14 calendar days (2 weeks * 7 days)
        - "1.5m" = 45 calendar days (1.5 months * 30 days)
        - "L" = Large (equivalent to 60 days, or 2 months)

        Note: We use calendar days for Gantt chart scheduling, not working days.
        """
        effort_str = effort_str.strip().lower()

        # Check for size labels first
        if effort_str == "l":
            return 60.0  # 2 months

        match = re.match(r"^([\d.]+)([dwm])$", effort_str)
        if not match:
            return 7.0  # Default to 1 week

        value, unit = match.groups()
        num = float(value)

        if unit == "d":
            return num
        if unit == "w":
            return num * 7  # 7 calendar days per week
        if unit == "m":
            return num * 30  # 30 calendar days per month (approximation)
        return 7.0

    def _parse_resources(
        self, resources_raw: list[str | tuple[str, float]]
    ) -> tuple[list[tuple[str, float]], str | None]:
        """Parse resources list to (name, capacity) tuples and extract resource spec.

        Supported formats:
        - ["alice"] -> ([("alice", 1.0)], None)
        - ["alice", "bob"] -> ([("alice", 1.0), ("bob", 1.0)], None)
        - ["alice:0.5"] -> ([("alice", 0.5)], None)
        - ["*"] -> ([], "*")  - wildcard, needs auto-assignment
        - ["john|mary|susan"] -> ([], "john|mary|susan") - multi-resource, needs auto-assignment
        - [] -> ([], None) - empty, unassigned (becomes [("unassigned", 1.0)])

        Returns:
            Tuple of (resource list, resource_spec for auto-assignment)
            If resource_spec is not None, resource list will be empty and assignment is deferred
        """
        if not resources_raw:
            # Empty resources = use default_resource from config if available
            if self.resource_config and self.resource_config.default_resource:
                # Use configured default resource spec for auto-assignment
                return ([], self.resource_config.default_resource)
            # Fall back to UNASSIGNED_RESOURCE
            return ([(UNASSIGNED_RESOURCE, 1.0)], None)

        # Check for special specs that need auto-assignment (only wildcards and pipe-lists)
        if len(resources_raw) == 1:
            spec_str = str(resources_raw[0])
            # Only treat "*" or pipe-separated lists as auto-assignment specs
            if spec_str == "*" or "|" in spec_str:
                # Wildcard or pipe-separated list
                return ([], spec_str)

        # Parse as concrete resources
        result: list[tuple[str, float]] = []
        for resource_str in resources_raw:
            if isinstance(resource_str, tuple):
                # Handle tuple format: ("alice", 0.5)
                name_raw: str
                capacity_raw: float
                name_raw, capacity_raw = resource_str
                result.append((name_raw, capacity_raw))
            elif ":" in str(resource_str):
                # Handle string format: "alice:0.5"
                parts = str(resource_str).split(":", 1)
                name = parts[0].strip()
                try:
                    capacity = float(parts[1].strip())
                except ValueError:
                    capacity = 1.0
                result.append((name, capacity))
            else:
                # Handle plain name: "alice"
                # Check if this could be a group alias (needs resource config to determine)
                # For now, treat it as a concrete resource
                spec_str = str(resource_str).strip()
                # If resource_config exists and this is a group, return as spec
                if self.resource_config and spec_str in self.resource_config.groups:
                    return ([], spec_str)
                result.append((spec_str, 1.0))

        return (result, None)

    def _parse_date(self, date_str: str | date) -> date | None:
        """Parse a date string or date object to date object.

        Args:
            date_str: Either a string in ISO format (YYYY-MM-DD) or a date object

        Returns:
            date object or None if parsing fails
        """
        # If already a date object, return it
        if isinstance(date_str, date):
            return date_str

        try:
            # ISO format YYYY-MM-DD
            return date.fromisoformat(date_str.strip())
        except ValueError:
            return None

    def generate_mermaid(
        self,
        result: ScheduleResult,
        title: str = "Project Schedule",
        group_by: str = "type",
        tick_interval: str | None = None,
        axis_format: str | None = None,
        vertical_dividers: str | None = None,
        compact: bool = False,
    ) -> str:
        """Generate Mermaid gantt chart from schedule result.

        Args:
            result: The scheduling result containing tasks
            title: Chart title (default: "Project Schedule")
            group_by: How to group tasks - "type" (entity type) or "resource" (person/team)
            tick_interval: Mermaid tickInterval (e.g., "1week", "1month", "3month" for quarters)
            axis_format: Mermaid axisFormat string (e.g., "%Y-%m-%d", "%b %Y")
            vertical_dividers: Add vertical dividers at intervals: "quarter", "halfyear", or "year"
            compact: Use compact display mode to show multiple tasks in same row when possible

        Returns:
            Mermaid gantt chart syntax as a string
        """
        # Set todayMarker to current_date so the red line appears at the right position
        current_date_str = self.current_date.strftime("%Y-%m-%d")

        lines: list[str] = []

        # Add YAML frontmatter for compact mode
        if compact:
            lines.extend(
                [
                    "---",
                    "displayMode: compact",
                    "---",
                ]
            )

        lines.extend(
            [
                "gantt",
                f"    title {title}",
                "    dateFormat YYYY-MM-DD",
            ]
        )

        if tick_interval:
            lines.append(f"    tickInterval {tick_interval}")

        if axis_format:
            lines.append(f"    axisFormat {axis_format}")

        lines.append(f"    todayMarker {current_date_str}")
        lines.append("")

        # Add vertical dividers if requested
        if vertical_dividers and result.tasks:
            divider_lines = self._generate_vertical_dividers(result.tasks, vertical_dividers)
            lines.extend(divider_lines)
            if divider_lines:
                lines.append("")

        entities_by_id = {e.id: e for e in self.feature_map.entities}

        if group_by == "type":
            tasks_by_type: dict[str, list[ScheduledTask]] = {}

            for task in result.tasks:
                entity = entities_by_id[task.entity_id]
                entity_type = entity.type
                if entity_type not in tasks_by_type:
                    tasks_by_type[entity_type] = []
                tasks_by_type[entity_type].append(task)

            type_order = {"capability": 0, "user_story": 1, "outcome": 2}
            sorted_types = sorted(
                tasks_by_type.keys(),
                key=lambda t: type_order.get(t, 99),
            )

            for entity_type in sorted_types:
                section_name = entity_type.replace("_", " ").title()
                lines.append(f"    section {section_name}")

                tasks = tasks_by_type[entity_type]
                for task in tasks:
                    self._add_task_to_mermaid(lines, task, entities_by_id)

        elif group_by == "resource":
            tasks_by_resource: dict[str, list[ScheduledTask]] = {}

            for task in result.tasks:
                if not task.resources:
                    if "unassigned" not in tasks_by_resource:
                        tasks_by_resource["unassigned"] = []
                    tasks_by_resource["unassigned"].append(task)
                else:
                    for resource in task.resources:
                        if resource not in tasks_by_resource:
                            tasks_by_resource[resource] = []
                        tasks_by_resource[resource].append(task)

            sorted_resources = sorted(tasks_by_resource.keys())
            if "unassigned" in sorted_resources:
                sorted_resources.remove("unassigned")
                sorted_resources.append("unassigned")

            for resource in sorted_resources:
                lines.append(f"    section {resource}")

                tasks = tasks_by_resource[resource]
                for task in tasks:
                    self._add_task_to_mermaid(lines, task, entities_by_id)

        return "\n".join(lines)

    def _generate_vertical_dividers(
        self, tasks: list[ScheduledTask], divider_type: str
    ) -> list[str]:
        """Generate vertical divider lines for the Mermaid chart.

        Args:
            tasks: List of scheduled tasks to determine date range
            divider_type: Type of dividers - "quarter", "halfyear", or "year"

        Returns:
            List of Mermaid vert lines
        """
        if not tasks:
            return []

        # Find the date range from tasks
        min_date = min(task.start_date for task in tasks)
        max_date = max(task.end_date for task in tasks)

        dividers: list[str] = []

        if divider_type == "quarter":
            current = date(min_date.year, 1, 1)
            while current <= max_date:
                if current >= min_date:
                    quarter = (current.month - 1) // 3 + 1
                    label = f"Q{quarter} {current.year}"
                    vert_id = f"q{quarter}_{current.year}"
                    dividers.append(
                        f"    {label} : vert, {vert_id}, {current.strftime('%Y-%m-%d')}, 0d"
                    )
                if current.month == 10:
                    current = date(current.year + 1, 1, 1)
                else:
                    current = date(current.year, current.month + 3, 1)

        elif divider_type == "halfyear":
            current = date(min_date.year, 1, 1)
            while current <= max_date:
                if current >= min_date:
                    half = 1 if current.month == 1 else 2
                    label = f"H{half} {current.year}"
                    vert_id = f"h{half}_{current.year}"
                    dividers.append(
                        f"    {label} : vert, {vert_id}, {current.strftime('%Y-%m-%d')}, 0d"
                    )
                if current.month == 1:
                    current = date(current.year, 7, 1)
                else:
                    current = date(current.year + 1, 1, 1)

        elif divider_type == "year":
            current = date(min_date.year, 1, 1)
            while current <= max_date:
                if current >= min_date:
                    label = str(current.year)
                    vert_id = f"y{current.year}"
                    dividers.append(
                        f"    {label} : vert, {vert_id}, {current.strftime('%Y-%m-%d')}, 0d"
                    )
                current = date(current.year + 1, 1, 1)

        return dividers

    def _add_task_to_mermaid(
        self, lines: list[str], task: ScheduledTask, entities_by_id: dict[str, Entity]
    ) -> None:
        """Add a task to the Mermaid lines list.

        Args:
            lines: The list of Mermaid lines to append to
            task: The scheduled task to add
            entities_by_id: Map of entity IDs to entities
        """
        entity = entities_by_id[task.entity_id]
        gantt_meta = self._get_gantt_meta(entity)

        # Check if task has a deadline (explicit or from timeframe) and if it's violated
        is_late = False
        deadline_date = None

        if gantt_meta.end_before is not None:
            deadline_date = self._parse_date(gantt_meta.end_before)
        elif gantt_meta.timeframe is not None:
            _, deadline_date = parse_timeframe(gantt_meta.timeframe)

        # Check if task is late and create milestone if so
        if deadline_date is not None:
            is_late = task.end_date > deadline_date
            if is_late:
                milestone_label = f"{entity.name} Deadline"
                deadline_str = deadline_date.strftime("%Y-%m-%d")
                lines.append(
                    f"    {milestone_label} :milestone, crit, {task.entity_id}_deadline, "
                    f"{deadline_str}, 0d"
                )

        label = entity.name

        is_unassigned = task.resources == ["unassigned"] or not task.resources

        if task.resources:
            if is_unassigned:
                label += " (unassigned)"
            else:
                label += f" ({', '.join(task.resources)})"

        tags: list[str] = []
        if is_late:
            tags.append("crit")
        elif is_unassigned:
            tags.append("active")

        tags_str = ", ".join(tags) + ", " if tags else ""
        start_str = task.start_date.strftime("%Y-%m-%d")
        duration_str = f"{int(task.duration_days)}d"

        lines.append(f"    {label} :{tags_str}{task.entity_id}, {start_str}, {duration_str}")
