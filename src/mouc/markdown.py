"""Markdown documentation generator for Mouc."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Entity, FeatureMap


class MarkdownGenerator:
    """Generate markdown documentation from a feature map."""

    def __init__(self, feature_map: FeatureMap):
        """Initialize with a feature map."""
        self.feature_map = feature_map

    def generate(self) -> str:
        """Generate complete markdown documentation."""
        sections = [
            self._generate_header(),
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
                lines.append(f"  - [{entity.name}](#{anchor})")

        if user_stories:
            lines.append("- [User Stories](#user-stories)")
            for entity in sorted(user_stories, key=lambda e: e.id):
                anchor = self._make_anchor(entity.id)
                lines.append(f"  - [{entity.name}](#{anchor})")

        if outcomes:
            lines.append("- [Outcomes](#outcomes)")
            for entity in sorted(outcomes, key=lambda e: e.id):
                anchor = self._make_anchor(entity.id)
                lines.append(f"  - [{entity.name}](#{anchor})")

        return "\n".join(lines)

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

        if "requestor" in entity.meta:
            table_rows.append(f"| Requestor | {entity.meta['requestor']} |")

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

        if entity.dependencies:
            lines.append("")
            lines.append("#### Dependencies")
            lines.append("")
            for dep_id in entity.dependencies:
                dep = self.feature_map.get_entity_by_id(dep_id)
                if dep:
                    anchor = self._make_anchor(dep_id)
                    type_label = (
                        f" [{self._pretty_type(dep.type)}]" if dep.type != entity.type else ""
                    )
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`){type_label}")
                else:
                    lines.append(f"- `{dep_id}` ⚠️ (missing)")

        # Find what depends on this entity
        dependents = self.feature_map.get_dependents(entity.id)

        if dependents:
            lines.append("")
            lines.append("#### Required by")
            lines.append("")

            # Sort dependents by type and ID for consistent output
            sorted_dependents: list[tuple[str, str, Entity]] = []
            for dep_id in dependents:
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
        # Get the entity name based on ID
        entity = self.feature_map.get_entity_by_id(entity_id)
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
