"""Input validation and entity-to-task conversion."""

import re
from datetime import date
from typing import TYPE_CHECKING

from mouc.logger import get_logger
from mouc.resources import UNASSIGNED_RESOURCE

from .core import Task
from .timeframes import parse_timeframe

logger = get_logger()

if TYPE_CHECKING:
    from mouc.models import Entity, FeatureMap
    from mouc.resources import ResourceConfig


class SchedulerInputValidator:
    """Extracts and validates scheduling inputs from entity metadata.

    This ensures consistent input extraction for all scheduling contexts
    (Gantt, schedule command, etc.).
    """

    def __init__(self, resource_config: "ResourceConfig | None" = None):
        """Initialize validator with optional resource configuration.

        Args:
            resource_config: Optional resource configuration for auto-assignment
        """
        self.resource_config = resource_config

    def parse_effort(self, effort_str: str) -> float:
        """Parse effort string to calendar days.

        Supported formats:
        - "5d" = 5 calendar days
        - "2w" = 14 calendar days
        - "1.5m" = 45 calendar days
        - "L" = Large (60 days)
        """
        effort_str = effort_str.strip().lower()
        if effort_str == "l":
            return 60.0

        match = re.match(r"^([\d.]+)([dwm])$", effort_str)
        if not match:
            return 7.0  # Default to 1 week

        value, unit = match.groups()
        num = float(value)

        if unit == "d":
            return num
        if unit == "w":
            return num * 7
        if unit == "m":
            return num * 30
        return 7.0

    def parse_date(self, date_val: str | date | None) -> date | None:
        """Parse a date string or date object."""
        if date_val is None:
            return None
        if isinstance(date_val, date):
            return date_val
        try:
            return date.fromisoformat(date_val.strip())
        except (ValueError, AttributeError):
            return None

    def parse_resources(
        self, resources_raw: list[str | tuple[str, float]] | None
    ) -> tuple[list[tuple[str, float]], str | None, bool]:
        """Parse resources list.

        Returns:
            Tuple of (resource list, resource_spec, is_computed)
            - resource list: concrete assignments
            - resource_spec: spec for auto-assignment (if needed)
            - is_computed: True if resources will be auto-assigned
        """
        if not resources_raw:
            if self.resource_config and self.resource_config.default_resource:
                return ([], self.resource_config.default_resource, True)
            return ([(UNASSIGNED_RESOURCE, 1.0)], None, False)

        # Check for auto-assignment specs when we have resource config
        if self.resource_config and len(resources_raw) == 1 and isinstance(resources_raw[0], str):
            spec_str = resources_raw[0]
            # Only treat as spec if it's a wildcard, contains pipes, starts with !, or is a group
            is_spec = (
                spec_str == "*"
                or "|" in spec_str
                or spec_str.startswith("!")
                or spec_str in self.resource_config.groups
            )
            if is_spec:
                logger.debug(f"      parse_resources: treating '{spec_str}' as spec for expansion")
                return ([], spec_str, True)

        # Parse concrete resources (no resource config or complex allocations)
        result: list[tuple[str, float]] = []
        for resource_str in resources_raw:
            if isinstance(resource_str, tuple):
                name, capacity = resource_str
                result.append((str(name), float(capacity)))
            elif ":" in str(resource_str):
                parts = str(resource_str).split(":", 1)
                name = parts[0].strip()
                try:
                    capacity = float(parts[1].strip())
                except ValueError:
                    capacity = 1.0
                result.append((name, capacity))
            else:
                spec_str = str(resource_str).strip()
                result.append((spec_str, 1.0))

        return (result, None, False)

    def parse_timeframe(self, timeframe_str: str) -> tuple[date | None, date | None]:
        """Parse timeframe string to (start_date, end_date)."""
        return parse_timeframe(timeframe_str)

    def entity_to_task(self, entity: "Entity") -> tuple[Task | None, bool, bool]:
        """Convert entity to scheduler Task.

        Returns:
            Tuple of (Task, is_done_without_dates, resources_were_computed)
            - Task: None if entity is done without dates
            - is_done_without_dates: True if excluded from scheduling
            - resources_were_computed: True if resources will be auto-assigned
        """
        meta = entity.meta
        effort = meta.get("effort", "1w")
        resources_raw = meta.get("resources", [])
        start_date = self.parse_date(meta.get("start_date"))
        end_date = self.parse_date(meta.get("end_date"))
        start_after = self.parse_date(meta.get("start_after"))
        end_before = self.parse_date(meta.get("end_before"))
        timeframe = meta.get("timeframe")
        status = meta.get("status")

        # Check if done without dates
        if status == "done" and start_date is None and end_date is None:
            return (None, True, False)

        # Parse resources
        resources, resource_spec, is_computed = self.parse_resources(resources_raw)

        # Calculate duration
        # If both start_date and end_date are specified, duration is the span between them
        if start_date is not None and end_date is not None:
            duration = float((end_date - start_date).days)
        else:
            effort_days = self.parse_effort(str(effort))
            total_capacity = 1.0 if resource_spec else sum(c for _, c in resources) or 1.0
            duration = effort_days / total_capacity

        # Handle timeframe
        if timeframe and not start_after and not end_before:
            timeframe_start, timeframe_end = self.parse_timeframe(str(timeframe))
            if not start_after:
                start_after = timeframe_start
            if not end_before:
                end_before = timeframe_end

        # Create task
        task = Task(
            id=entity.id,
            duration_days=duration,
            resources=resources,
            dependencies=list(entity.requires),
            start_after=start_after,
            end_before=end_before,
            start_on=start_date,
            end_on=end_date,
            resource_spec=resource_spec,
            meta=entity.meta,
        )

        return (task, False, is_computed)

    def extract_tasks(
        self, feature_map: "FeatureMap"
    ) -> tuple[list[Task], set[str], dict[str, bool]]:
        """Extract all tasks from feature map.

        Returns:
            Tuple of (tasks, done_without_dates, resources_computed_map)
            - tasks: List of Task objects to schedule
            - done_without_dates: Set of entity IDs marked done without dates
            - resources_computed_map: Map of entity_id → resources_were_computed
        """
        tasks: list[Task] = []
        done_without_dates: set[str] = set()
        resources_computed_map: dict[str, bool] = {}

        for entity in feature_map.entities:
            task, is_done, is_computed = self.entity_to_task(entity)
            if is_done:
                done_without_dates.add(entity.id)
            elif task:
                tasks.append(task)
                resources_computed_map[entity.id] = is_computed

        return (tasks, done_without_dates, resources_computed_map)
