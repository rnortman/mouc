"""Example styling module for Mouc graphs and gantt charts.

This file demonstrates how to use the styling system to customize:
- Graph visualization (nodes and edges)
- Gantt chart task appearance
- Markdown output labels

Usage:
    mouc graph feature_map.yaml --style-file examples/style_example.py
    mouc gantt feature_map.yaml --style-file examples/style_example.py
    mouc doc feature_map.yaml --style-file examples/style_example.py
"""

from mouc.styling import (
    EdgeStyle,
    Entity,
    NodeStyle,
    StylingContext,
    TaskStyle,
    contrast_text_color,
    sequential_hue,
    style_edge,
    style_label,
    style_node,
    style_task,
)

# =============================================================================
# Graph Styling (Graphviz)
# =============================================================================


@style_node(priority=100)
def color_by_timeframe(entity: Entity, context: StylingContext) -> NodeStyle:
    """Color nodes based on their timeframe metadata."""
    timeframe = entity.meta.get("timeframe")
    if not timeframe:
        return {}

    # Get all timeframes to create consistent color mapping
    all_timeframes = context.collect_metadata_values("timeframe")

    # Generate color based on sequential position
    bg_color = sequential_hue(timeframe, all_timeframes)
    text_color = contrast_text_color(bg_color)

    return {
        "fill_color": bg_color,
        "text_color": text_color,
    }


@style_node(priority=200)
def highlight_critical_path(entity: Entity, context: StylingContext) -> NodeStyle:
    """Add thick border to entities on critical path."""
    # Example: mark entities that are both late and enable outcomes
    enabled = context.transitively_enables(entity.id)
    outcomes = [e for e in enabled if (ent := context.get_entity(e)) and ent.type == "outcome"]

    if outcomes and entity.meta.get("priority") == "high":
        return {
            "border_color": "#ff0000",
            "border_width": 3,
        }
    return {}


@style_edge(priority=100)
def style_dependency_edges(
    from_id: str, to_id: str, edge_type: str, context: StylingContext
) -> EdgeStyle:
    """Style edges based on dependency type and entity types."""
    from_entity = context.get_entity(from_id)
    to_entity = context.get_entity(to_id)

    if not from_entity or not to_entity:
        return {}

    # Cross-layer dependencies (e.g., capability -> outcome) get special styling
    if from_entity.type == "capability" and to_entity.type == "outcome":
        return {
            "color": "#ff6600",
            "style": "dashed",
            "penwidth": 2,
        }

    # Default styling
    return {
        "color": "#666666",
        "style": "solid",
    }


# =============================================================================
# Gantt Chart Styling (Mermaid)
# =============================================================================


@style_task(priority=100)
def style_by_status_and_priority(entity: Entity, context: StylingContext) -> TaskStyle:
    """Assign Mermaid task tags based on status and priority.

    Mermaid gantt supports these tags:
    - done: Completed tasks (green)
    - crit: Critical tasks (red)
    - active: In-progress tasks (blue)
    - milestone: Single-point events
    """
    tags: list[str] = []

    # Check completion status
    status = entity.meta.get("status")
    if status == "done":
        tags.append("done")
        return {"tags": tags}  # Done tasks don't need other tags

    # Check priority
    priority = entity.meta.get("priority")
    if priority == "high":
        tags.append("crit")
    elif priority == "medium":
        tags.append("active")

    # Check if unassigned
    resources = entity.meta.get("resources", [])
    if not resources and "active" not in tags:
        tags.append("active")

    return {"tags": tags}


@style_task(priority=200)
def highlight_blocked_tasks(entity: Entity, context: StylingContext) -> TaskStyle:
    """Mark tasks that are blocking outcomes as critical."""
    # Find all outcomes this entity transitively enables
    enabled = context.transitively_enables(entity.id)
    enabled_outcomes = [
        e for e in enabled if (ent := context.get_entity(e)) and ent.type == "outcome"
    ]

    # If this entity blocks outcomes, mark as critical
    if enabled_outcomes and entity.meta.get("status") != "done":
        return {"tags": ["crit"]}

    return {}


@style_task(priority=300)
def color_by_team(entity: Entity, context: StylingContext) -> TaskStyle:
    """Color tasks by team ownership using custom CSS colors."""
    team = entity.meta.get("team")
    colors = {"platform": "#4287f5", "backend": "#42f554", "frontend": "#f54242"}

    if team in colors:
        return {"fill_color": colors[team]}

    return {}


# =============================================================================
# Markdown Label Styling
# =============================================================================


@style_label(priority=100)
def show_timeframe_in_label(entity: Entity, context: StylingContext) -> str | None:
    """Show timeframe in entity label."""
    timeframe = entity.meta.get("timeframe")
    if timeframe:
        return f"[{entity.type.replace('_', ' ').title()} · {timeframe}]"
    return None  # Use default if no timeframe


@style_label(priority=200)
def show_blocking_outcomes(entity: Entity, context: StylingContext) -> str | None:
    """For capabilities, show which outcomes they block."""
    if entity.type != "capability":
        return None

    # Find all outcomes this capability transitively enables
    enabled = context.transitively_enables(entity.id)
    enabled_outcomes = [
        ent for e in enabled if (ent := context.get_entity(e)) and ent.type == "outcome"
    ]

    max_outcomes_to_show = 3
    if enabled_outcomes:
        outcome_names = ", ".join(o.name for o in enabled_outcomes[:max_outcomes_to_show])
        if len(enabled_outcomes) > max_outcomes_to_show:
            outcome_names += f", +{len(enabled_outcomes) - max_outcomes_to_show} more"
        return f"[Capability → {outcome_names}]"

    return None
