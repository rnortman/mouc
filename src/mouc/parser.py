"""YAML parser and validator for Mouc."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from .exceptions import (
    CircularDependencyError,
    MissingReferenceError,
    ParseError,
    ValidationError,
)
from .models import (
    Dependency,
    Entity,
    FeatureMap,
    FeatureMapMetadata,
)
from .schemas import FeatureMapSchema


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
    """Parser for feature map YAML files."""

    def parse_file(self, file_path: Path | str) -> FeatureMap:
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

        return self._parse_data(data)  # type: ignore[arg-type]

    def _parse_data(self, data: dict[str, Any]) -> FeatureMap:
        """Parse the loaded YAML data into a FeatureMap."""
        try:
            # Validate with Pydantic schema
            schema = FeatureMapSchema(**data)
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid YAML structure: {e}") from e

        # Convert to domain models
        metadata = FeatureMapMetadata(
            version=schema.metadata.version,
            last_updated=schema.metadata.last_updated,
            team=schema.metadata.team,
        )

        entities: list[Entity] = []

        # Handle new format: entities with explicit type
        for entity_id, entity_data in schema.entities.items():
            if not entity_data.type:
                raise ValidationError(
                    f"Entity '{entity_id}' in 'entities' section must have a 'type' field"
                )
            meta = entity_data.meta.copy() if entity_data.meta else {}

            entity = Entity(
                type=entity_data.type,
                id=entity_id,
                name=entity_data.name,
                description=entity_data.description,
                requires={Dependency.parse(s) for s in entity_data.requires},
                enables={Dependency.parse(s) for s in entity_data.enables},
                links=entity_data.links,
                tags=entity_data.tags,
                meta=meta,
            )
            entities.append(entity)

        # Handle old format: entities grouped by type
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
                )
                entities.append(entity)

        # Resolve bidirectional edges
        resolve_graph_edges(entities)

        # Create feature map
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        # Validate references
        self._validate_feature_map(feature_map)

        return feature_map

    def _validate_feature_map(self, feature_map: FeatureMap) -> None:
        """Validate the entire feature map."""
        all_ids = feature_map.get_all_ids()

        # Validate all entity dependencies (requires and enables should both reference valid IDs)
        for entity in feature_map.entities:
            for dep_id in entity.requires_ids:
                if dep_id not in all_ids:
                    raise MissingReferenceError(
                        f"{entity.type.title()} {entity.id} requires unknown entity: {dep_id}"
                    )
            for enabled_id in entity.enables_ids:
                if enabled_id not in all_ids:
                    raise MissingReferenceError(
                        f"{entity.type.title()} {entity.id} enables unknown entity: {enabled_id}"
                    )

        # Check for circular dependencies
        self._check_circular_dependencies(feature_map)

    def _check_circular_dependencies(self, feature_map: FeatureMap) -> None:
        """Check for circular dependencies in all entities."""
        for entity in feature_map.entities:
            visited: set[str] = set()
            path: list[str] = []
            if self._has_circular_dependency(feature_map, entity.id, visited, path):
                cycle = " -> ".join(path[path.index(entity.id) :] + [entity.id])
                raise CircularDependencyError(f"Circular dependency detected: {cycle}")

    def _has_circular_dependency(
        self,
        feature_map: FeatureMap,
        entity_id: str,
        visited: set[str],
        path: list[str],
    ) -> bool:
        """Recursively check for circular dependencies."""
        if entity_id in path:
            return True

        if entity_id in visited:
            return False

        visited.add(entity_id)
        path.append(entity_id)

        entity = feature_map.get_entity_by_id(entity_id)
        if entity:
            for dep_id in entity.requires_ids:
                if self._has_circular_dependency(feature_map, dep_id, visited, path):
                    return True

        path.pop()
        return False
