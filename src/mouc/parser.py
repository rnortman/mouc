"""YAML parser for Mouc feature maps."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from .exceptions import ParseError, ValidationError
from .models import (
    Dependency,
    Entity,
    FeatureMap,
    FeatureMapMetadata,
)
from .schemas import FeatureMapSchema

if TYPE_CHECKING:
    from .unified_config import UnifiedConfig


def resolve_graph_edges(entities: list[Entity]) -> None:
    """Resolve bidirectional edges: populate requires/enables on both ends.

    For each entity, if it specifies 'requires', add this entity to those entities' 'enables'.
    If it specifies 'enables', add those entities to this entity's 'requires'.

    This mutates the entities in place to ensure all edges are bidirectional.
    Lag is preserved when creating the reverse edge.
    """
    # Build a map for quick lookups
    entity_map: dict[str, Entity] = {entity.id: entity for entity in entities}

    # Process each entity's explicitly specified edges
    for entity in entities:
        # For each entity this one requires, add this entity to their enables
        for dep in list(entity.requires):
            required_entity = entity_map.get(dep.entity_id)
            if required_entity:
                # Create reverse dependency with same lag
                reverse_dep = Dependency(entity_id=entity.id, lag_days=dep.lag_days)
                required_entity.enables.add(reverse_dep)

        # For each entity this one enables, add this entity to their requires
        for dep in list(entity.enables):
            enabled_entity = entity_map.get(dep.entity_id)
            if enabled_entity:
                # Create reverse dependency with same lag
                reverse_dep = Dependency(entity_id=entity.id, lag_days=dep.lag_days)
                enabled_entity.requires.add(reverse_dep)


class FeatureMapParser:
    """Parser for feature map YAML files.

    This parser only handles YAML parsing and entity creation.
    For full feature map loading with workflow expansion and validation,
    use load_feature_map() from mouc.loader.
    """

    def parse_file(self, file_path: Path | str, config: UnifiedConfig | None = None) -> FeatureMap:
        """Parse a YAML file into a FeatureMap."""
        path = Path(file_path)
        if not path.exists():
            raise ParseError(f"File not found: {file_path}")

        try:
            with path.open(encoding="utf-8") as f:
                data: Any = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ParseError(f"Failed to parse YAML: {e}") from e

        if not isinstance(data, dict):
            raise ParseError("YAML must contain a dictionary at the root level")

        return self._parse_data(data, config)  # type: ignore[arg-type]

    def _parse_data(self, data: dict[str, Any], config: UnifiedConfig | None = None) -> FeatureMap:
        """Parse the loaded YAML data into a FeatureMap."""
        try:
            # Validate with Pydantic schema
            schema = FeatureMapSchema(**data)
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid YAML structure: {e}") from e

        # Get default entity type from config
        default_type: str | None = None
        if config and config.entity_types:
            default_type = config.entity_types.default_type

        # Convert to domain models
        metadata = FeatureMapMetadata(
            version=schema.metadata.version,
            last_updated=schema.metadata.last_updated,
            team=schema.metadata.team,
        )

        entities: list[Entity] = []

        # Handle new format: entities with explicit type
        for entity_id, entity_data in schema.entities.items():
            entity_type = entity_data.type or default_type
            if not entity_type:
                raise ValidationError(
                    f"Entity '{entity_id}' in 'entities' section must have a 'type' field "
                    "(or configure a default_type in entity_types config)"
                )
            meta = entity_data.meta.copy() if entity_data.meta else {}

            entity = Entity(
                type=entity_type,
                id=entity_id,
                name=entity_data.name,
                description=entity_data.description,
                requires={Dependency.parse(s) for s in entity_data.requires},
                enables={Dependency.parse(s) for s in entity_data.enables},
                links=entity_data.links,
                tags=entity_data.tags,
                meta=meta,
                workflow=entity_data.workflow,
                phases=entity_data.phases,
            )
            entities.append(entity)

        # Handle old format: entities grouped by type (deprecated)
        if schema.capabilities or schema.user_stories or schema.outcomes:
            sys.stderr.write(
                "WARNING: Using deprecated 3-section format (capabilities/user_stories/outcomes). "
                "Use unified 'entities' section instead. Run 'mouc convert-format' to migrate.\n"
            )

        for entity_dict, type_name in [
            (schema.capabilities, "capability"),
            (schema.user_stories, "user_story"),
            (schema.outcomes, "outcome"),
        ]:
            for entity_id, entity_data in entity_dict.items():
                # For old format, set type based on section
                meta = entity_data.meta.copy() if entity_data.meta else {}

                entity = Entity(
                    type=type_name,
                    id=entity_id,
                    name=entity_data.name,
                    description=entity_data.description,
                    requires={Dependency.parse(s) for s in entity_data.requires},
                    enables={Dependency.parse(s) for s in entity_data.enables},
                    links=entity_data.links,
                    tags=entity_data.tags,
                    meta=meta,
                    workflow=entity_data.workflow,
                    phases=entity_data.phases,
                )
                entities.append(entity)

        # Create feature map (no workflow expansion or edge resolution here)
        return FeatureMap(
            metadata=metadata,
            entities=entities,
        )
