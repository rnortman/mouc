"""Graph generation for Mouc."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Entity, FeatureMap


class GraphView(Enum):
    """Types of graph views available."""

    ALL = "all"
    CRITICAL_PATH = "critical-path"
    FILTERED = "filtered"
    TIMELINE = "timeline"
    TIMEFRAME_COLORED = "timeframe-colored"


class GraphGenerator:
    """Generate dependency graphs in DOT format."""

    def __init__(self, feature_map: FeatureMap):
        """Initialize with a feature map."""
        self.feature_map = feature_map

    def generate(
        self,
        view: GraphView = GraphView.ALL,
        target: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Generate a DOT graph based on the specified view."""
        if view == GraphView.ALL:
            return self._generate_all()
        if view == GraphView.CRITICAL_PATH:
            if not target:
                raise ValueError("Critical path view requires a target")
            return self._generate_critical_path(target)
        if view == GraphView.FILTERED:
            if not tags:
                raise ValueError("Filtered view requires tags")
            return self._generate_filtered(tags)
        if view == GraphView.TIMELINE:
            return self._generate_timeline()
        if view == GraphView.TIMEFRAME_COLORED:
            return self._generate_timeframe_colored()
        raise ValueError(f"Unknown view: {view}")

    def _generate_all(self) -> str:
        """Generate a complete graph with all entities."""
        lines = ["digraph FeatureMap {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=oval];")
        lines.append("")

        # Group entities by type for consistent rendering
        capabilities = self.feature_map.get_entities_by_type("capability")
        user_stories = self.feature_map.get_entities_by_type("user_story")
        outcomes = self.feature_map.get_entities_by_type("outcome")

        # Add capabilities
        for entity in capabilities:
            label = self._escape_label(entity.name)
            lines.append(f'  {entity.id} [label="{label}", style=filled, fillcolor=lightblue];')
        lines.append("")

        # Add user stories
        for entity in user_stories:
            label = self._escape_label(entity.name)
            lines.append(f'  {entity.id} [label="{label}", style=filled, fillcolor=lightgreen];')
        lines.append("")

        # Add outcomes
        for entity in outcomes:
            label = self._escape_label(entity.name)
            lines.append(f'  {entity.id} [label="{label}", style=filled, fillcolor=lightyellow];')
        lines.append("")

        # Add edges (unblocks direction)
        lines.append("  // Dependencies (unblocks direction)")
        for entity in self.feature_map.entities:
            for dep_id in entity.dependencies:
                lines.append(f"  {dep_id} -> {entity.id};")

        lines.append("}")
        return "\n".join(lines)

    def _generate_critical_path(self, target: str) -> str:
        """Generate a graph showing only the critical path to a target."""
        # Find all dependencies of the target
        dependencies = self._find_all_dependencies(target)
        dependencies.add(target)

        lines = ["digraph CriticalPath {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=oval];")
        lines.append("")

        # Highlight the target
        lines.append(f"  {target} [style=filled, fillcolor=red, fontcolor=white];")
        lines.append("")

        # Add all nodes in the critical path
        for node_id in dependencies:
            if node_id == target:
                continue

            entity = self.feature_map.get_entity_by_id(node_id)
            if not entity:
                continue

            # Determine node color by type
            color_map = {
                "capability": "lightblue",
                "user_story": "lightgreen",
                "outcome": "lightyellow",
            }
            color = color_map.get(entity.type, "white")

            label = self._escape_label(entity.name)
            lines.append(f'  {node_id} [label="{label}", style=filled, fillcolor={color}];')

        lines.append("")

        # Add edges only for nodes in the critical path (unblocks direction)
        for entity in self.feature_map.entities:
            if entity.id not in dependencies:
                continue
            for dep_id in entity.dependencies:
                if dep_id in dependencies:
                    lines.append(f"  {dep_id} -> {entity.id};")

        lines.append("}")
        return "\n".join(lines)

    def _generate_filtered(self, tags: list[str]) -> str:
        """Generate a graph filtered by tags."""
        # Find all entities with matching tags
        matching_ids: set[str] = set()

        for entity in self.feature_map.entities:
            if any(tag in entity.tags for tag in tags):
                matching_ids.add(entity.id)

        # Also include direct dependencies/dependents
        expanded_ids: set[str] = matching_ids.copy()
        for node_id in matching_ids:
            expanded_ids.update(self._find_direct_connections(node_id))

        lines = ["digraph FilteredView {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=oval];")
        lines.append("")

        # Add nodes
        for node_id in expanded_ids:
            entity = self.feature_map.get_entity_by_id(node_id)
            if not entity:
                continue

            # Determine node color by type
            color_map = {
                "capability": "lightblue",
                "user_story": "lightgreen",
                "outcome": "lightyellow",
            }
            color = color_map.get(entity.type, "white")

            label = self._escape_label(entity.name)
            # Highlight nodes that match the filter
            if node_id in matching_ids:
                lines.append(
                    f'  {node_id} [label="{label}", style=filled, fillcolor={color}, penwidth=3];'
                )
            else:
                lines.append(f'  {node_id} [label="{label}", style=filled, fillcolor={color}];')

        lines.append("")

        # Add edges (unblocks direction)
        for entity in self.feature_map.entities:
            if entity.id not in expanded_ids:
                continue
            for dep_id in entity.dependencies:
                if dep_id in expanded_ids:
                    lines.append(f"  {dep_id} -> {entity.id};")

        lines.append("}")
        return "\n".join(lines)

    def _find_all_dependencies(self, target: str) -> set[str]:
        """Find all transitive dependencies of a target."""
        dependencies: set[str] = set()
        to_process = [target]

        while to_process:
            current = to_process.pop()

            entity = self.feature_map.get_entity_by_id(current)
            if entity:
                for dep_id in entity.dependencies:
                    if dep_id not in dependencies:
                        dependencies.add(dep_id)
                        to_process.append(dep_id)

        return dependencies

    def _find_direct_connections(self, node_id: str) -> set[str]:
        """Find direct dependencies and dependents of a node."""
        connections: set[str] = set()

        # Find the entity and add its dependencies
        entity = self.feature_map.get_entity_by_id(node_id)
        if entity:
            connections.update(entity.dependencies)

        # Find things that depend on this node
        connections.update(self.feature_map.get_dependents(node_id))

        return connections

    def _escape_label(self, label: str) -> str:
        """Escape special characters in DOT labels."""
        return label.replace('"', '\\"').replace("\n", "\\n")

    def _hsl_to_hex(self, h: float, s: float, lightness: float) -> str:
        """Convert HSL color to hex format for Graphviz.

        Args:
            h: Hue in degrees (0-360)
            s: Saturation as percentage (0-100)
            lightness: Lightness as percentage (0-100)

        Returns:
            Hex color string like "#RRGGBB"
        """
        h = h / 360
        s = s / 100
        lightness = lightness / 100

        if s == 0:
            r = g = b = lightness
        else:

            def hue_to_rgb(p: float, q: float, t: float) -> float:
                if t < 0:
                    t += 1
                if t > 1:
                    t -= 1
                if t < 1 / 6:
                    return p + (q - p) * 6 * t
                if t < 1 / 2:
                    return q
                if t < 2 / 3:
                    return p + (q - p) * (2 / 3 - t) * 6
                return p

            q = lightness * (1 + s) if lightness < 0.5 else lightness + s - lightness * s
            p = 2 * lightness - q
            r = hue_to_rgb(p, q, h + 1 / 3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1 / 3)

        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

    def _get_timeframe_color(self, timeframe_index: int, total_timeframes: int) -> str:
        """Generate a color for a timeframe based on its position in the sequence."""
        if total_timeframes == 0:
            return "lightgray"

        start_hue = 120
        end_hue = 220

        start_lightness = 88
        end_lightness = 50

        if total_timeframes == 1:
            hue = (start_hue + end_hue) / 2
            lightness = (start_lightness + end_lightness) / 2
        else:
            progress = timeframe_index / (total_timeframes - 1)
            hue = start_hue + (end_hue - start_hue) * progress
            lightness = start_lightness + (end_lightness - start_lightness) * progress

        return self._hsl_to_hex(hue, 60, lightness)

    def _generate_timeline(self) -> str:
        """Generate a timeline graph grouped by timeframe."""
        # Group entities by timeframe
        timeframe_groups: dict[str, list[Entity]] = {}
        unscheduled: list[Entity] = []

        for entity in self.feature_map.entities:
            timeframe = entity.meta.get("timeframe")
            if timeframe:
                if timeframe not in timeframe_groups:
                    timeframe_groups[timeframe] = []
                timeframe_groups[timeframe].append(entity)
            else:
                unscheduled.append(entity)

        # Sort timeframes for consistent ordering
        sorted_timeframes = sorted(timeframe_groups.keys())

        lines = ["digraph Timeline {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=oval];")
        lines.append("")

        # Create subgraph clusters for each timeframe
        cluster_idx = 0
        for timeframe in sorted_timeframes:
            lines.append(f"  subgraph cluster_{cluster_idx} {{")
            lines.append(f'    label="{self._escape_label(timeframe)}";')
            lines.append("    style=filled;")
            lines.append("    fillcolor=lightgrey;")
            lines.append("")

            # Add entities in this timeframe
            for entity in timeframe_groups[timeframe]:
                # Determine node color by type
                color_map = {
                    "capability": "lightblue",
                    "user_story": "lightgreen",
                    "outcome": "lightyellow",
                }
                color = color_map.get(entity.type, "white")

                label = self._escape_label(entity.name)
                lines.append(f'    {entity.id} [label="{label}", style=filled, fillcolor={color}];')

            lines.append("  }")
            lines.append("")
            cluster_idx += 1

        # Add unscheduled entities if any
        if unscheduled:
            lines.append(f"  subgraph cluster_{cluster_idx} {{")
            lines.append('    label="Unscheduled";')
            lines.append("    style=dashed;")
            lines.append("")

            for entity in unscheduled:
                # Determine node color by type
                color_map = {
                    "capability": "lightblue",
                    "user_story": "lightgreen",
                    "outcome": "lightyellow",
                }
                color = color_map.get(entity.type, "white")

                label = self._escape_label(entity.name)
                lines.append(f'    {entity.id} [label="{label}", style=filled, fillcolor={color}];')

            lines.append("  }")
            lines.append("")

        # Add all edges (dependencies)
        lines.append("  // Dependencies")
        for entity in self.feature_map.entities:
            for dep_id in entity.dependencies:
                lines.append(f"  {dep_id} -> {entity.id};")

        lines.append("}")
        return "\n".join(lines)

    def _generate_timeframe_colored(self) -> str:
        """Generate a graph where node colors represent timeframes."""
        # Group entities by timeframe
        timeframe_groups: dict[str, list[Entity]] = {}
        unscheduled: list[Entity] = []

        for entity in self.feature_map.entities:
            timeframe = entity.meta.get("timeframe")
            if timeframe:
                if timeframe not in timeframe_groups:
                    timeframe_groups[timeframe] = []
                timeframe_groups[timeframe].append(entity)
            else:
                unscheduled.append(entity)

        # Sort timeframes for consistent ordering
        sorted_timeframes = sorted(timeframe_groups.keys())
        total_timeframes = len(sorted_timeframes)

        # Build a map of entity ID to color
        entity_colors: dict[str, str] = {}
        for idx, timeframe in enumerate(sorted_timeframes):
            color = self._get_timeframe_color(idx, total_timeframes)
            for entity in timeframe_groups[timeframe]:
                entity_colors[entity.id] = color

        # Unscheduled entities get gray
        for entity in unscheduled:
            entity_colors[entity.id] = "lightgray"

        lines = ["digraph TimeframeColored {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=oval];")
        lines.append("")

        # Add all nodes with colors based on timeframe
        for entity in self.feature_map.entities:
            color = entity_colors.get(entity.id, "white")
            label = self._escape_label(entity.name)
            lines.append(f'  {entity.id} [label="{label}", style=filled, fillcolor="{color}"];')

        lines.append("")

        # Add edges (unblocks direction)
        lines.append("  // Dependencies")
        for entity in self.feature_map.entities:
            for dep_id in entity.dependencies:
                lines.append(f"  {dep_id} -> {entity.id};")

        lines.append("}")
        return "\n".join(lines)
