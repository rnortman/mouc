"""Example styling module that displays schedule annotations in markdown.

Usage:
    mouc doc --schedule --style-file examples/schedule_markdown_style.py

This example demonstrates how to inject computed schedule information
into markdown output by adding fields to the display metadata.
"""

from typing import Any

from mouc.styling import Entity, StylingContext, style_metadata


@style_metadata()
def inject_schedule_to_metadata(
    entity: Entity, context: StylingContext, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Inject schedule annotations into markdown metadata display.

    This styling function returns a new metadata dict with computed schedule
    information added. The input metadata dict is not mutated.
    """
    schedule = entity.annotations.get("schedule")
    if not schedule:
        return metadata

    # Copy and add computed fields
    result = metadata.copy()

    # Add estimated dates if they exist
    if schedule.estimated_start:
        result["⏱️ Estimated Start"] = str(schedule.estimated_start)

    if schedule.estimated_end:
        result["⏱️ Estimated End"] = str(schedule.estimated_end)

    # Add computed deadline if it exists
    if schedule.computed_deadline:
        result["📅 Computed Deadline"] = str(schedule.computed_deadline)

    # Add deadline violation warning
    if schedule.deadline_violated:
        result["⚠️ Status"] = "DEADLINE VIOLATED"

    # Show resource assignments
    if schedule.resource_assignments:
        resources_str = ", ".join(
            f"{name}:{alloc}" for name, alloc in schedule.resource_assignments
        )
        result["👥 Assigned Resources"] = resources_str

        # Indicate if resources were auto-assigned
        if schedule.resources_were_computed:
            result["👥 Assigned Resources"] += " (auto-assigned)"

    # Indicate if this was a fixed date task
    if schedule.was_fixed:
        result["📌 Schedule Type"] = "Fixed dates (not computed)"
    else:
        result["📌 Schedule Type"] = "Computed by scheduler"

    # Return new metadata dict with schedule info added
    return result
