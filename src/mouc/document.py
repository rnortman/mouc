"""Backend-agnostic document generator for Mouc."""

from __future__ import annotations

import sys
from datetime import date
from typing import TYPE_CHECKING, Any, cast

from mouc import styling
from mouc.backends.base import EntityReference
from mouc.models import Entity
from mouc.unified_config import (
    OrganizationConfig,
    UnifiedConfig,
    get_display_name,
    get_entity_type_order,
)

if TYPE_CHECKING:
    from mouc.backends.base import DocumentBackend
    from mouc.models import FeatureMap
    from mouc.unified_config import DocumentConfig

# Type aliases for organization structure
OrganizedSection = tuple[str, list[Entity]]
NestedOrganizedSection = tuple[str, list[tuple[str, list[Entity]]]]
OrganizedStructure = list[OrganizedSection] | list[NestedOrganizedSection]


def infer_timeframe_from_date(dt: date, granularity: str) -> str:
    """Convert a date to a timeframe string based on granularity.

    Args:
        dt: Date to convert
        granularity: One of "weekly", "monthly", "quarterly", "half_year", "yearly"

    Returns:
        Timeframe string (e.g., "2025w01", "2025-02", "2025q1", "2025h1", "2025")
    """
    if granularity == "weekly":
        iso_year, iso_week, _ = dt.isocalendar()
        return f"{iso_year}w{iso_week:02d}"
    if granularity == "monthly":
        return f"{dt.year}-{dt.month:02d}"
    if granularity == "quarterly":
        quarter = (dt.month - 1) // 3 + 1
        return f"{dt.year}q{quarter}"
    if granularity == "half_year":
        # July (month 7) onwards is H2, months 1-6 are H1
        half = 1 if dt.month <= 6 else 2  # noqa: PLR2004
        return f"{dt.year}h{half}"
    if granularity == "yearly":
        return str(dt.year)
    raise ValueError(f"Invalid granularity: {granularity}")


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
        config: UnifiedConfig | None = None,
    ):
        """Initialize with a feature map, backend, and optional configuration.

        Args:
            feature_map: The feature map to document
            backend: Backend implementation for format-specific rendering
            doc_config: Configuration for document organization and TOC
            config: Full unified config for entity type display names
        """
        self.feature_map = feature_map
        self.backend = backend
        self.config = config
        self.doc_config = doc_config
        # Store TOC sections to generate (default to all if no config provided)
        self.toc_sections = doc_config.toc_sections if doc_config else ["timeline", "entity_types"]
        # Store organization config (default to alpha_by_id if no config provided)
        self.organization = doc_config.organization if doc_config else OrganizationConfig()
        # Store timeline config for ToC timeline section
        self.toc_timeline_config = doc_config.toc_timeline if doc_config else None
        # Store timeline config for body organization (from organization config)
        self.body_timeline_config = self.organization.timeline if self.organization else None
        # Build anchor registry in first pass
        self.anchor_registry: dict[str, str] = {}
        # Track which entities will be rendered (populated after filtering)
        self.rendered_entity_ids: set[str] = set()

    def _get_entity_type_order(self) -> list[str]:
        """Get entity type order, falling back to config or default types."""
        if self.organization.entity_type_order:
            return self.organization.entity_type_order
        # Fall back to config-defined order or default types
        return get_entity_type_order(self.config)

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

        # Add TOC if enabled (skip if toc_sections is empty)
        if self.toc_sections:
            self._generate_toc()

        # Check for backward dependencies and add warnings if any exist
        warnings = self._check_backward_dependencies()
        if warnings:
            self.backend.add_timeline_warnings(warnings)

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

    def _get_effective_end_date(self, entity: Entity) -> tuple[str | None, date | None]:
        """Get effective timeframe string and end date for backward dependency checking.

        Priority order:
        1. Manual end_date in metadata (fixed date)
        2. Manual timeframe in metadata
        3. Scheduler's estimated_end

        Args:
            entity: Entity to get effective end date for

        Returns:
            (timeframe_string, end_date) - end_date is set when we have an actual date
        """
        granularity = (
            self.toc_timeline_config.inferred_granularity
            if self.toc_timeline_config and self.toc_timeline_config.inferred_granularity
            else "weekly"
        )

        # 1. Check for manual end_date first (highest priority)
        manual_end = entity.meta.get("end_date")
        if manual_end:
            if isinstance(manual_end, date):
                end_date = manual_end
            else:
                end_date = date.fromisoformat(manual_end)
            inferred = infer_timeframe_from_date(end_date, granularity)
            return (inferred, end_date)

        # 2. Check for manual timeframe
        manual_tf = entity.meta.get("timeframe")
        if manual_tf:
            return (manual_tf, None)

        # 3. Check for scheduler annotation
        schedule = entity.annotations.get("schedule")
        if schedule and schedule.estimated_end:
            inferred = infer_timeframe_from_date(schedule.estimated_end, granularity)
            return (inferred, schedule.estimated_end)

        return (None, None)

    def _check_backward_dependencies(self) -> list[str]:
        """Check for dependencies going backward in timeline order.

        Uses effective timeframes from manual end_date, manual timeframe, or scheduler
        estimated_end to detect backward dependencies.

        Returns:
            List of warning messages about backward dependencies
        """
        warnings: list[str] = []

        # Apply entity filters before checking
        filtered_entities = cast(
            list[Entity],
            styling.apply_entity_filters(self.feature_map.entities, self.backend.styling_context),
        )

        # Build entity lookup for dependencies that may not be in filtered list
        entity_lookup = {e.id: e for e in self.feature_map.entities}

        # Build a map of entity IDs to their effective (timeframe, end_date)
        effective_map: dict[str, tuple[str | None, date | None]] = {}
        for entity in filtered_entities:
            effective_map[entity.id] = self._get_effective_end_date(entity)

        # Also compute for dependencies that might not be in filtered set
        for entity in filtered_entities:
            for dep_id in entity.requires_ids:
                if dep_id not in effective_map:
                    dep_entity = entity_lookup.get(dep_id)
                    if dep_entity:
                        effective_map[dep_id] = self._get_effective_end_date(dep_entity)

        # Check each entity's dependencies
        for entity in filtered_entities:
            entity_tf, entity_end = effective_map.get(entity.id, (None, None))

            # Skip if entity has no timeframe (unscheduled entities can depend on anything)
            if not entity_tf:
                continue

            for dep_id in entity.requires_ids:
                dep_tf, dep_end = effective_map.get(dep_id, (None, None))

                # If dependency has no timeframe (truly unscheduled), it's backward
                if not dep_tf:
                    dep_entity = self.feature_map.get_entity_by_id(dep_id)
                    dep_name = dep_entity.name if dep_entity else dep_id
                    msg = f"`{entity.name}` ({entity_tf}) depends on `{dep_name}` (Unscheduled)"
                    warnings.append(msg)
                    sys.stderr.write(f"WARNING: Backward dependency - {msg}\n")
                    continue

                # Compare using actual dates if both have them, else lexical timeframe comparison
                is_backward = dep_end > entity_end if entity_end and dep_end else dep_tf > entity_tf

                if is_backward:
                    dep_entity = self.feature_map.get_entity_by_id(dep_id)
                    dep_name = dep_entity.name if dep_entity else dep_id
                    msg = f"`{entity.name}` ({entity_tf}) depends on `{dep_name}` ({dep_tf})"
                    warnings.append(msg)
                    sys.stderr.write(f"WARNING: Backward dependency - {msg}\n")

        return warnings

    def _generate_toc(self) -> None:
        """Generate table of contents with sections specified in toc_sections."""
        self.backend.add_section_header("Table of Contents", level=1)

        # Generate sections in the EXACT order specified in toc_sections
        for section_name in self.toc_sections:
            if section_name == "timeline":
                self._generate_timeline_section()
            elif section_name == "entity_types":
                self._generate_entity_types_toc()

    def _generate_entity_types_toc(self) -> None:
        """Generate TOC entries for all entity type sections."""
        # Get organized structure
        organized = self._organize_entities()

        # Generate TOC entries based on actual body structure
        for item in organized:
            heading, content = item

            # Add section header for this entity type
            self.backend.add_section_header(heading, level=2)

            # Check if content has subsections (nested structure)
            if content and isinstance(content[0], tuple):
                # 2-level nesting
                nested_content = cast(list[tuple[str, list[Entity]]], content)
                for subheading, entities in nested_content:
                    self.backend.add_section_header(subheading, level=3)
                    for entity in entities:
                        entity_anchor = self.anchor_registry[entity.id]
                        type_label = self.backend.format_type_label(entity)
                        self.backend.add_toc_entry(
                            entity.name, entity_anchor, level=0, suffix=type_label
                        )
            else:
                # Direct list of entities
                entity_list = cast(list[Entity], content)
                for entity in entity_list:
                    entity_anchor = self.anchor_registry[entity.id]
                    type_label = self.backend.format_type_label(entity)
                    self.backend.add_toc_entry(
                        entity.name, entity_anchor, level=0, suffix=type_label
                    )

    def _get_entity_timeframe(
        self, entity: Entity, timeline_config: Any = None
    ) -> tuple[str | None, bool]:
        """Get timeframe for entity, using manual value or inferred from schedule.

        Args:
            entity: Entity to get timeframe for
            timeline_config: TimelineConfig to use (or None)

        Returns:
            Tuple of (timeframe, is_manual) where is_manual indicates if timeframe is from metadata
        """
        # Manual timeframe takes precedence
        timeframe = entity.meta.get("timeframe")
        if timeframe:
            return (timeframe, True)

        # If no manual timeframe and inference is enabled, infer from schedule
        if timeline_config and timeline_config.infer_from_schedule:
            schedule_annotations = entity.annotations.get("schedule")
            if schedule_annotations and schedule_annotations.estimated_end:
                inferred = infer_timeframe_from_date(
                    schedule_annotations.estimated_end,
                    timeline_config.inferred_granularity,  # type: ignore[arg-type]
                )
                return (inferred, False)

        return (None, False)

    def _sort_unscheduled_entities(
        self, entities: list[Entity], timeline_config: Any = None
    ) -> list[Entity]:
        """Sort unscheduled entities by completion date or (type, id)."""
        if timeline_config and timeline_config.sort_unscheduled_by_completion:

            def sort_key(e: Entity) -> tuple[date, str, str]:
                schedule = e.annotations.get("schedule")
                end_date = schedule.estimated_end if schedule else None
                # Use max date for None to sort to end
                sort_date = end_date if end_date else date.max
                return (sort_date, e.type, e.id)

            return sorted(entities, key=sort_key)
        return sorted(entities, key=lambda e: (e.type, e.id))

    def _generate_timeline_section(self) -> None:
        """Generate timeline section grouped by timeframe."""
        all_entities = self.feature_map.entities

        # Apply entity filters before grouping
        filtered_entities = cast(
            list[Entity], styling.apply_entity_filters(all_entities, self.backend.styling_context)
        )

        # Group entities by timeframe (with confirmed/inferred separation if configured)
        timeframe_groups = self._group_entities_by_timeframe(
            filtered_entities, self.toc_timeline_config
        )

        # Separate scheduled from unscheduled
        scheduled_groups = {k: v for k, v in timeframe_groups.items() if k != "Unscheduled"}
        unscheduled = timeframe_groups.get("Unscheduled")

        # If no entities have timeframes, don't generate the timeline section
        if not scheduled_groups:
            return

        self.backend.add_section_header("Timeline", level=2)

        # Build sections using helper (handles confirmed/inferred flattening)
        sections = self._build_timeframe_subsections(scheduled_groups, self.toc_timeline_config)

        # Generate timeline entries for each section
        for section_name, entities in sections:
            self.backend.add_section_header(section_name, level=3)
            sorted_entities = sorted(entities, key=lambda e: (e.type, e.id))
            for entity in sorted_entities:
                anchor = self.anchor_registry[entity.id]
                type_label = self.backend.format_type_label(entity)
                self.backend.add_toc_entry(entity.name, anchor, level=0, suffix=type_label)

        # Add unscheduled section if there are any
        if unscheduled:
            self.backend.add_section_header("Unscheduled", level=3)
            # Unscheduled is either list[Entity] or dict[str, list[Entity]]
            if isinstance(unscheduled, dict):
                # Has confirmed/inferred separation
                uns_dict = cast(dict[str, list[Entity]], unscheduled)
                all_unscheduled: list[Entity] = uns_dict.get("confirmed", []) + uns_dict.get(
                    "inferred", []
                )
            else:
                all_unscheduled = cast(list[Entity], unscheduled)

            sorted_entities = self._sort_unscheduled_entities(
                all_unscheduled, self.toc_timeline_config
            )
            for entity in sorted_entities:
                anchor = self.anchor_registry[entity.id]
                type_label = self.backend.format_type_label(entity)
                self.backend.add_toc_entry(entity.name, anchor, level=0, suffix=type_label)

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

    def _group_entities_by_timeframe(
        self, entities: list[Entity], timeline_config: Any = None
    ) -> dict[str, Any]:
        """Group entities by timeframe, optionally separating confirmed vs inferred.

        Args:
            entities: Entities to group
            timeline_config: Timeline configuration (if None, uses manual timeframes only)

        Returns:
            If separate_confirmed_inferred is False:
                Dict of {timeframe: [entities]}
            If separate_confirmed_inferred is True:
                Dict of {timeframe: {"confirmed": [entities], "inferred": [entities]}}
        """
        separate = timeline_config.separate_confirmed_inferred if timeline_config else False

        if separate:
            # Nested structure: timeframe -> source -> entities
            groups: dict[str, dict[str, list[Entity]]] = {}
            for entity in entities:
                timeframe, is_manual = self._get_entity_timeframe(entity, timeline_config)
                tf_key = timeframe if timeframe else "Unscheduled"
                source = "confirmed" if is_manual else "inferred"

                if tf_key not in groups:
                    groups[tf_key] = {"confirmed": [], "inferred": []}
                groups[tf_key][source].append(entity)
            return groups
        # Simple structure: timeframe -> entities
        simple_groups: dict[str, list[Entity]] = {}
        for entity in entities:
            timeframe, _ = self._get_entity_timeframe(entity, timeline_config)
            tf_key = timeframe if timeframe else "Unscheduled"

            if tf_key not in simple_groups:
                simple_groups[tf_key] = []
            simple_groups[tf_key].append(entity)
        return simple_groups

    def _get_type_display_name(self, entity_type: str) -> str:
        """Get plural display name for entity type (used in section headers)."""
        # Get singular display name from config
        singular = get_display_name(entity_type, self.config)
        # Simple pluralization: add 's' (or 'ies' for words ending in 'y')
        if singular.endswith("y") and len(singular) > 1 and singular[-2] not in "aeiou":
            return singular[:-1] + "ies"
        return singular + "s"

    def _build_timeframe_subsections(
        self, timeframe_groups: dict[str, Any], timeline_config: Any = None
    ) -> list[tuple[str, list[Entity]]]:
        """Build subsections from timeframe groups, handling confirmed/inferred separation.

        Args:
            timeframe_groups: Output from _group_entities_by_timeframe()
            timeline_config: TimelineConfig to check for separate_confirmed_inferred flag

        Returns:
            List of (heading, entities) where heading includes source if separate_confirmed_inferred
        """
        sorted_timeframes = sorted(timeframe_groups.keys())

        if timeline_config and timeline_config.separate_confirmed_inferred:
            # Flatten to single level: confirmed and inferred sections at same level
            result: list[tuple[str, list[Entity]]] = []
            for tf in sorted_timeframes:
                source_groups = timeframe_groups[tf]
                # Add confirmed section if not empty
                if source_groups["confirmed"]:
                    result.append(
                        (
                            f"{tf} (confirmed)",
                            sorted(source_groups["confirmed"], key=lambda e: e.id),
                        )
                    )
                # Add inferred section if not empty
                if source_groups["inferred"]:
                    result.append(
                        (f"{tf} (inferred)", sorted(source_groups["inferred"], key=lambda e: e.id))
                    )
            return result
        # Simple structure: timeframe -> entities
        return [(tf, sorted(timeframe_groups[tf], key=lambda e: e.id)) for tf in sorted_timeframes]

    def _organize_entities(  # noqa: PLR0911, PLR0912, PLR0915
        self,
    ) -> OrganizedStructure:
        """Organize entities based on configuration.

        Returns:
            For no secondary grouping: list of (heading, entities)
            For secondary grouping: list of (primary_heading, [(secondary_heading, entities)])
        """
        all_entities = self.feature_map.entities

        # Apply entity filters before organization
        filtered_entities = cast(
            list[Entity], styling.apply_entity_filters(all_entities, self.backend.styling_context)
        )

        # Track which entities will be rendered (for filtered reference handling)
        self.rendered_entity_ids = {e.id for e in filtered_entities}

        # Handle primary grouping
        if self.organization.primary in ("alpha_by_id", "yaml_order"):
            # Single flat section with all entities
            sorted_entities = self._get_sorted_entities(filtered_entities)
            if self.organization.secondary == "by_timeframe":
                # Group by timeframe within the flat list
                timeframe_groups = self._group_entities_by_timeframe(
                    sorted_entities, self.body_timeline_config
                )
                subsections = self._build_timeframe_subsections(
                    timeframe_groups, self.body_timeline_config
                )
                return cast(OrganizedStructure, [("Entities", subsections)])
            if self.organization.secondary == "by_type":
                # Group by type within the flat list
                type_groups = self._group_entities_by_type(sorted_entities)
                ordered_types = self._get_entity_type_order()
                subsections = [
                    (self._get_type_display_name(t), sorted(type_groups[t], key=lambda e: e.id))
                    for t in ordered_types
                    if t in type_groups
                ]
                return [("Entities", subsections)]
            # No secondary grouping
            return [("Entities", sorted_entities)]

        if self.organization.primary == "by_type":
            type_groups = self._group_entities_by_type(filtered_entities)
            ordered_types = self._get_entity_type_order()

            if self.organization.secondary == "by_timeframe":
                # Primary: type sections, Secondary: timeframe subsections
                result_list: list[Any] = []
                for entity_type in ordered_types:
                    if entity_type not in type_groups:
                        continue
                    type_entities = type_groups[entity_type]
                    timeframe_groups = self._group_entities_by_timeframe(
                        type_entities, self.body_timeline_config
                    )
                    subsections = self._build_timeframe_subsections(
                        timeframe_groups, self.body_timeline_config
                    )
                    result_list.append((self._get_type_display_name(entity_type), subsections))
                return cast(OrganizedStructure, result_list)
            # No secondary grouping, just sorted by ID within each type
            result_simple: list[OrganizedSection] = []
            for entity_type in ordered_types:
                if entity_type not in type_groups:
                    continue
                sorted_entities = sorted(type_groups[entity_type], key=lambda e: e.id)
                result_simple.append((self._get_type_display_name(entity_type), sorted_entities))
            return result_simple

        if self.organization.primary == "by_timeframe":
            timeframe_groups = self._group_entities_by_timeframe(
                filtered_entities, self.body_timeline_config
            )

            if self.organization.secondary == "by_type":
                # Primary: timeframe sections, Secondary: type subsections
                # With separate_confirmed_inferred, flatten confirmed/inferred to same level
                if (
                    self.body_timeline_config
                    and self.body_timeline_config.separate_confirmed_inferred
                ):
                    result_flat_sources: list[NestedOrganizedSection] = []
                    sorted_timeframes = sorted(timeframe_groups.keys())
                    for timeframe in sorted_timeframes:
                        source_groups = timeframe_groups[timeframe]
                        # Create separate sections for confirmed and inferred at same level
                        for source in ["confirmed", "inferred"]:
                            if source_groups[source]:
                                type_groups = self._group_entities_by_type(source_groups[source])
                                ordered_types = self._get_entity_type_order()
                                type_subsections: list[tuple[str, list[Entity]]] = [
                                    (
                                        self._get_type_display_name(t),
                                        sorted(type_groups[t], key=lambda e: e.id),
                                    )
                                    for t in ordered_types
                                    if t in type_groups
                                ]
                                if type_subsections:
                                    result_flat_sources.append(
                                        (f"{timeframe} ({source})", type_subsections)
                                    )
                    return result_flat_sources
                result_nested: list[NestedOrganizedSection] = []
                sorted_timeframes = sorted(timeframe_groups.keys())
                for timeframe in sorted_timeframes:
                    tf_entities = timeframe_groups[timeframe]
                    type_groups = self._group_entities_by_type(tf_entities)
                    ordered_types = self._get_entity_type_order()
                    subsections_list: list[tuple[str, list[Entity]]] = [
                        (
                            self._get_type_display_name(t),
                            sorted(type_groups[t], key=lambda e: e.id),
                        )
                        for t in ordered_types
                        if t in type_groups
                    ]
                    result_nested.append((timeframe, subsections_list))
                return result_nested

            # No secondary grouping - use helper which handles confirmed/inferred flattening
            return self._build_timeframe_subsections(timeframe_groups, self.body_timeline_config)

        # Default fallback
        return [("Entities", sorted(filtered_entities, key=lambda e: e.id))]

    def _generate_organized_sections(self) -> None:
        """Generate document body sections based on organization config."""
        organized = self._organize_entities()

        for item in organized:
            heading, content = item
            # Check if content is a list of entities or a list of subsections
            if content and isinstance(content[0], tuple):
                # 2-level nesting: h2 section -> h3 subsection -> h4 entity
                nested_content = cast(list[tuple[str, list[Entity]]], content)
                self.backend.add_section_header(heading, level=1)  # h2 section
                for subheading, entities in nested_content:
                    self.backend.add_section_header(subheading, level=2)  # h3 subsection
                    for entity in entities:
                        # Entities under h3 subsection should be h4
                        self._render_entity(entity, level=4)
            else:
                # Direct list of entities (single-level organization)
                # Structure: h2 section -> h3 entity
                entity_list = cast(list[Entity], content)
                self.backend.add_section_header(heading, level=1)  # h2 section
                for entity in entity_list:
                    # Entities directly under h2 section should be h3
                    self._render_entity(entity, level=3)

    def _render_entity(self, entity: Entity, level: int) -> None:
        """Render a single entity using the backend.

        Args:
            entity: Entity to render
            level: Direct heading level for the entity (3=h3, 4=h4, etc.)
        """
        # Get anchor for this entity
        anchor_id = self.anchor_registry[entity.id]

        # Apply styling to get type label and metadata
        styled_type_label = self.backend.format_type_label(entity)
        # Create a copy of entity.meta and add entity fields before styling
        base_metadata = entity.meta.copy()
        base_metadata["id"] = entity.id
        if entity.tags:
            base_metadata["tags"] = entity.tags
        if entity.links:
            base_metadata["links"] = entity.links
        display_metadata: dict[str, Any] = styling.apply_metadata_styles(
            entity, self.backend.styling_context, base_metadata
        )

        # Get filtered reference handling config (default: "mark")
        filtered_handling = (
            self.doc_config.filtered_reference_handling if self.doc_config else "mark"
        )

        # Build requires references
        requires_refs: list[EntityReference] = []
        for dep_id in sorted(entity.requires_ids):
            dep = self.feature_map.get_entity_by_id(dep_id)
            if dep:
                if dep_id in self.rendered_entity_ids:
                    # Normal link - entity exists and will be rendered
                    requires_refs.append(
                        EntityReference(
                            entity_id=dep_id,
                            entity_name=dep.name,
                            entity_type=dep.type,
                            anchor_id=self.anchor_registry[dep_id],
                        )
                    )
                elif filtered_handling == "mark":
                    # Entity exists but was filtered out - mark it
                    requires_refs.append(
                        EntityReference(
                            entity_id=dep_id,
                            entity_name=f"{dep.name} (filtered)",
                            entity_type=dep.type,
                            anchor_id="",
                        )
                    )
                # If filtered_handling == "omit", skip adding reference
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
        for dep_id in sorted(entity.enables_ids):
            dep = self.feature_map.get_entity_by_id(dep_id)
            if dep:
                if dep_id in self.rendered_entity_ids:
                    # Normal - entity exists and will be rendered
                    sorted_dependents.append((dep.type, dep_id, dep))
                elif filtered_handling == "mark":
                    # Entity exists but was filtered out - mark it
                    enables_refs.append(
                        EntityReference(
                            entity_id=dep_id,
                            entity_name=f"{dep.name} (filtered)",
                            entity_type=dep.type,
                            anchor_id="",
                        )
                    )
                # If filtered_handling == "omit", skip adding reference

        for _, dep_id, dep in sorted(sorted_dependents):
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
            level=level,
        )
