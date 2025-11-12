"""Gantt chart scheduling for Mouc - data preparation and rendering."""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .backends.base import AnchorFunction
from .resources import UNASSIGNED_RESOURCE
from .scheduler import ParallelScheduler, SchedulingConfig, Task, parse_timeframe
from .scheduler import ScheduledTask as SchedulerTask
from .styling import StylingContext, apply_task_styles, create_styling_context
from .unified_config import load_unified_config

if TYPE_CHECKING:
    from .models import Entity, FeatureMap
    from .resources import ResourceConfig

# Constants for date calculations
OCTOBER = 10  # Month number for October, used for quarterly rollover


class GanttMetadata(BaseModel):
    """Validated metadata for gantt scheduling."""

    effort: str = "1w"
    resources: list[str | tuple[str, float]] = Field(default_factory=list[str | tuple[str, float]])
    start_date: str | date | None = None  # Fixed start date (task won't be scheduled)
    end_date: str | date | None = None  # Fixed end date (task won't be scheduled)
    start_after: str | date | None = None  # Constraint: earliest possible start
    end_before: str | date | None = None  # Constraint: hard deadline
    timeframe: str | None = None  # Convenience: sets start_after and end_before from timeframe
    status: str | None = None  # Task status: "done" marks task as completed
    priority: int = 50  # Urgency indicator (0-100, default 50)


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

    def __init__(  # noqa: PLR0913 - Multiple optional config parameters needed (keyword-only)
        self,
        feature_map: FeatureMap,
        *,
        start_date: date | None = None,
        current_date: date | None = None,
        resource_config: ResourceConfig | None = None,
        resource_config_path: Path | str | None = None,
        scheduler_config: SchedulingConfig | None = None,
        verbosity: int = 0,
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
            scheduler_config: Optional scheduling configuration for prioritization strategy
            verbosity: Debug output level (0=silent, 1=basic, 2=detailed, 3=debug)
        """
        self.feature_map = feature_map
        self.current_date = current_date or date.today()  # noqa: DTZ011

        # Load resource config if path provided
        if resource_config is None and resource_config_path is not None:
            # Load from unified config
            with suppress(FileNotFoundError):
                unified = load_unified_config(resource_config_path)
                resource_config = unified.resources
                if scheduler_config is None:
                    scheduler_config = unified.scheduler

        self.resource_config = resource_config
        self.scheduler_config = scheduler_config
        self.verbosity = verbosity

        # Calculate start_date if not provided
        if start_date is None:
            self.start_date = self._calculate_chart_start_date()
        else:
            self.start_date = start_date

        # Create styling context for task styling
        self.styling_context: StylingContext = create_styling_context(feature_map)

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

    def _create_fixed_task(self, entity: Entity, gantt_meta: GanttMetadata) -> Task:
        """Create a Task object for a fixed-date entity."""
        resources, resource_spec = self._parse_resources(gantt_meta.resources)
        start, end = self._schedule_fixed_task(entity)

        return Task(
            id=entity.id,
            duration_days=(end - start).days,
            resources=resources,
            dependencies=list(entity.requires),
            start_on=start,
            end_on=end,
            resource_spec=resource_spec,
            meta=entity.meta,
        )

    def _extract_constraints(self, gantt_meta: GanttMetadata) -> tuple[date | None, date | None]:
        """Extract start_after and end_before constraints from metadata.

        Returns:
            Tuple of (start_after, end_before)
        """
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

        return start_after, end_before

    def _create_regular_task(self, entity: Entity, gantt_meta: GanttMetadata) -> Task:
        """Create a Task object for a regular (non-fixed) entity."""
        resources, resource_spec = self._parse_resources(gantt_meta.resources)
        duration = self._calculate_duration(entity)
        start_after, end_before = self._extract_constraints(gantt_meta)

        return Task(
            id=entity.id,
            duration_days=duration,
            resources=resources,
            dependencies=list(entity.requires),
            start_after=start_after,
            end_before=end_before,
            resource_spec=resource_spec,
            meta=entity.meta,
        )

    def _convert_scheduler_results(
        self, scheduled_tasks: list[SchedulerTask], result: ScheduleResult
    ) -> None:
        """Convert scheduler results to ScheduledTask format."""
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

    def _check_deadline_violations(
        self, result: ScheduleResult, entities_by_id: dict[str, Entity]
    ) -> None:
        """Check for deadline violations and add warnings."""
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

    def schedule(self) -> ScheduleResult:
        """Schedule all entities respecting dependencies, resources, and deadlines."""
        result = ScheduleResult()
        entities_by_id = {e.id: e for e in self.feature_map.entities}

        # Track tasks marked done without dates (excluded from scheduling and Gantt)
        done_without_dates: set[str] = set()

        # Convert all entities to scheduler tasks
        tasks_to_schedule: list[Task] = []

        for entity in self.feature_map.entities:
            gantt_meta = self._get_gantt_meta(entity)

            # Check if task is marked done without dates
            if (
                gantt_meta.status == "done"
                and gantt_meta.start_date is None
                and gantt_meta.end_date is None
            ):
                # Exclude from scheduling and Gantt, but satisfies dependencies
                done_without_dates.add(entity.id)
                result.warnings.append(
                    f"Task '{entity.id}' marked done without dates - excluded from schedule"
                )
                continue

            # Handle fixed tasks (with explicit start_date or end_date)
            if gantt_meta.start_date is not None or gantt_meta.end_date is not None:
                task = self._create_fixed_task(entity, gantt_meta)
            else:
                # Regular task: calculate duration and constraints
                task = self._create_regular_task(entity, gantt_meta)

            tasks_to_schedule.append(task)

        # Run the scheduler
        try:
            scheduler = ParallelScheduler(
                tasks_to_schedule,
                self.current_date,
                resource_config=self.resource_config,
                completed_task_ids=done_without_dates,
                config=self.scheduler_config,
                verbosity=self.verbosity,
            )
            scheduled_tasks = scheduler.schedule()

            # Convert scheduler results to our format
            self._convert_scheduler_results(scheduled_tasks, result)

            # Check for deadline violations
            self._check_deadline_violations(result, entities_by_id)

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

    def _build_mermaid_frontmatter(self, compact: bool, theme_css: str) -> list[str]:
        """Build YAML frontmatter for Mermaid chart."""
        if not (compact or theme_css):
            return []

        lines = ["---"]
        if compact:
            lines.append("displayMode: compact")
        if theme_css:
            lines.append("config:")
            lines.append('    themeCSS: "')
            for css_line in theme_css.split("\n"):
                if css_line.strip():
                    lines.append(f"        {css_line}  \\n")
            lines.append('    "')
        lines.append("---")
        return lines

    def _build_mermaid_header(
        self, title: str, tick_interval: str | None, axis_format: str | None
    ) -> list[str]:
        """Build Mermaid chart header."""
        current_date_str = self.current_date.strftime("%Y-%m-%d")

        lines = [
            "gantt",
            f"    title {title}",
            "    dateFormat YYYY-MM-DD",
        ]

        if tick_interval:
            lines.append(f"    tickInterval {tick_interval}")

        if axis_format:
            lines.append(f"    axisFormat {axis_format}")

        lines.append(f"    todayMarker {current_date_str}")
        return lines

    def _group_tasks_by_type(
        self, result: ScheduleResult, entities_by_id: dict[str, Entity]
    ) -> dict[str, list[ScheduledTask]]:
        """Group tasks by entity type."""
        tasks_by_type: dict[str, list[ScheduledTask]] = {}

        for task in result.tasks:
            entity = entities_by_id[task.entity_id]
            entity_type = entity.type
            if entity_type not in tasks_by_type:
                tasks_by_type[entity_type] = []
            tasks_by_type[entity_type].append(task)

        return tasks_by_type

    def _group_tasks_by_resource(self, result: ScheduleResult) -> dict[str, list[ScheduledTask]]:
        """Group tasks by resource."""
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

        return tasks_by_resource

    def _add_tasks_by_type(
        self,
        lines: list[str],
        result: ScheduleResult,
        entities_by_id: dict[str, Entity],
        markdown_base_url: str | None,
        anchor_fn: AnchorFunction | None,
    ) -> None:
        """Add tasks grouped by type to Mermaid lines."""
        tasks_by_type = self._group_tasks_by_type(result, entities_by_id)

        type_order = {"capability": 0, "user_story": 1, "outcome": 2}
        sorted_types = sorted(tasks_by_type.keys(), key=lambda t: type_order.get(t, 99))

        for entity_type in sorted_types:
            section_name = entity_type.replace("_", " ").title()
            lines.append(f"    section {section_name}")

            tasks = tasks_by_type[entity_type]
            for task in tasks:
                self._add_task_to_mermaid(lines, task, entities_by_id, markdown_base_url, anchor_fn)

    def _add_tasks_by_resource(
        self,
        lines: list[str],
        result: ScheduleResult,
        entities_by_id: dict[str, Entity],
        markdown_base_url: str | None,
        anchor_fn: AnchorFunction | None,
    ) -> None:
        """Add tasks grouped by resource to Mermaid lines."""
        tasks_by_resource = self._group_tasks_by_resource(result)

        sorted_resources = sorted(tasks_by_resource.keys())
        if "unassigned" in sorted_resources:
            sorted_resources.remove("unassigned")
            sorted_resources.append("unassigned")

        for resource in sorted_resources:
            lines.append(f"    section {resource}")

            tasks = tasks_by_resource[resource]
            for task in tasks:
                self._add_task_to_mermaid(lines, task, entities_by_id, markdown_base_url, anchor_fn)

    def generate_mermaid(  # noqa: PLR0913 - Gantt chart generation needs many formatting options
        self,
        result: ScheduleResult,
        *,
        title: str = "Project Schedule",
        group_by: str = "type",
        tick_interval: str | None = None,
        axis_format: str | None = None,
        vertical_dividers: str | None = None,
        compact: bool = False,
        markdown_base_url: str | None = None,
        anchor_fn: AnchorFunction | None = None,
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
            markdown_base_url: Base URL for markdown links (e.g., "./feature_map.md"). If provided,
                              tasks will be clickable and link to their corresponding markdown headers.
            anchor_fn: Function to generate anchors for markdown links. Required if markdown_base_url is provided.

        Returns:
            Mermaid gantt chart syntax as a string
        """
        entities_by_id = {e.id: e for e in self.feature_map.entities}
        theme_css = self._generate_theme_css(result.tasks, entities_by_id)

        lines: list[str] = []

        # Add YAML frontmatter for compact mode and/or themeCSS
        lines.extend(self._build_mermaid_frontmatter(compact, theme_css))

        # Add header
        lines.extend(self._build_mermaid_header(title, tick_interval, axis_format))
        lines.append("")

        # Add vertical dividers if requested
        if vertical_dividers and result.tasks:
            divider_lines = self._generate_vertical_dividers(result.tasks, vertical_dividers)
            lines.extend(divider_lines)
            if divider_lines:
                lines.append("")

        # Add tasks grouped by type or resource
        if group_by == "type":
            self._add_tasks_by_type(lines, result, entities_by_id, markdown_base_url, anchor_fn)
        elif group_by == "resource":
            self._add_tasks_by_resource(lines, result, entities_by_id, markdown_base_url, anchor_fn)

        return "\n".join(lines)

    def _generate_theme_css(
        self, tasks: list[ScheduledTask], entities_by_id: dict[str, Entity]
    ) -> str:
        """Generate themeCSS block for custom task styling.

        Args:
            tasks: List of scheduled tasks
            entities_by_id: Map of entity IDs to entities

        Returns:
            CSS string for themeCSS configuration, or empty string if no custom styles
        """
        css_rules: list[str] = []

        for task in tasks:
            entity = entities_by_id.get(task.entity_id)
            if not entity:
                continue

            # Apply task styling
            task_style = apply_task_styles(entity, self.styling_context)

            # Build CSS rule for this task if it has custom colors
            css_properties: list[str] = []

            if "fill_color" in task_style:
                css_properties.append(f"fill: {task_style['fill_color']}")

            if "stroke_color" in task_style:
                css_properties.append(f"stroke: {task_style['stroke_color']}")

            if "text_color" in task_style:
                css_properties.append(f"color: {task_style['text_color']}")

            if css_properties:
                css_rule = f"#{task.entity_id} {{ {'; '.join(css_properties)} }}"
                css_rules.append(css_rule)

        return "\n".join(css_rules)

    def _generate_quarter_dividers(self, min_date: date, max_date: date) -> list[str]:
        """Generate quarterly vertical dividers."""
        dividers: list[str] = []
        current = date(min_date.year, 1, 1)

        while current <= max_date:
            if current >= min_date:
                quarter = (current.month - 1) // 3 + 1
                label = f"Q{quarter} {current.year}"
                vert_id = f"q{quarter}_{current.year}"
                dividers.append(
                    f"    {label} : vert, {vert_id}, {current.strftime('%Y-%m-%d')}, 0d"
                )
            if current.month == OCTOBER:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 3, 1)

        return dividers

    def _generate_halfyear_dividers(self, min_date: date, max_date: date) -> list[str]:
        """Generate half-year vertical dividers."""
        dividers: list[str] = []
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

        return dividers

    def _generate_year_dividers(self, min_date: date, max_date: date) -> list[str]:
        """Generate yearly vertical dividers."""
        dividers: list[str] = []
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

        if divider_type == "quarter":
            return self._generate_quarter_dividers(min_date, max_date)
        if divider_type == "halfyear":
            return self._generate_halfyear_dividers(min_date, max_date)
        if divider_type == "year":
            return self._generate_year_dividers(min_date, max_date)

        return []

    def _get_task_deadline(self, gantt_meta: GanttMetadata) -> date | None:
        """Get task deadline from metadata."""
        if gantt_meta.end_before is not None:
            return self._parse_date(gantt_meta.end_before)
        if gantt_meta.timeframe is not None:
            _, deadline_date = parse_timeframe(gantt_meta.timeframe)
            return deadline_date
        return None

    def _add_deadline_milestone(
        self, lines: list[str], entity: Entity, task: ScheduledTask, deadline_date: date
    ) -> None:
        """Add deadline milestone if task is late."""
        if task.end_date > deadline_date:
            milestone_label = f"{entity.name} Deadline"
            deadline_str = deadline_date.strftime("%Y-%m-%d")
            lines.append(
                f"    {milestone_label} :milestone, crit, {task.entity_id}_deadline, "
                f"{deadline_str}, 0d"
            )

    def _build_task_label(self, entity: Entity, task: ScheduledTask) -> str:
        """Build task label with resource information."""
        label = entity.name
        is_unassigned = task.resources == ["unassigned"] or not task.resources

        if task.resources:
            if is_unassigned:
                label += " (unassigned)"
            else:
                label += f" ({', '.join(task.resources)})"

        return label

    def _get_task_tags(
        self,
        gantt_meta: GanttMetadata,
        task: ScheduledTask,
        task_style: dict[str, Any],
        is_late: bool,
    ) -> list[str]:
        """Get task tags from style or default logic."""
        if "tags" in task_style:
            return task_style["tags"]

        # Default tag behavior (backward compatibility)
        tags: list[str] = []
        if gantt_meta.status == "done":
            tags.append("done")
        elif is_late:
            tags.append("crit")
        elif task.resources == ["unassigned"] or not task.resources:
            tags.append("active")

        return tags

    def _add_task_to_mermaid(
        self,
        lines: list[str],
        task: ScheduledTask,
        entities_by_id: dict[str, Entity],
        markdown_base_url: str | None = None,
        anchor_fn: AnchorFunction | None = None,
    ) -> None:
        """Add a task to the Mermaid lines list.

        Args:
            lines: The list of Mermaid lines to append to
            task: The scheduled task to add
            entities_by_id: Map of entity IDs to entities
            markdown_base_url: Base URL for markdown links. If provided, a click directive
                              will be added to make the task clickable.
            anchor_fn: Function to generate anchors for markdown links. Required if markdown_base_url is provided.
        """
        entity = entities_by_id[task.entity_id]
        gantt_meta = self._get_gantt_meta(entity)

        # Check if task has a deadline and if it's violated
        deadline_date = self._get_task_deadline(gantt_meta)
        is_late = deadline_date is not None and task.end_date > deadline_date

        # Create milestone if task is late
        if deadline_date is not None and is_late:
            self._add_deadline_milestone(lines, entity, task, deadline_date)

        # Build task label with resources
        label = self._build_task_label(entity, task)

        # Apply task styling and get tags
        task_style = apply_task_styles(entity, self.styling_context)
        tags = self._get_task_tags(gantt_meta, task, task_style, is_late)

        tags_str = ", ".join(tags) + ", " if tags else ""
        start_str = task.start_date.strftime("%Y-%m-%d")
        # Calculate duration from actual date range (accounts for DNS gaps)
        calendar_duration = (task.end_date - task.start_date).days
        duration_str = f"{calendar_duration}d"

        lines.append(f"    {label} :{tags_str}{task.entity_id}, {start_str}, {duration_str}")

        # Add click directive if markdown_base_url is provided
        if markdown_base_url and anchor_fn:
            anchor = anchor_fn(task.entity_id, entity.name)
            url = f"{markdown_base_url}#{anchor}"
            lines.append(f'    click {task.entity_id} href "{url}"')
