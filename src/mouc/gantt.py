"""Gantt chart scheduling for Mouc."""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .models import Entity, FeatureMap


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
    """Resource-aware deadline-driven scheduler for Mouc entities."""

    def __init__(
        self,
        feature_map: FeatureMap,
        start_date: date | None = None,
        current_date: date | None = None,
    ):
        """Initialize scheduler with a feature map and optional dates.

        Args:
            feature_map: The feature map to schedule
            start_date: Chart start date (left edge of visualization).
                       If None, defaults to min(first fixed task date, current_date)
            current_date: Current/as-of date for scheduling.
                         If None, defaults to today
        """
        self.feature_map = feature_map
        self.current_date = current_date or date.today()  # noqa: DTZ011

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

        # Step 1: Calculate topological order (validate no cycles)
        try:
            topo_order = self._topological_sort()
        except ValueError as e:
            result.warnings.append(str(e))
            return result

        # Step 2: Handle fixed-schedule tasks (those with start_date and/or end_date)
        scheduled_dates: dict[str, tuple[date, date]] = {}
        fixed_tasks = self._schedule_fixed_tasks(entities_by_id, result)
        scheduled_dates.update(fixed_tasks)

        # Step 3: Backward pass - propagate deadlines up dependency chains
        latest_dates = self._calculate_latest_dates(entities_by_id, topo_order)

        # Step 4: Calculate urgency scores
        urgency_scores = self._calculate_urgency(entities_by_id, latest_dates, topo_order)

        # Step 5: Forward pass with resource tracking (skip fixed tasks)
        resource_availability: dict[str, date] = {}

        # Priority queue: (urgency_score, entity_id)
        # Using negative urgency for max-heap behavior
        ready_queue: list[tuple[float, str]] = []
        dependencies_remaining = {eid: len(entities_by_id[eid].requires) for eid in entities_by_id}

        # Initialize queue with entities that have no dependencies (skip fixed tasks)
        # Also update dependency counts for tasks depending on fixed tasks
        for entity_id in entities_by_id:
            if entity_id in scheduled_dates:
                # Already scheduled as fixed task, update dependents
                entity = entities_by_id[entity_id]
                for dependent_id in entity.enables:
                    dependencies_remaining[dependent_id] -= 1
                    if dependencies_remaining[dependent_id] == 0:
                        urgency = urgency_scores.get(dependent_id, 0.0)
                        heapq.heappush(ready_queue, (-urgency, dependent_id))
                continue
            if dependencies_remaining[entity_id] == 0:
                urgency = urgency_scores.get(entity_id, 0.0)
                heapq.heappush(ready_queue, (-urgency, entity_id))

        while ready_queue:
            _, entity_id = heapq.heappop(ready_queue)

            # Skip if already scheduled (as a fixed task)
            if entity_id in scheduled_dates:
                continue

            entity = entities_by_id[entity_id]

            # Calculate when this entity can start
            # Must be after: current_date, all dependencies, all resources available, start_after constraint
            earliest_start: date = self.current_date

            # Check dependency completion
            for dep_id in entity.requires:
                if dep_id in scheduled_dates:
                    dep_end = scheduled_dates[dep_id][1]
                    earliest_start = max(earliest_start, dep_end + timedelta(days=1))

            # Check resource availability
            gantt_meta = self._get_gantt_meta(entity)
            resources = self._parse_resources(gantt_meta.resources)
            for resource_name, _ in resources:
                if resource_name in resource_availability:
                    earliest_start = max(earliest_start, resource_availability[resource_name])

            # Check start_after constraint (apply max with current_date)
            # Explicit takes precedence over timeframe
            if gantt_meta.start_after:
                start_after = self._parse_date(gantt_meta.start_after)
                if start_after:
                    # Use max of specified start_after and current_date (can't start in past)
                    earliest_start = max(earliest_start, start_after, self.current_date)
            elif gantt_meta.timeframe:
                # Apply timeframe start if no explicit start_after
                timeframe_start, _ = parse_timeframe(gantt_meta.timeframe)
                if timeframe_start:
                    # Use max of timeframe start and current_date (can't start in past)
                    earliest_start = max(earliest_start, timeframe_start, self.current_date)

            # Calculate duration and end date
            duration = self._calculate_duration(entity)
            end_date = earliest_start + timedelta(days=duration)

            # Update resource availability
            for resource_name, _ in resources:
                resource_availability[resource_name] = end_date + timedelta(days=1)

            # Record schedule
            scheduled_dates[entity_id] = (earliest_start, end_date)
            result.tasks.append(
                ScheduledTask(
                    entity_id=entity_id,
                    start_date=earliest_start,
                    end_date=end_date,
                    duration_days=duration,
                    resources=[r for r, _ in resources],
                )
            )

            # Check for deadline violations
            if entity_id in latest_dates:
                required_end = latest_dates[entity_id]
                if end_date > required_end:
                    days_late = (end_date - required_end).days
                    result.warnings.append(
                        f"Entity '{entity_id}' finishes {days_late} days after required date "
                        f"({end_date} vs {required_end})"
                    )

            # Update queue with newly ready entities
            for dependent_id in entity.enables:
                dependencies_remaining[dependent_id] -= 1
                if dependencies_remaining[dependent_id] == 0:
                    urgency = urgency_scores.get(dependent_id, 0.0)
                    heapq.heappush(ready_queue, (-urgency, dependent_id))

        return result

    def _schedule_fixed_tasks(
        self, entities_by_id: dict[str, Entity], result: ScheduleResult
    ) -> dict[str, tuple[date, date]]:
        """Schedule tasks with fixed start_date and/or end_date.

        Returns dict of entity_id -> (start_date, end_date) for fixed tasks.
        """
        fixed_schedules: dict[str, tuple[date, date]] = {}

        for entity_id, entity in entities_by_id.items():
            gantt_meta = self._get_gantt_meta(entity)

            # Skip if neither start_date nor end_date is specified
            if gantt_meta.start_date is None and gantt_meta.end_date is None:
                continue

            # Parse the dates
            start = self._parse_date(gantt_meta.start_date) if gantt_meta.start_date else None
            end = self._parse_date(gantt_meta.end_date) if gantt_meta.end_date else None

            # If both are specified, use them
            if start is not None and end is not None:
                duration = (end - start).days
                fixed_schedules[entity_id] = (start, end)
                resources = self._parse_resources(gantt_meta.resources)
                result.tasks.append(
                    ScheduledTask(
                        entity_id=entity_id,
                        start_date=start,
                        end_date=end,
                        duration_days=float(duration),
                        resources=[r for r, _ in resources],
                    )
                )
            # If only start_date is specified, compute end_date from effort
            elif start is not None:
                duration = self._calculate_duration(entity)
                end = start + timedelta(days=duration)
                fixed_schedules[entity_id] = (start, end)
                resources = self._parse_resources(gantt_meta.resources)
                result.tasks.append(
                    ScheduledTask(
                        entity_id=entity_id,
                        start_date=start,
                        end_date=end,
                        duration_days=duration,
                        resources=[r for r, _ in resources],
                    )
                )
            # If only end_date is specified, compute start_date from effort
            elif end is not None:
                duration = self._calculate_duration(entity)
                start = end - timedelta(days=duration)
                fixed_schedules[entity_id] = (start, end)
                resources = self._parse_resources(gantt_meta.resources)
                result.tasks.append(
                    ScheduledTask(
                        entity_id=entity_id,
                        start_date=start,
                        end_date=end,
                        duration_days=duration,
                        resources=[r for r, _ in resources],
                    )
                )

        return fixed_schedules

    def _topological_sort(self) -> list[str]:
        """Return entities in topological order (dependencies first)."""
        entities_by_id = {e.id: e for e in self.feature_map.entities}
        in_degree = {eid: len(entities_by_id[eid].requires) for eid in entities_by_id}
        queue = [eid for eid, degree in in_degree.items() if degree == 0]
        result: list[str] = []

        while queue:
            entity_id = queue.pop(0)
            result.append(entity_id)  # pyright: ignore[reportUnknownMemberType]

            entity = entities_by_id[entity_id]
            for dependent_id in entity.enables:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(result) != len(entities_by_id):  # pyright: ignore[reportUnknownArgumentType]
            raise ValueError("Circular dependency detected in feature map")

        return result

    def _calculate_latest_dates(
        self, entities_by_id: dict[str, Entity], topo_order: list[str]
    ) -> dict[str, date]:
        """Backward pass: propagate deadlines up the dependency chain."""
        latest: dict[str, date] = {}

        # Initialize with explicit deadlines (explicit takes precedence over timeframe)
        for entity_id, entity in entities_by_id.items():
            gantt_meta = self._get_gantt_meta(entity)
            if gantt_meta.end_before:
                end_before = self._parse_date(gantt_meta.end_before)
                if end_before:
                    latest[entity_id] = end_before
            elif gantt_meta.timeframe:
                # Apply timeframe end as deadline if no explicit end_before
                _, timeframe_end = parse_timeframe(gantt_meta.timeframe)
                if timeframe_end:
                    latest[entity_id] = timeframe_end

        # Propagate backwards through dependencies (reverse topological order)
        for entity_id in reversed(topo_order):
            if entity_id not in latest:
                continue

            entity = entities_by_id[entity_id]
            entity_deadline = latest[entity_id]
            entity_duration = self._calculate_duration(entity)

            # Propagate to dependencies
            for dep_id in entity.requires:
                # Dependency must finish at least entity_duration + 1 day before this entity's deadline
                dep_deadline = entity_deadline - timedelta(days=entity_duration + 1)
                if dep_id in latest:
                    latest[dep_id] = min(latest[dep_id], dep_deadline)
                else:
                    latest[dep_id] = dep_deadline

        return latest

    def _calculate_urgency(
        self,
        entities_by_id: dict[str, Entity],
        latest_dates: dict[str, date],
        topo_order: list[str],
    ) -> dict[str, float]:
        """Calculate urgency scores based on deadlines and dependent count."""
        urgency: dict[str, float] = {}

        for entity_id in entities_by_id:
            score = 0.0

            # Factor 1: Deadline urgency (higher score = more urgent)
            if entity_id in latest_dates:
                days_until_deadline = (latest_dates[entity_id] - self.current_date).days
                # More urgent if deadline is sooner (inverse relationship)
                if days_until_deadline > 0:
                    score += 1000.0 / days_until_deadline
                else:
                    score += 10000.0  # Already late!

            # Factor 2: Number of dependents (more dependents = more critical)
            entity = entities_by_id[entity_id]
            score += len(entity.enables) * 10.0

            urgency[entity_id] = score

        return urgency

    def _calculate_duration(self, entity: Entity) -> float:
        """Calculate duration in days from effort and resource allocation."""
        gantt_meta = self._get_gantt_meta(entity)
        effort_days = self._parse_effort(gantt_meta.effort)
        resources = self._parse_resources(gantt_meta.resources)

        # Total capacity = sum of resource allocations
        total_capacity = sum(capacity for _, capacity in resources)
        if total_capacity == 0:
            total_capacity = 1.0

        return effort_days / total_capacity

    def _parse_effort(self, effort_str: str) -> float:
        """Parse effort string to days.

        Supported formats:
        - "5d" = 5 days
        - "2w" = 10 working days (2 weeks * 5 days)
        - "1.5m" = 30 working days (1.5 months * 20 days)
        """
        effort_str = effort_str.strip().lower()
        match = re.match(r"^([\d.]+)([dwm])$", effort_str)
        if not match:
            return 5.0  # Default to 1 week

        value, unit = match.groups()
        num = float(value)

        if unit == "d":
            return num
        if unit == "w":
            return num * 5  # 5 working days per week
        if unit == "m":
            return num * 20  # ~20 working days per month
        return 5.0

    def _parse_resources(
        self, resources_raw: list[str | tuple[str, float]]
    ) -> list[tuple[str, float]]:
        """Parse resources list to (name, capacity) tuples.

        Supported formats:
        - ["alice"] -> [("alice", 1.0)]
        - ["alice", "bob"] -> [("alice", 1.0), ("bob", 1.0)]
        - ["alice:0.5"] -> [("alice", 0.5)]
        - ["alice:1.0", "bob:0.5"] -> [("alice", 1.0), ("bob", 0.5)]
        - [("alice", 0.5)] -> [("alice", 0.5)]
        """
        if not resources_raw:
            return [("unassigned", 1.0)]

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
                result.append((str(resource_str).strip(), 1.0))

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

    def generate_mermaid(
        self, result: ScheduleResult, title: str = "Project Schedule", group_by: str = "type"
    ) -> str:
        """Generate Mermaid gantt chart from schedule result.

        Args:
            result: The scheduling result containing tasks
            title: Chart title (default: "Project Schedule")
            group_by: How to group tasks - "type" (entity type) or "resource" (person/team)

        Returns:
            Mermaid gantt chart syntax as a string
        """
        # Set todayMarker to current_date so the red line appears at the right position
        current_date_str = self.current_date.strftime("%Y-%m-%d")

        lines = [
            "gantt",
            f"    title {title}",
            "    dateFormat YYYY-MM-DD",
            f"    todayMarker {current_date_str}",
            "",
        ]

        entities_by_id = {e.id: e for e in self.feature_map.entities}

        if group_by == "type":
            # Group by entity type (original behavior)
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
                key=lambda t: type_order.get(t, 99),  # noqa: PLR2004
            )

            for entity_type in sorted_types:
                section_name = entity_type.replace("_", " ").title()
                lines.append(f"    section {section_name}")

                tasks = tasks_by_type[entity_type]
                for task in tasks:
                    self._add_task_to_mermaid(lines, task, entities_by_id)

        elif group_by == "resource":
            # Group by resource (tasks with multiple resources appear in each resource's section)
            tasks_by_resource: dict[str, list[ScheduledTask]] = {}

            for task in result.tasks:
                for resource in task.resources:
                    if resource not in tasks_by_resource:
                        tasks_by_resource[resource] = []
                    tasks_by_resource[resource].append(task)

            # Sort resources alphabetically, but put "unassigned" last
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
