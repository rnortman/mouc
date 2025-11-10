"""Backend-agnostic document generator for Mouc."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, cast

from mouc import styling
from mouc.backends.base import EntityReference
from mouc.models import Entity
from mouc.unified_config import OrganizationConfig

if TYPE_CHECKING:
    from mouc.backends.base import DocumentBackend
    from mouc.models import FeatureMap
    from mouc.unified_config import DocumentConfig

# Type aliases for organization structure
OrganizedSection = tuple[str, list[Entity]]
NestedOrganizedSection = tuple[str, list[tuple[str, list[Entity]]]]
OrganizedStructure = list[OrganizedSection] | list[NestedOrganizedSection]


class DocumentGenerator:
    """Generate documentation from a feature map using a pluggable backend.

    This class handles content organization and structure, delegating
    format-specific rendering to the backend implementation.
    """

    def __init__(
        self,
        feature_map: FeatureMap,
        backend: DocumentBackend,
        doc_config: DocumentConfig | None = None,
    ):
        """Initialize with a feature map, backend, and optional configuration.

        Args:
            feature_map: The feature map to document
            backend: Backend implementation for format-specific rendering
            doc_config: Configuration for document organization and TOC
        """
        self.feature_map = feature_map
        self.backend = backend
        # Store TOC sections to generate (default to all if no config provided)
        self.toc_sections = (
            doc_config.toc_sections
            if doc_config
            else ["timeline", "capabilities", "user_stories", "outcomes"]
        )
        # Store organization config (default to alpha_by_id if no config provided)
        self.organization = doc_config.organization if doc_config else OrganizationConfig()
        # Build anchor registry in first pass
        self.anchor_registry: dict[str, str] = {}

    def generate(self) -> str | bytes:
        """Generate complete documentation.

        Returns:
            Document content (format depends on backend)
        """
        self.backend.create_document()

        # First pass: Build anchor registry for all entities
        self._build_anchor_registry()

        # Add header
        self.backend.add_header(self.feature_map.metadata)

        # Add timeline before TOC if included (maintains original ordering)
        if "timeline" in self.toc_sections:
            self._generate_timeline()
            warnings = self._check_backward_dependencies()
            self.backend.add_timeline_warnings(warnings)

        # Add TOC if enabled (skip if toc_sections is empty)
        if self.toc_sections:
            self._generate_toc()

        # Generate body sections based on organization config
        self._generate_organized_sections()

        return self.backend.finalize()

    def _build_anchor_registry(self) -> None:
        """Build registry of anchors for all entities (first pass)."""
        for entity in self.feature_map.entities:
            anchor = self.backend.make_anchor(entity.id, entity.name)
            self.anchor_registry[entity.id] = anchor

    def _generate_timeline(self) -> None:
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
            return

        self.backend.add_section_header("Timeline", level=1)

        # Sort timeframes lexically for consistent ordering
        sorted_timeframes = sorted(timeframe_groups.keys())

        # Generate timeline entries
        for timeframe in sorted_timeframes:
            self.backend.add_section_header(timeframe, level=2)

            entities = sorted(timeframe_groups[timeframe], key=lambda e: (e.type, e.id))
            for entity in entities:
                anchor = self.anchor_registry[entity.id]
                type_label = self.backend.format_type_label(entity)
                # Add TOC-style entry linking to entity
                self.backend.add_toc_entry(entity.name, anchor, level=0, suffix=type_label)

        # Add unscheduled section if there are any
        if unscheduled:
            self.backend.add_section_header("Unscheduled", level=2)

            entities = sorted(unscheduled, key=lambda e: (e.type, e.id))
            for entity in entities:
                anchor = self.anchor_registry[entity.id]
                type_label = self.backend.format_type_label(entity)
                self.backend.add_toc_entry(entity.name, anchor, level=0, suffix=type_label)

    def _check_backward_dependencies(self) -> list[str]:
        """Check for dependencies going backward in timeline order.

        Returns:
            List of warning messages about backward dependencies
        """
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

        return warnings

    def _generate_toc(self) -> None:
        """Generate table of contents based on body organization."""
        self.backend.add_section_header("Table of Contents", level=1)

        # Get organized structure
        organized = self._organize_entities()

        # Generate TOC entries based on actual body structure
        for item in organized:
            heading, content = item
            section_anchor = self.backend.make_anchor("", heading)

            # Check if content has subsections (nested structure)
            if content and isinstance(content[0], tuple):
                # Has subsections - add top-level link
                nested_content = cast(list[tuple[str, list[Entity]]], content)
                self.backend.add_toc_entry(heading, section_anchor, level=0)
                for subheading, entities in nested_content:
                    subsection_anchor = self.backend.make_anchor("", subheading)
                    self.backend.add_toc_entry(subheading, subsection_anchor, level=1)
                    for entity in entities:
                        entity_anchor = self.anchor_registry[entity.id]
                        type_label = self.backend.format_type_label(entity)
                        self.backend.add_toc_entry(
                            entity.name, entity_anchor, level=2, suffix=type_label
                        )
            else:
                # Direct list of entities
                entity_list = cast(list[Entity], content)
                self.backend.add_toc_entry(heading, section_anchor, level=0)
                for entity in entity_list:
                    entity_anchor = self.anchor_registry[entity.id]
                    type_label = self.backend.format_type_label(entity)
                    self.backend.add_toc_entry(
                        entity.name, entity_anchor, level=1, suffix=type_label
                    )

    def _get_sorted_entities(self, entities: list[Entity]) -> list[Entity]:
        """Sort entities based on the primary organization mode."""
        if self.organization.primary == "alpha_by_id":
            return sorted(entities, key=lambda e: e.id)
        if self.organization.primary == "yaml_order":
            # Entities are already in YAML order in the list
            return entities
        # For by_type and by_timeframe, sorting happens in grouping
        return sorted(entities, key=lambda e: e.id)

    def _group_entities_by_type(self, entities: list[Entity]) -> dict[str, list[Entity]]:
        """Group entities by their type."""
        groups: dict[str, list[Entity]] = {}
        for entity in entities:
            if entity.type not in groups:
                groups[entity.type] = []
            groups[entity.type].append(entity)
        return groups

    def _group_entities_by_timeframe(self, entities: list[Entity]) -> dict[str, list[Entity]]:
        """Group entities by their timeframe metadata."""
        groups: dict[str, list[Entity]] = {}
        for entity in entities:
            timeframe = entity.meta.get("timeframe", "Unscheduled")
            if timeframe not in groups:
                groups[timeframe] = []
            groups[timeframe].append(entity)
        return groups

    def _get_type_display_name(self, entity_type: str) -> str:
        """Get display name for entity type."""
        type_names = {
            "capability": "Capabilities",
            "user_story": "User Stories",
            "outcome": "Outcomes",
        }
        return type_names.get(entity_type, entity_type.title())

    def _organize_entities(  # noqa: PLR0911, PLR0912
        self,
    ) -> OrganizedStructure:
        """Organize entities based on configuration.

        Returns:
            For no secondary grouping: list of (heading, entities)
            For secondary grouping: list of (primary_heading, [(secondary_heading, entities)])
        """
        all_entities = self.feature_map.entities

        # Handle primary grouping
        if self.organization.primary in ("alpha_by_id", "yaml_order"):
            # Single flat section with all entities
            sorted_entities = self._get_sorted_entities(all_entities)
            if self.organization.secondary == "by_timeframe":
                # Group by timeframe within the flat list
                timeframe_groups = self._group_entities_by_timeframe(sorted_entities)
                sorted_timeframes = sorted(timeframe_groups.keys())
                subsections = [
                    (tf, sorted(timeframe_groups[tf], key=lambda e: e.id))
                    for tf in sorted_timeframes
                ]
                return [("Entities", subsections)]
            if self.organization.secondary == "by_type":
                # Group by type within the flat list
                type_groups = self._group_entities_by_type(sorted_entities)
                ordered_types = self.organization.entity_type_order
                subsections = [
                    (self._get_type_display_name(t), sorted(type_groups[t], key=lambda e: e.id))
                    for t in ordered_types
                    if t in type_groups
                ]
                return [("Entities", subsections)]
            # No secondary grouping
            return [("Entities", sorted_entities)]

        if self.organization.primary == "by_type":
            type_groups = self._group_entities_by_type(all_entities)
            ordered_types = self.organization.entity_type_order

            if self.organization.secondary == "by_timeframe":
                # Primary: type sections, Secondary: timeframe subsections
                result: list[NestedOrganizedSection] = []
                for entity_type in ordered_types:
                    if entity_type not in type_groups:
                        continue
                    type_entities = type_groups[entity_type]
                    timeframe_groups = self._group_entities_by_timeframe(type_entities)
                    sorted_timeframes = sorted(timeframe_groups.keys())
                    subsections: list[tuple[str, list[Entity]]] = [
                        (tf, sorted(timeframe_groups[tf], key=lambda e: e.id))
                        for tf in sorted_timeframes
                    ]
                    result.append((self._get_type_display_name(entity_type), subsections))
                return result
            # No secondary grouping, just sorted by ID within each type
            result_simple: list[OrganizedSection] = []
            for entity_type in ordered_types:
                if entity_type not in type_groups:
                    continue
                sorted_entities = sorted(type_groups[entity_type], key=lambda e: e.id)
                result_simple.append((self._get_type_display_name(entity_type), sorted_entities))
            return result_simple

        if self.organization.primary == "by_timeframe":
            timeframe_groups = self._group_entities_by_timeframe(all_entities)
            sorted_timeframes = sorted(timeframe_groups.keys())

            if self.organization.secondary == "by_type":
                # Primary: timeframe sections, Secondary: type subsections
                result_nested: list[NestedOrganizedSection] = []
                for timeframe in sorted_timeframes:
                    tf_entities = timeframe_groups[timeframe]
                    type_groups = self._group_entities_by_type(tf_entities)
                    ordered_types = self.organization.entity_type_order
                    subsections_list: list[tuple[str, list[Entity]]] = [
                        (self._get_type_display_name(t), sorted(type_groups[t], key=lambda e: e.id))
                        for t in ordered_types
                        if t in type_groups
                    ]
                    result_nested.append((timeframe, subsections_list))
                return result_nested
            # No secondary grouping, just sorted by ID within each timeframe
            result_flat: list[OrganizedSection] = []
            for timeframe in sorted_timeframes:
                sorted_entities = sorted(timeframe_groups[timeframe], key=lambda e: e.id)
                result_flat.append((timeframe, sorted_entities))
            return result_flat

        # Default fallback
        return [("Entities", sorted(all_entities, key=lambda e: e.id))]

    def _generate_organized_sections(self) -> None:
        """Generate document body sections based on organization config."""
        organized = self._organize_entities()

        for item in organized:
            heading, content = item
            # Check if content is a list of entities or a list of subsections
            if content and isinstance(content[0], tuple):
                # Has subsections - nested structure
                nested_content = cast(list[tuple[str, list[Entity]]], content)
                self.backend.add_section_header(heading, level=1)
                for subheading, entities in nested_content:
                    self.backend.add_section_header(subheading, level=2)
                    for entity in entities:
                        self._render_entity(entity)
            else:
                # Direct list of entities
                entity_list = cast(list[Entity], content)
                self.backend.add_section_header(heading, level=1)
                for entity in entity_list:
                    self._render_entity(entity)

    def _render_entity(self, entity: Entity) -> None:
        """Render a single entity using the backend.

        Args:
            entity: Entity to render
        """
        # Get anchor for this entity
        anchor_id = self.anchor_registry[entity.id]

        # Apply styling to get type label and metadata
        styled_type_label = self.backend.format_type_label(entity)
        styling_context = styling.create_styling_context(self.feature_map)
        display_metadata: dict[str, Any] = styling.apply_metadata_styles(
            entity, styling_context, entity.meta
        )

        # Build requires references
        requires_refs: list[EntityReference] = []
        for dep_id in sorted(entity.requires):
            dep = self.feature_map.get_entity_by_id(dep_id)
            if dep:
                requires_refs.append(
                    EntityReference(
                        entity_id=dep_id,
                        entity_name=dep.name,
                        entity_type=dep.type,
                        anchor_id=self.anchor_registry[dep_id],
                    )
                )
            else:
                # Handle missing dependency
                requires_refs.append(
                    EntityReference(
                        entity_id=dep_id,
                        entity_name=f"{dep_id} ⚠️ (missing)",
                        entity_type="unknown",
                        anchor_id="",
                    )
                )

        # Build enables references
        enables_refs: list[EntityReference] = []
        sorted_dependents: list[tuple[str, str, Entity]] = []
        for dep_id in sorted(entity.enables):
            dep = self.feature_map.get_entity_by_id(dep_id)
            if dep:
                sorted_dependents.append((dep.type, dep_id, dep))

        for _dep_type, dep_id, dep in sorted(sorted_dependents):
            enables_refs.append(
                EntityReference(
                    entity_id=dep_id,
                    entity_name=dep.name,
                    entity_type=dep.type,
                    anchor_id=self.anchor_registry[dep_id],
                )
            )

        # Delegate to backend
        self.backend.add_entity(
            entity=entity,
            anchor_id=anchor_id,
            styled_type_label=styled_type_label,
            display_metadata=display_metadata,
            requires_refs=requires_refs,
            enables_refs=enables_refs,
        )
