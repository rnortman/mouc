"""Graph generation for Mouc."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import FeatureMap


class GraphView(Enum):
    """Types of graph views available."""

    ALL = "all"
    CRITICAL_PATH = "critical-path"
    FILTERED = "filtered"


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
        raise ValueError(f"Unknown view: {view}")

    def _generate_all(self) -> str:
        """Generate a complete graph with all entities."""
        lines = ["digraph FeatureMap {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=box];")
        lines.append("")

        # Add capabilities
        for cap_id, cap in self.feature_map.capabilities.items():
            label = self._escape_label(cap.name)
            lines.append(f'  {cap_id} [label="{label}", style=filled, fillcolor=lightblue];')
        lines.append("")

        # Add user stories
        for story_id, story in self.feature_map.user_stories.items():
            label = self._escape_label(story.name)
            lines.append(f'  {story_id} [label="{label}", style=filled, fillcolor=lightgreen];')
        lines.append("")

        # Add outcomes
        for outcome_id, outcome in self.feature_map.outcomes.items():
            label = self._escape_label(outcome.name)
            lines.append(f'  {outcome_id} [label="{label}", style=filled, fillcolor=lightyellow];')
        lines.append("")

        # Add edges
        lines.append("  // Capability dependencies (unblocks direction)")
        for cap_id, cap in self.feature_map.capabilities.items():
            for dep_id in cap.dependencies:
                lines.append(f"  {dep_id} -> {cap_id};")

        lines.append("")
        lines.append("  // User story dependencies (unblocks direction)")
        for story_id, story in self.feature_map.user_stories.items():
            for dep_id in story.dependencies:
                lines.append(f"  {dep_id} -> {story_id};")

        lines.append("")
        lines.append("  // Outcome dependencies (unblocks direction)")
        for outcome_id, outcome in self.feature_map.outcomes.items():
            for dep_id in outcome.dependencies:
                lines.append(f"  {dep_id} -> {outcome_id};")

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

            # Determine node type and style
            if node_id in self.feature_map.capabilities:
                entity = self.feature_map.capabilities[node_id]
                color = "lightblue"
            elif node_id in self.feature_map.user_stories:
                entity = self.feature_map.user_stories[node_id]
                color = "lightgreen"
            elif node_id in self.feature_map.outcomes:
                entity = self.feature_map.outcomes[node_id]
                color = "lightyellow"
            else:
                continue

            label = self._escape_label(entity.name)
            lines.append(f'  {node_id} [label="{label}", style=filled, fillcolor={color}];')

        lines.append("")

        # Add edges only for nodes in the critical path (unblocks direction)
        for cap_id, cap in self.feature_map.capabilities.items():
            if cap_id not in dependencies:
                continue
            for dep_id in cap.dependencies:
                if dep_id in dependencies:
                    lines.append(f"  {dep_id} -> {cap_id};")

        for story_id, story in self.feature_map.user_stories.items():
            if story_id not in dependencies:
                continue
            for dep_id in story.dependencies:
                if dep_id in dependencies:
                    lines.append(f"  {dep_id} -> {story_id};")

        for outcome_id, outcome in self.feature_map.outcomes.items():
            if outcome_id not in dependencies:
                continue
            for dep_id in outcome.dependencies:
                if dep_id in dependencies:
                    lines.append(f"  {dep_id} -> {outcome_id};")

        lines.append("}")
        return "\n".join(lines)

    def _generate_filtered(self, tags: list[str]) -> str:
        """Generate a graph filtered by tags."""
        # Find all entities with matching tags
        matching_ids: set[str] = set()

        for cap_id, cap in self.feature_map.capabilities.items():
            if any(tag in cap.tags for tag in tags):
                matching_ids.add(cap_id)

        for story_id, story in self.feature_map.user_stories.items():
            if any(tag in story.tags for tag in tags):
                matching_ids.add(story_id)

        for outcome_id, outcome in self.feature_map.outcomes.items():
            if any(tag in outcome.tags for tag in tags):
                matching_ids.add(outcome_id)

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
            if node_id in self.feature_map.capabilities:
                entity = self.feature_map.capabilities[node_id]
                color = "lightblue"
            elif node_id in self.feature_map.user_stories:
                entity = self.feature_map.user_stories[node_id]
                color = "lightgreen"
            elif node_id in self.feature_map.outcomes:
                entity = self.feature_map.outcomes[node_id]
                color = "lightyellow"
            else:
                continue

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
        for cap_id, cap in self.feature_map.capabilities.items():
            if cap_id not in expanded_ids:
                continue
            for dep_id in cap.dependencies:
                if dep_id in expanded_ids:
                    lines.append(f"  {dep_id} -> {cap_id};")

        for story_id, story in self.feature_map.user_stories.items():
            if story_id not in expanded_ids:
                continue
            for dep_id in story.dependencies:
                if dep_id in expanded_ids:
                    lines.append(f"  {dep_id} -> {story_id};")

        for outcome_id, outcome in self.feature_map.outcomes.items():
            if outcome_id not in expanded_ids:
                continue
            for dep_id in outcome.dependencies:
                if dep_id in expanded_ids:
                    lines.append(f"  {dep_id} -> {outcome_id};")

        lines.append("}")
        return "\n".join(lines)

    def _find_all_dependencies(self, target: str) -> set[str]:
        """Find all transitive dependencies of a target."""
        dependencies: set[str] = set()
        to_process = [target]

        while to_process:
            current = to_process.pop()

            # Check capabilities
            if current in self.feature_map.capabilities:
                cap = self.feature_map.capabilities[current]
                for dep_id in cap.dependencies:
                    if dep_id not in dependencies:
                        dependencies.add(dep_id)
                        to_process.append(dep_id)

            # Check user stories
            elif current in self.feature_map.user_stories:
                story = self.feature_map.user_stories[current]
                for dep_id in story.dependencies:
                    if dep_id not in dependencies:
                        dependencies.add(dep_id)
                        to_process.append(dep_id)

            # Check outcomes
            elif current in self.feature_map.outcomes:
                outcome = self.feature_map.outcomes[current]
                for dep_id in outcome.dependencies:
                    if dep_id not in dependencies:
                        dependencies.add(dep_id)
                        to_process.append(dep_id)

        return dependencies

    def _find_direct_connections(self, node_id: str) -> set[str]:
        """Find direct dependencies and dependents of a node."""
        connections: set[str] = set()

        # If it's a capability, add its dependencies
        if node_id in self.feature_map.capabilities:
            cap = self.feature_map.capabilities[node_id]
            connections.update(cap.dependencies)

        # If it's a user story, add its dependencies
        if node_id in self.feature_map.user_stories:
            story = self.feature_map.user_stories[node_id]
            connections.update(story.dependencies)

        # If it's an outcome, add its dependencies
        if node_id in self.feature_map.outcomes:
            outcome = self.feature_map.outcomes[node_id]
            connections.update(outcome.dependencies)

        # Find things that depend on this node
        connections.update(self.feature_map.get_capability_dependents(node_id))

        # Find user stories that depend on this node
        for story_id, story in self.feature_map.user_stories.items():
            if node_id in story.dependencies:
                connections.add(story_id)

        # Find outcomes that depend on this node
        for outcome_id, outcome in self.feature_map.outcomes.items():
            if node_id in outcome.dependencies:
                connections.add(outcome_id)

        return connections

    def _escape_label(self, label: str) -> str:
        """Escape special characters in DOT labels."""
        return label.replace('"', '\\"').replace("\n", "\\n")
