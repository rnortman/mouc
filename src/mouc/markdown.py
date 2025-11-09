"""Markdown documentation generator for Mouc."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from . import styling

if TYPE_CHECKING:
    from .models import Entity, FeatureMap


def make_anchor(entity_id: str, feature_map: FeatureMap) -> str:
    """Create a valid markdown anchor from an entity ID.

    Looks up the entity by ID and uses its name to generate the anchor,
    matching the format used in markdown headers.

    Args:
        entity_id: The entity ID to look up
        feature_map: The feature map containing the entity

    Returns:
        A markdown-compatible anchor string
    """
    # Get the entity name based on ID
    entity = feature_map.get_entity_by_id(entity_id)
    if entity:
        name = entity.name
    else:
        # Fallback to ID-based anchor if entity not found
        return entity_id.replace("_", "-")

    # Convert name to markdown anchor format
    # Lowercase, replace spaces with hyphens, remove special chars
    anchor = name.lower()
    anchor = anchor.replace(" ", "-")
    # Remove characters that aren't alphanumeric or hyphens
    anchor = "".join(c for c in anchor if c.isalnum() or c == "-")
    # Remove multiple consecutive hyphens
    while "--" in anchor:
        anchor = anchor.replace("--", "-")
    # Remove leading/trailing hyphens
    return anchor.strip("-")


class MarkdownGenerator:
    """Generate markdown documentation from a feature map."""

    def __init__(self, feature_map: FeatureMap):
        """Initialize with a feature map."""
        self.feature_map = feature_map
        # Create styling context
        self.styling_context = styling.create_styling_context(feature_map)

    def generate(self) -> str:
        """Generate complete markdown documentation."""
        sections = [
            self._generate_header(),
            self._generate_timeline(),
            self._check_backward_dependencies(),
            self._generate_toc(),
            self._generate_capabilities_section(),
            self._generate_user_stories_section(),
            self._generate_outcomes_section(),
        ]

        return "\n\n".join(section for section in sections if section)

    def _generate_header(self) -> str:
        """Generate document header."""
        lines = ["# Feature Map", ""]

        # Build metadata table
        lines.append("| | |")
        lines.append("|-|-|")

        if self.feature_map.metadata.team:
            lines.append(f"| Team | {self.feature_map.metadata.team} |")

        if self.feature_map.metadata.last_updated:
            lines.append(f"| Last Updated | {self.feature_map.metadata.last_updated} |")

        lines.append(f"| Version | {self.feature_map.metadata.version} |")

        return "\n".join(lines)

    def _generate_toc(self) -> str:
        """Generate table of contents."""
        lines = ["## Table of Contents", ""]

        # Group entities by type
        capabilities = self.feature_map.get_entities_by_type("capability")
        user_stories = self.feature_map.get_entities_by_type("user_story")
        outcomes = self.feature_map.get_entities_by_type("outcome")

        if capabilities:
            lines.append("- [Capabilities](#capabilities)")
            for entity in sorted(capabilities, key=lambda e: e.id):
                anchor = self._make_anchor(entity.id)
                type_label = self._format_type_label(entity)
                lines.append(f"  - [{entity.name}](#{anchor}){type_label}")

        if user_stories:
            lines.append("- [User Stories](#user-stories)")
            for entity in sorted(user_stories, key=lambda e: e.id):
                anchor = self._make_anchor(entity.id)
                type_label = self._format_type_label(entity)
                lines.append(f"  - [{entity.name}](#{anchor}){type_label}")

        if outcomes:
            lines.append("- [Outcomes](#outcomes)")
            for entity in sorted(outcomes, key=lambda e: e.id):
                anchor = self._make_anchor(entity.id)
                type_label = self._format_type_label(entity)
                lines.append(f"  - [{entity.name}](#{anchor}){type_label}")

        return "\n".join(lines)

    def _generate_timeline(self) -> str:
        """Generate timeline section grouped by timeframe."""
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

        # If no entities have timeframes, don't generate the timeline section
        if not timeframe_groups:
            return ""

        lines = ["## Timeline", ""]

        # Sort timeframes lexically for consistent ordering
        sorted_timeframes = sorted(timeframe_groups.keys())

        # Generate timeline entries
        for timeframe in sorted_timeframes:
            lines.append(f"### {timeframe}")
            lines.append("")

            entities = sorted(timeframe_groups[timeframe], key=lambda e: (e.type, e.id))
            for entity in entities:
                anchor = self._make_anchor(entity.id)
                type_label = self._format_type_label(entity)
                lines.append(f"- [{entity.name}](#{anchor}){type_label}")

            lines.append("")

        # Add unscheduled section if there are any
        if unscheduled:
            lines.append("### Unscheduled")
            lines.append("")

            entities = sorted(unscheduled, key=lambda e: (e.type, e.id))
            for entity in entities:
                anchor = self._make_anchor(entity.id)
                type_label = self._format_type_label(entity)
                lines.append(f"- [{entity.name}](#{anchor}){type_label}")

            lines.append("")

        return "\n".join(lines).rstrip()

    def _check_backward_dependencies(self) -> str:
        """Check for dependencies going backward in timeline order."""
        warnings: list[str] = []

        # Build a map of entity IDs to their timeframes
        timeframe_map: dict[str, str | None] = {}
        for entity in self.feature_map.entities:
            timeframe_map[entity.id] = entity.meta.get("timeframe")

        # Check each entity's dependencies
        for entity in self.feature_map.entities:
            entity_timeframe = timeframe_map.get(entity.id)

            # Skip if entity has no timeframe (unscheduled entities can depend on anything)
            if not entity_timeframe:
                continue

            for dep_id in entity.requires:
                dep_timeframe = timeframe_map.get(dep_id)

                # If dependency has no timeframe (unscheduled), it's always backward
                if not dep_timeframe:
                    dep_entity = self.feature_map.get_entity_by_id(dep_id)
                    dep_name = dep_entity.name if dep_entity else dep_id
                    msg = f"`{entity.name}` ({entity_timeframe}) depends on `{dep_name}` (Unscheduled)"
                    warnings.append(msg)
                    # Also print to console
                    sys.stderr.write(f"WARNING: Backward dependency - {msg}\n")
                    continue

                # Check if dependency comes after entity in lexical order
                if dep_timeframe > entity_timeframe:
                    dep_entity = self.feature_map.get_entity_by_id(dep_id)
                    dep_name = dep_entity.name if dep_entity else dep_id
                    msg = f"`{entity.name}` ({entity_timeframe}) depends on `{dep_name}` ({dep_timeframe})"
                    warnings.append(msg)
                    # Also print to console
                    sys.stderr.write(f"WARNING: Backward dependency - {msg}\n")

        # Generate warning section if any backward dependencies found
        if warnings:
            lines = ["## ⚠️ Timeline Warnings", ""]
            lines.append("The following dependencies go backward in timeline order:")
            lines.append("")
            for warning in warnings:
                lines.append(f"- {warning}")
            return "\n".join(lines)

        return ""

    def _generate_capabilities_section(self) -> str:
        """Generate capabilities section."""
        capabilities = self.feature_map.get_entities_by_type("capability")
        if not capabilities:
            return ""

        lines = ["## Capabilities", ""]

        for entity in sorted(capabilities, key=lambda e: e.id):
            lines.extend(self._format_entity(entity))
            lines.append("")

        return "\n".join(lines)

    def _generate_user_stories_section(self) -> str:
        """Generate user stories section."""
        user_stories = self.feature_map.get_entities_by_type("user_story")
        if not user_stories:
            return ""

        lines = ["## User Stories", ""]

        for entity in sorted(user_stories, key=lambda e: e.id):
            lines.extend(self._format_entity(entity))
            lines.append("")

        return "\n".join(lines)

    def _generate_outcomes_section(self) -> str:
        """Generate outcomes section."""
        outcomes = self.feature_map.get_entities_by_type("outcome")
        if not outcomes:
            return ""

        lines = ["## Outcomes", ""]

        for entity in sorted(outcomes, key=lambda e: e.id):
            lines.extend(self._format_entity(entity))
            lines.append("")

        return "\n".join(lines)

    def _format_links(self, links: list[str]) -> list[str]:
        """Format links for display in a table."""
        if not links:
            return []

        from .models import Link

        # Parse all links
        parsed_links = [Link.parse(link) for link in links]

        # Group by type for better organization
        by_type: dict[str | None, list[Link]] = {}
        for link in parsed_links:
            by_type.setdefault(link.type, []).append(link)

        rows: list[str] = []
        for link_type, type_links in sorted(by_type.items(), key=lambda x: (x[0] is None, x[0])):
            for link in type_links:
                display = f"[{link.label}]({link.url})" if link.url else f"`{link.label}`"

                if link_type:
                    # Prettify type name
                    pretty_type = link_type.replace("_", " ").title()
                    rows.append(f"| {pretty_type} | {display} |")
                else:
                    rows.append(f"| Link | {display} |")

        return rows

    def _format_entity(self, entity: Entity) -> list[str]:
        """Format a single entity."""
        lines = [f"### {entity.name}", ""]

        # Build metadata table
        table_rows: list[str] = []
        table_rows.append(f"| ID | `{entity.id}` |")

        # Apply metadata styling functions to get display metadata
        # This allows styling functions to add computed fields without mutation
        display_metadata: dict[str, Any] = styling.apply_metadata_styles(
            entity, self.styling_context, entity.meta
        )  # type: ignore

        # Add all metadata fields
        for key, value in sorted(display_metadata.items()):
            # Format the key nicely
            pretty_key = key.replace("_", " ").title()
            # Format the value based on type
            formatted_value: str
            if isinstance(value, list):
                formatted_value = ", ".join(str(item) for item in value)  # type: ignore
            else:
                formatted_value = str(value)
            table_rows.append(f"| {pretty_key} | {formatted_value} |")

        if entity.tags:
            tags = ", ".join(f"`{tag}`" for tag in entity.tags)
            table_rows.append(f"| Tags | {tags} |")

        # Add links
        link_rows = self._format_links(entity.links)
        table_rows.extend(link_rows)

        if table_rows:
            lines.append("| | |")
            lines.append("|-|-|")
            lines.extend(table_rows)
            lines.append("")

        lines.append(entity.description.strip())

        if entity.requires:
            lines.append("")
            lines.append("#### Requires")
            lines.append("")
            for dep_id in sorted(entity.requires):
                dep = self.feature_map.get_entity_by_id(dep_id)
                if dep:
                    anchor = self._make_anchor(dep_id)
                    type_label = (
                        f" [{self._pretty_type(dep.type)}]" if dep.type != entity.type else ""
                    )
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`){type_label}")
                else:
                    lines.append(f"- `{dep_id}` ⚠️ (missing)")

        # Find what depends on this entity (what this enables)
        dependents = entity.enables

        if dependents:
            lines.append("")
            lines.append("#### Enables")
            lines.append("")

            # Sort dependents by type and ID for consistent output
            sorted_dependents: list[tuple[str, str, Entity]] = []
            for dep_id in sorted(dependents):
                dep = self.feature_map.get_entity_by_id(dep_id)
                if dep:
                    sorted_dependents.append((dep.type, dep_id, dep))

            for _dep_type, dep_id, dep in sorted(sorted_dependents):
                anchor = self._make_anchor(dep_id)
                type_label = f" [{self._pretty_type(dep.type)}]" if dep.type != entity.type else ""
                lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`){type_label}")

        return lines

    def _pretty_type(self, entity_type: str) -> str:
        """Convert entity type to pretty display name."""
        type_names = {"capability": "Capability", "user_story": "User Story", "outcome": "Outcome"}
        return type_names.get(entity_type, entity_type.replace("_", " ").title())

    def _make_anchor(self, entity_id: str) -> str:
        """Create a valid HTML anchor from an entity name."""
        return make_anchor(entity_id, self.feature_map)

    def _format_type_label(self, entity: Entity) -> str:
        """Format type label with styling applied."""
        # Apply user styling
        user_label = styling.apply_label_styles(entity, self.styling_context)  # type: ignore

        # If user styling returned a label (including empty string to hide), use it
        if user_label is not None:
            return f" {user_label}" if user_label else ""

        # Otherwise use default type label
        return f" [{self._pretty_type(entity.type)}]"
