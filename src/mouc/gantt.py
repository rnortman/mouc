"""Gantt chart scheduling for Mouc - data preparation and rendering."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .backends.base import AnchorFunction
from .builtin_gantt import register_builtin_organization
from .scheduler import (
    ScheduleAnnotations,
    SchedulingConfig,
    SchedulingService,
    TimeframeConstraintMode,
    parse_timeframe,
)
from .styling import (
    StylingContext,
    apply_entity_filters,
    apply_task_grouping,
    apply_task_sorting,
    apply_task_styles,
    create_styling_context,
)
from .unified_config import GanttConfig, load_unified_config

if TYPE_CHECKING:
    from .models import Entity, FeatureMap
    from .resources import DNSPeriod, ResourceConfig

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
    priority: int | None = None  # Urgency indicator (0-100), uses config default if not set


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
        global_dns_periods: list[DNSPeriod] | None = None,
        gantt_config: GanttConfig | None = None,
        style_tags: set[str] | None = None,
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
            global_dns_periods: Optional global DNS periods that apply to all resources
            gantt_config: Optional gantt configuration for grouping/sorting
            style_tags: Optional set of active style tags for filtering styling functions
        """
        self.feature_map = feature_map
        self.current_date = current_date or date.today()  # noqa: DTZ011

        # Load configs if path provided
        if resource_config_path is not None:
            # Load from unified config
            with suppress(FileNotFoundError):
                unified = load_unified_config(resource_config_path)
                if resource_config is None:
                    resource_config = unified.resources
                if scheduler_config is None:
                    scheduler_config = unified.scheduler
                if global_dns_periods is None:
                    global_dns_periods = unified.global_dns_periods
                if gantt_config is None:
                    gantt_config = unified.gantt

        self.resource_config = resource_config
        self.scheduler_config = scheduler_config
        self.global_dns_periods = global_dns_periods or []
        self.gantt_config = gantt_config or GanttConfig()

        # Calculate start_date if not provided
        if start_date is None:
            self.start_date = self._calculate_chart_start_date()
        else:
            self.start_date = start_date

        # Register built-in organization functions based on config
        register_builtin_organization(
            group_by=self.gantt_config.group_by,
            sort_by=self.gantt_config.sort_by,
        )

        # Create styling context for task styling (with config access)
        config_dict: dict[str, object] = {"gantt": self.gantt_config.model_dump()}
        if self.scheduler_config:
            config_dict["scheduler"] = self.scheduler_config.model_dump()
        self.styling_context: StylingContext = create_styling_context(
            feature_map, output_format="gantt", config=config_dict, style_tags=style_tags
        )

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
        # Delegate to SchedulingService for actual scheduling
        service = SchedulingService(
            feature_map=self.feature_map,
            current_date=self.current_date,
            resource_config=self.resource_config,
            config=self.scheduler_config,
            global_dns_periods=self.global_dns_periods,
        )
        scheduling_result = service.schedule()

        # Convert to gantt ScheduleResult format
        result = ScheduleResult()
        result.warnings.extend(scheduling_result.warnings)

        for scheduled_task in scheduling_result.scheduled_tasks:
            result.tasks.append(
                ScheduledTask(
                    entity_id=scheduled_task.task_id,
                    start_date=scheduled_task.start_date,
                    end_date=scheduled_task.end_date,
                    duration_days=scheduled_task.duration_days,
                    resources=scheduled_task.resources,
                )
            )

        # Store annotations for _populate_schedule_annotations
        self._scheduling_annotations = scheduling_result.annotations

        return result

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
        # Always include frontmatter for topAxis
        lines = ["---"]
        if compact:
            lines.append("displayMode: compact")

        # Build config section for topAxis and/or themeCSS
        lines.append("config:")
        lines.append("    gantt:")
        lines.append("        topAxis: true")

        if theme_css:
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

    def generate_mermaid(  # noqa: PLR0913 - Gantt chart generation needs many formatting options
        self,
        result: ScheduleResult,
        *,
        title: str = "Project Schedule",
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

        # Populate entity annotations with schedule information for use in organization functions
        self._populate_schedule_annotations(result.tasks, entities_by_id)

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

        # Apply organization pipeline (group → sort)
        organized_tasks = self._organize_tasks(result.tasks)

        # Render organized tasks
        self._render_organized_tasks(
            lines, organized_tasks, entities_by_id, markdown_base_url, anchor_fn
        )

        return "\n".join(lines)

    def _populate_schedule_annotations(
        self, tasks: list[ScheduledTask], entities_by_id: dict[str, Entity]
    ) -> None:
        """Populate entity annotations with schedule information.

        Uses full annotations from SchedulingService (computed_deadline, computed_priority, etc.)
        which are stored during schedule() call.

        Args:
            tasks: List of scheduled tasks (used for entity ID iteration)
            entities_by_id: Mapping of entity IDs to entity objects
        """
        # Use full annotations from SchedulingService if available
        if hasattr(self, "_scheduling_annotations") and self._scheduling_annotations:
            for entity_id, annotation in self._scheduling_annotations.items():
                entity = entities_by_id.get(entity_id)
                if entity:
                    entity.annotations["schedule"] = annotation
        else:
            # Fallback for edge cases (shouldn't happen in normal use)
            for task in tasks:
                entity = entities_by_id.get(task.entity_id)
                if entity:
                    entity.annotations["schedule"] = ScheduleAnnotations(
                        estimated_start=task.start_date,
                        estimated_end=task.end_date,
                        computed_deadline=None,
                        computed_priority=None,
                        deadline_violated=False,
                        resource_assignments=[(r, 1.0) for r in task.resources],
                        resources_were_computed=False,
                        was_fixed=False,
                    )

    def _organize_tasks(self, tasks: list[ScheduledTask]) -> dict[str | None, list[ScheduledTask]]:
        """Apply organization pipeline: grouping → sorting.

        Organization functions operate on Entity objects (with schedule annotations populated).
        This method converts between ScheduledTask and Entity as needed.

        Args:
            tasks: List of scheduled tasks to organize

        Returns:
            Dict mapping section names (or None) to sorted task lists
        """
        # Build mapping from entity_id to ScheduledTask for conversion back
        task_by_entity_id = {task.entity_id: task for task in tasks}

        # Convert to entities for organization
        entities = [self.feature_map.get_entity_by_id(task.entity_id) for task in tasks]
        entities = [e for e in entities if e is not None]  # Filter out None

        # Apply entity filters
        filtered_entities = apply_entity_filters(entities, self.styling_context)

        # Step 1: Apply grouping (highest-priority function wins)
        grouped_entities = apply_task_grouping(filtered_entities, self.styling_context)

        # Step 2: Apply sorting within each group (highest-priority function wins)
        sorted_groups: dict[str | None, list[ScheduledTask]] = {}
        for group_key, group_entities in grouped_entities.items():
            sorted_entities = apply_task_sorting(group_entities, self.styling_context)
            # Convert back to ScheduledTask for rendering
            sorted_tasks = [
                task_by_entity_id[e.id] for e in sorted_entities if e.id in task_by_entity_id
            ]
            sorted_groups[group_key] = sorted_tasks

        return sorted_groups

    def _render_organized_tasks(
        self,
        lines: list[str],
        organized_tasks: dict[str | None, list[ScheduledTask]],
        entities_by_id: dict[str, Entity],
        markdown_base_url: str | None,
        anchor_fn: AnchorFunction | None,
    ) -> None:
        """Render organized task structure to Mermaid lines.

        Args:
            lines: List of Mermaid lines to append to
            organized_tasks: Dict mapping section names to task lists
            entities_by_id: Map of entity IDs to entities
            markdown_base_url: Base URL for markdown links
            anchor_fn: Function to generate anchors
        """
        for group_key, tasks in organized_tasks.items():
            # Add section header if group has a name
            if group_key is not None:
                lines.append(f"    section {group_key}")

            # Add tasks
            for task in tasks:
                self._add_task_to_mermaid(lines, task, entities_by_id, markdown_base_url, anchor_fn)

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
        # Only use timeframe as deadline if config allows end constraints
        if gantt_meta.timeframe is not None:
            tf_mode = (
                self.scheduler_config.auto_constraint_from_timeframe
                if self.scheduler_config
                else TimeframeConstraintMode.BOTH
            )
            if tf_mode in (TimeframeConstraintMode.BOTH, TimeframeConstraintMode.END):
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

        start_str = task.start_date.strftime("%Y-%m-%d")

        # Check if this is a milestone (0d task)
        is_milestone = task.duration_days == 0 or (
            task.start_date == task.end_date and not task.resources
        )
        if is_milestone:
            # Render as Mermaid milestone
            lines.append(f"    {label} :milestone, {task.entity_id}, {start_str}, 0d")
            # Add click directive if markdown_base_url is provided
            if markdown_base_url and anchor_fn:
                anchor = anchor_fn(task.entity_id, entity.name)
                url = f"{markdown_base_url}#{anchor}"
                lines.append(f'    click {task.entity_id} href "{url}"')
            return

        tags_str = ", ".join(tags) + ", " if tags else ""
        # Calculate duration from actual date range (accounts for DNS gaps)
        calendar_duration = (task.end_date - task.start_date).days
        duration_str = f"{calendar_duration}d"

        lines.append(f"    {label} :{tags_str}{task.entity_id}, {start_str}, {duration_str}")

        # Add click directive if markdown_base_url is provided
        if markdown_base_url and anchor_fn:
            anchor = anchor_fn(task.entity_id, entity.name)
            url = f"{markdown_base_url}#{anchor}"
            lines.append(f'    click {task.entity_id} href "{url}"')
