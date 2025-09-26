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
    Entity,
    FeatureMap,
    FeatureMapMetadata,
)
from .schemas import FeatureMapSchema


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
                dependencies=entity_data.dependencies,
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
                    dependencies=entity_data.dependencies,
                    links=entity_data.links,
                    tags=entity_data.tags,
                    meta=meta,
                )
                entities.append(entity)

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

        # Validate all entity dependencies
        for entity in feature_map.entities:
            for dep_id in entity.dependencies:
                if dep_id not in all_ids:
                    raise MissingReferenceError(
                        f"{entity.type.title()} {entity.id} depends on unknown entity: {dep_id}"
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
            for dep_id in entity.dependencies:
                if self._has_circular_dependency(feature_map, dep_id, visited, path):
                    return True

        path.pop()
        return False
