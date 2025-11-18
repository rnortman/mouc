"""Base abstractions for document generation backends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from mouc.models import Entity, FeatureMapMetadata, Link

if TYPE_CHECKING:
    from mouc.styling import StylingContext


@dataclass
class EntityReference:
    """Cross-reference to another entity in the document."""

    entity_id: str
    entity_name: str
    entity_type: str
    anchor_id: str


@dataclass
class SectionStructure:
    """Represents a section in the document hierarchy."""

    heading: str
    level: int  # 1=top-level, 2=nested, etc.
    anchor_id: str | None = None
    entities: list[Entity] | None = None
    subsections: list[SectionStructure] | None = None


AnchorFunction = Callable[[str, str], str]
"""Type for anchor generation functions: (entity_id, entity_name) -> anchor_id"""


class DocumentBackend(Protocol):
    """Protocol for document generation backends.

    Backends are responsible for rendering document content in a specific
    format (markdown, docx, html, etc.). The DocumentGenerator orchestrates
    content organization and delegates format-specific rendering to the backend.
    """

    styling_context: StylingContext

    def create_document(self) -> None:
        """Initialize a new document."""
        ...

    def add_header(self, metadata: FeatureMapMetadata) -> None:
        """Add document header with feature map metadata."""
        ...

    def add_section_header(self, text: str, level: int) -> str:
        """Add a section header at the specified level.

        Args:
            text: Section heading text
            level: Heading level (1=top-level, 2=subsection, etc.)

        Returns:
            Anchor/bookmark ID for cross-referencing this section
        """
        ...

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
        """Render a complete entity with all its components.

        Args:
            entity: The entity to render
            anchor_id: Pre-generated anchor/bookmark ID for this entity
            styled_type_label: Type label after styling plugin processing
            display_metadata: Metadata dict after styling plugin processing
            requires_refs: References to required entities
            enables_refs: References to enabled entities
            level: Semantic heading level (1=h1 title, 2=h2 section, 3=h3 entity/subsection, 4=h4 entity)
        """
        ...

    def add_toc_entry(
        self, text: str, anchor_id: str, level: int, suffix: str | None = None
    ) -> None:
        """Add a table of contents entry.

        Args:
            text: TOC entry text (link text)
            anchor_id: Anchor/bookmark to link to
            level: Nesting level in TOC
            suffix: Optional suffix to append after the link (e.g., type label)
        """
        ...

    def add_timeline_warnings(self, warnings: list[str]) -> None:
        """Add timeline dependency warnings section.

        Args:
            warnings: List of warning messages about backward dependencies
        """
        ...

    def finalize(self) -> str | bytes:
        """Finalize and return the document.

        Returns:
            Document content (string for text formats, bytes for binary formats)
        """
        ...

    def make_anchor(self, entity_id: str, entity_name: str) -> str:
        """Create a format-specific anchor/bookmark identifier.

        Args:
            entity_id: Unique entity identifier
            entity_name: Human-readable entity name

        Returns:
            Format-specific anchor/bookmark ID
        """
        ...

    def format_link(self, link: Link) -> str:
        """Format an external link for this backend.

        Args:
            link: Link object to format

        Returns:
            Backend-specific link representation
        """
        ...

    def format_internal_reference(self, ref: EntityReference) -> str:
        """Format an internal cross-reference to another entity.

        Args:
            ref: Reference to another entity in the document

        Returns:
            Backend-specific cross-reference representation
        """
        ...

    def format_type_label(self, entity: Entity) -> str:
        """Format a type label for an entity.

        Args:
            entity: Entity to get type label for

        Returns:
            Formatted type label string (may be empty if styled to hide)
        """
        ...
