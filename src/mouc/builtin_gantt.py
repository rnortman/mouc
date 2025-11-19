"""Built-in gantt organization functions activated by config.

These functions are conditionally registered at initialization time based on
gantt configuration settings. They use priority=5 so user functions (priority=10)
can override them.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

# Import registries directly (not through public API since this is internal)
from . import styling
from .scheduler import parse_timeframe

if TYPE_CHECKING:
    from .gantt import ScheduledTask
    from .styling import StylingContext

# Priority for built-in functions (lower than user functions)
BUILTIN_PRIORITY = 5


# ============================================================================
# Built-in Grouping Functions (Not Decorated - Registered Conditionally)
# ============================================================================


def _builtin_group_by_type(
    tasks: list[ScheduledTask], context: StylingContext
) -> dict[str | None, list[ScheduledTask]]:
    """Group tasks by entity type."""
    # Get entity type order from config (or use default)
    config = getattr(context, "_config", {})
    gantt_config = config.get("gantt", {})
    type_order = gantt_config.get("entity_type_order", ["capability", "user_story", "outcome"])

    # Initialize groups in order
    groups: dict[str, list[ScheduledTask]] = {t: [] for t in type_order}

    # Assign tasks to groups
    for task in tasks:
        entity = context.get_entity(task.entity_id)
        if entity and entity.type in groups:
            groups[entity.type].append(task)

    # Remove empty groups and format names
    result: dict[str | None, list[ScheduledTask]] = {}
    for entity_type, task_list in groups.items():
        if task_list:
            # Format type name for display: "user_story" -> "User Story"
            section_name = entity_type.replace("_", " ").title()
            result[section_name] = task_list

    return result


def _builtin_group_by_resource(
    tasks: list[ScheduledTask], context: StylingContext
) -> dict[str | None, list[ScheduledTask]]:
    """Group tasks by assigned resource."""
    groups: dict[str, list[ScheduledTask]] = {}

    # Assign tasks to resource groups
    for task in tasks:
        if not task.resources:
            # No resources assigned
            if "unassigned" not in groups:
                groups["unassigned"] = []
            groups["unassigned"].append(task)
        else:
            # Add task to each resource it's assigned to
            for resource in task.resources:
                if resource not in groups:
                    groups[resource] = []
                groups[resource].append(task)

    # Sort: alphabetically, with "unassigned" last
    sorted_keys = sorted(k for k in groups if k != "unassigned")
    if "unassigned" in groups:
        sorted_keys.append("unassigned")

    return {k: groups[k] for k in sorted_keys}


def _builtin_group_by_timeframe(
    tasks: list[ScheduledTask], context: StylingContext
) -> dict[str | None, list[ScheduledTask]]:
    """Group tasks by timeframe metadata."""
    groups: dict[str, list[ScheduledTask]] = {}

    # Assign tasks to timeframe groups
    for task in tasks:
        entity = context.get_entity(task.entity_id)
        if entity:
            timeframe = entity.meta.get("timeframe", "Unscheduled")
            if timeframe not in groups:
                groups[timeframe] = []
            groups[timeframe].append(task)

    # Sort timeframes lexically (works reasonably for Q1, Q2, 2025-Q1 formats)
    return dict(sorted(groups.items()))


# ============================================================================
# Built-in Sorting Functions (Not Decorated - Registered Conditionally)
# ============================================================================


def _builtin_sort_by_start(
    tasks: list[ScheduledTask], context: StylingContext
) -> list[ScheduledTask]:
    """Sort tasks by start date ascending."""
    return sorted(tasks, key=lambda t: t.start_date)


def _builtin_sort_by_end(
    tasks: list[ScheduledTask], context: StylingContext
) -> list[ScheduledTask]:
    """Sort tasks by end date ascending."""
    return sorted(tasks, key=lambda t: t.end_date)


def _builtin_sort_by_deadline(
    tasks: list[ScheduledTask], context: StylingContext
) -> list[ScheduledTask]:
    """Sort tasks by deadline (end_before or timeframe end) ascending."""

    def get_deadline(task: ScheduledTask) -> date:
        entity = context.get_entity(task.entity_id)
        if not entity:
            return date.max

        # Try end_before first
        end_before = entity.meta.get("end_before")
        if end_before:
            if isinstance(end_before, date):
                return end_before
            if isinstance(end_before, str):
                try:
                    return date.fromisoformat(end_before)
                except ValueError:
                    pass

        # Try timeframe end
        timeframe = entity.meta.get("timeframe")
        if timeframe and isinstance(timeframe, str):
            try:
                _, end_date = parse_timeframe(timeframe)
                if end_date:
                    return end_date
            except (ValueError, TypeError):
                pass

        # No deadline found
        return date.max

    return sorted(tasks, key=get_deadline)


def _builtin_sort_by_name(
    tasks: list[ScheduledTask], context: StylingContext
) -> list[ScheduledTask]:
    """Sort tasks alphabetically by entity name."""

    def get_name_key(task: ScheduledTask) -> str:
        entity = context.get_entity(task.entity_id)
        return entity.name.lower() if entity else ""

    return sorted(tasks, key=get_name_key)


def _builtin_sort_by_priority(
    tasks: list[ScheduledTask], context: StylingContext
) -> list[ScheduledTask]:
    """Sort tasks by priority metadata descending (higher priority first)."""

    def get_priority(task: ScheduledTask) -> int:
        entity = context.get_entity(task.entity_id)
        if entity:
            return -entity.meta.get("priority", 50)  # Negative for descending sort
        return -50  # Default priority

    return sorted(tasks, key=get_priority)


# ============================================================================
# Registration Helper
# ============================================================================


def register_builtin_organization(group_by: str | None, sort_by: str | None) -> None:
    """Conditionally register built-in organization functions based on config.

    This function is called during GanttScheduler initialization to register
    the appropriate built-in functions based on the gantt configuration.

    Built-in functions are registered at priority=5, so user functions (priority=10)
    can override them.

    Args:
        group_by: Grouping strategy ('type', 'resource', 'timeframe', 'none', or None)
        sort_by: Sorting strategy ('start', 'end', 'deadline', 'name', 'priority', 'yaml_order', or None)
    """
    # Clear any previously registered built-in functions (priority=BUILTIN_PRIORITY, formats=['gantt'])
    # This prevents duplicate registrations when multiple schedulers are created
    styling._group_tasks_funcs[:] = [
        (pri, fmt, func)
        for pri, fmt, func in styling._group_tasks_funcs
        if pri != BUILTIN_PRIORITY or (fmt and "gantt" not in fmt)
    ]
    styling._sort_tasks_funcs[:] = [
        (pri, fmt, func)
        for pri, fmt, func in styling._sort_tasks_funcs
        if pri != BUILTIN_PRIORITY or (fmt and "gantt" not in fmt)
    ]

    # Register grouping function based on group_by config
    if group_by == "type":
        styling._group_tasks_funcs.append((BUILTIN_PRIORITY, ["gantt"], _builtin_group_by_type))
    elif group_by == "resource":
        styling._group_tasks_funcs.append((BUILTIN_PRIORITY, ["gantt"], _builtin_group_by_resource))
    elif group_by == "timeframe":
        styling._group_tasks_funcs.append(
            (BUILTIN_PRIORITY, ["gantt"], _builtin_group_by_timeframe)
        )
    # 'none' or None: no grouping function registered

    # Register sorting function based on sort_by config
    if sort_by == "start":
        styling._sort_tasks_funcs.append((BUILTIN_PRIORITY, ["gantt"], _builtin_sort_by_start))
    elif sort_by == "end":
        styling._sort_tasks_funcs.append((BUILTIN_PRIORITY, ["gantt"], _builtin_sort_by_end))
    elif sort_by == "deadline":
        styling._sort_tasks_funcs.append((BUILTIN_PRIORITY, ["gantt"], _builtin_sort_by_deadline))
    elif sort_by == "name":
        styling._sort_tasks_funcs.append((BUILTIN_PRIORITY, ["gantt"], _builtin_sort_by_name))
    elif sort_by == "priority":
        styling._sort_tasks_funcs.append((BUILTIN_PRIORITY, ["gantt"], _builtin_sort_by_priority))
    # 'yaml_order' or None: no sorting function registered (preserves order)
