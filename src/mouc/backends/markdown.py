"""Markdown backend for document generation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mouc import styling
from mouc.backends.base import EntityReference
from mouc.models import Link

if TYPE_CHECKING:
    from mouc.models import Entity, FeatureMap, FeatureMapMetadata
    from mouc.styling import StylingContext


class MarkdownBackend:
    """Backend for generating markdown documents."""

    def __init__(self, feature_map: FeatureMap, styling_context: StylingContext):
        """Initialize markdown backend.

        Args:
            feature_map: The feature map being documented
            styling_context: Styling context for applying user customizations
        """
        self.feature_map = feature_map
        self.styling_context = styling_context
        self.lines: list[str] = []

    def create_document(self) -> None:
        """Initialize a new markdown document."""
        self.lines = []

    def add_header(self, metadata: FeatureMapMetadata) -> None:
        """Add document header with feature map metadata."""
        self.lines.extend(["# Feature Map", ""])

        # Build metadata table
        self.lines.extend(["| | |", "|-|-|"])

        if metadata.team:
            self.lines.append(f"| Team | {metadata.team} |")

        if metadata.last_updated:
            self.lines.append(f"| Last Updated | {metadata.last_updated} |")

        self.lines.append(f"| Version | {metadata.version} |")

    def add_section_header(self, text: str, level: int) -> str:
        """Add a section header at the specified level.

        Args:
            text: Section heading text
            level: Heading level (1=top-level, 2=subsection, etc.)

        Returns:
            Anchor ID for cross-referencing this section
        """
        heading_prefix = "#" * (level + 1)  # +1 because main title is #
        self.lines.append(f"{heading_prefix} {text}")
        self.lines.append("")
        return self._make_anchor_from_text(text)

    def add_entity(  # noqa: PLR0913 - Entity rendering requires multiple structured parameters
        self,
        entity: Entity,
        anchor_id: str,
        styled_type_label: str | None,
        display_metadata: dict[str, Any],
        requires_refs: list[EntityReference],
        enables_refs: list[EntityReference],
        level: int,
    ) -> None:
        """Render a complete entity in markdown format."""
        # level directly represents the heading level: 1=h1, 2=h2, 3=h3, 4=h4, etc.
        # In markdown, this corresponds to the number of # symbols
        # Examples:
        # level=3: h3 entity -> ###
        # level=4: h4 entity -> ####
        heading_prefix = "#" * level
        self.lines.append(f"{heading_prefix} {entity.name}")
        self.lines.append("")

        # Build metadata table
        table_rows: list[str] = []
        table_rows.append(f"| ID | `{entity.id}` |")

        # Add all metadata fields
        for key, value in sorted(display_metadata.items()):
            # Format the key nicely
            pretty_key = key.replace("_", " ").title()
            # Format the value based on type
            if isinstance(value, list):
                # Metadata values can be any type, str() safely converts all types for display
                formatted_value = ", ".join(str(item) for item in value)  # type: ignore[arg-type]
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
            self.lines.extend(["| | |", "|-|-|"])
            self.lines.extend(table_rows)
            self.lines.append("")

        self.lines.append(entity.description.strip())

        # Requires section - use level + 1 for subsection heading
        if requires_refs:
            subsection_heading = "#" * (level + 1)
            self.lines.extend(["", f"{subsection_heading} Requires", ""])
            for ref in requires_refs:
                type_label = (
                    f" [{self._pretty_type(ref.entity_type)}]"
                    if ref.entity_type != entity.type
                    else ""
                )
                self.lines.append(
                    f"- [{ref.entity_name}](#{ref.anchor_id}) (`{ref.entity_id}`){type_label}"
                )

        # Enables section - use level + 1 for subsection heading
        if enables_refs:
            subsection_heading = "#" * (level + 1)
            self.lines.extend(["", f"{subsection_heading} Enables", ""])
            for ref in enables_refs:
                type_label = (
                    f" [{self._pretty_type(ref.entity_type)}]"
                    if ref.entity_type != entity.type
                    else ""
                )
                self.lines.append(
                    f"- [{ref.entity_name}](#{ref.anchor_id}) (`{ref.entity_id}`){type_label}"
                )

    def add_toc_entry(
        self, text: str, anchor_id: str, level: int, suffix: str | None = None
    ) -> None:
        """Add a table of contents entry.

        Args:
            text: TOC entry text (link text)
            anchor_id: Anchor to link to
            level: Nesting level in TOC (0=top-level, 1=nested, etc.)
            suffix: Optional suffix to append after the link (e.g., type label)
        """
        indent = "  " * level
        suffix_str = suffix or ""
        self.lines.append(f"{indent}- [{text}](#{anchor_id}){suffix_str}")

    def add_timeline_warnings(self, warnings: list[str]) -> None:
        """Add timeline dependency warnings section."""
        if not warnings:
            return

        self.lines.extend(["## ⚠️ Timeline Warnings", ""])
        self.lines.append("The following dependencies go backward in timeline order:")
        self.lines.append("")
        for warning in warnings:
            self.lines.append(f"- {warning}")

    def finalize(self) -> str:
        """Finalize and return the markdown document."""
        return "\n\n".join(self._get_sections())

    def make_anchor(self, entity_id: str, entity_name: str) -> str:
        """Create a markdown-compatible anchor from entity name.

        Args:
            entity_id: Unique entity identifier (unused in markdown)
            entity_name: Human-readable entity name

        Returns:
            Markdown anchor string (kebab-case)
        """
        # Convert name to markdown anchor format
        # Lowercase, replace spaces with hyphens, remove special chars
        anchor = entity_name.lower()
        anchor = anchor.replace(" ", "-")
        # Remove characters that aren't alphanumeric or hyphens
        anchor = "".join(c for c in anchor if c.isalnum() or c == "-")
        # Remove multiple consecutive hyphens
        while "--" in anchor:
            anchor = anchor.replace("--", "-")
        # Remove leading/trailing hyphens
        return anchor.strip("-")

    def format_link(self, link: Link) -> str:
        """Format an external link in markdown format."""
        if link.url:
            return f"[{link.label}]({link.url})"
        return f"`{link.label}`"

    def format_internal_reference(self, ref: EntityReference) -> str:
        """Format an internal cross-reference in markdown format."""
        return f"[{ref.entity_name}](#{ref.anchor_id})"

    def format_type_label(self, entity: Entity) -> str:
        """Format type label with styling applied.

        Args:
            entity: Entity to get type label for

        Returns:
            Formatted type label string (may be empty if styled to hide)
        """
        # Apply user styling
        user_label = styling.apply_label_styles(entity, self.styling_context)

        # If user styling returned a label (including empty string to hide), use it
        if user_label is not None:
            return f" {user_label}" if user_label else ""

        # Otherwise use default type label
        return f" [{self._pretty_type(entity.type)}]"

    def _format_links(self, links: list[str]) -> list[str]:
        """Format links for display in a markdown table."""
        if not links:
            return []

        # Parse all links
        parsed_links = [Link.parse(link) for link in links]

        # Group by type for better organization
        by_type: dict[str | None, list[Link]] = {}
        for link in parsed_links:
            by_type.setdefault(link.type, []).append(link)

        rows: list[str] = []
        for link_type, type_links in sorted(by_type.items(), key=lambda x: (x[0] is None, x[0])):
            for link in type_links:
                display = self.format_link(link)

                if link_type:
                    # Prettify type name
                    pretty_type = link_type.replace("_", " ").title()
                    rows.append(f"| {pretty_type} | {display} |")
                else:
                    rows.append(f"| Link | {display} |")

        return rows

    def _pretty_type(self, entity_type: str) -> str:
        """Convert entity type to pretty display name."""
        type_names = {
            "capability": "Capability",
            "user_story": "User Story",
            "outcome": "Outcome",
        }
        return type_names.get(entity_type, entity_type.replace("_", " ").title())

    def _make_anchor_from_text(self, text: str) -> str:
        """Create a valid markdown anchor from any text."""
        # Convert to lowercase, replace spaces with hyphens
        anchor = text.lower().replace(" ", "-")
        # Remove characters that aren't alphanumeric or hyphens
        anchor = "".join(c for c in anchor if c.isalnum() or c == "-")
        # Remove multiple consecutive hyphens
        while "--" in anchor:
            anchor = anchor.replace("--", "-")
        # Remove leading/trailing hyphens
        return anchor.strip("-")

    def _get_sections(self) -> list[str]:
        """Get document sections, split by double newlines."""
        # Join all lines with newlines, then split into sections
        full_text = "\n".join(self.lines)
        # Split by double newlines to get sections
        sections = full_text.split("\n\n")
        return [section for section in sections if section.strip()]
