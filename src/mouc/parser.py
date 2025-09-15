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
    Capability,
    FeatureMap,
    FeatureMapMetadata,
    Outcome,
    UserStory,
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

        capabilities = {
            cap_id: Capability(
                id=cap_id,
                name=cap_data.name,
                description=cap_data.description,
                dependencies=cap_data.dependencies,
                links=cap_data.links,
                tags=cap_data.tags,
            )
            for cap_id, cap_data in schema.capabilities.items()
        }

        user_stories = {
            story_id: UserStory(
                id=story_id,
                name=story_data.name,
                description=story_data.description,
                requires=story_data.requires,
                requestor=story_data.requestor,
                links=story_data.links,
                tags=story_data.tags,
            )
            for story_id, story_data in schema.user_stories.items()
        }

        outcomes = {
            outcome_id: Outcome(
                id=outcome_id,
                name=outcome_data.name,
                description=outcome_data.description,
                enables=outcome_data.enables,
                links=outcome_data.links,
                target_date=outcome_data.target_date,
                tags=outcome_data.tags,
            )
            for outcome_id, outcome_data in schema.outcomes.items()
        }

        # Create feature map
        feature_map = FeatureMap(
            metadata=metadata,
            capabilities=capabilities,
            user_stories=user_stories,
            outcomes=outcomes,
        )

        # Validate references
        self._validate_feature_map(feature_map)

        return feature_map

    def _validate_feature_map(self, feature_map: FeatureMap) -> None:
        """Validate the entire feature map."""

        # Validate capability dependencies
        for cap in feature_map.capabilities.values():
            for dep_id in cap.dependencies:
                if dep_id not in feature_map.capabilities:
                    raise MissingReferenceError(
                        f"Capability {cap.id} depends on unknown capability: {dep_id}"
                    )

        # Validate user story requirements
        for story in feature_map.user_stories.values():
            for req_id in story.requires:
                if req_id not in feature_map.capabilities:
                    raise MissingReferenceError(
                        f"User story {story.id} requires unknown capability: {req_id}"
                    )

        # Validate outcome enablers
        for outcome in feature_map.outcomes.values():
            for story_id in outcome.enables:
                if story_id not in feature_map.user_stories:
                    raise MissingReferenceError(
                        f"Outcome {outcome.id} enables unknown user story: {story_id}"
                    )

        # Check for circular dependencies
        self._check_circular_dependencies(feature_map)

    def _check_circular_dependencies(self, feature_map: FeatureMap) -> None:
        """Check for circular dependencies in capabilities."""
        for cap_id in feature_map.capabilities:
            visited: set[str] = set()
            path: list[str] = []
            if self._has_circular_dependency(feature_map, cap_id, visited, path):
                cycle = " -> ".join(path[path.index(cap_id) :] + [cap_id])
                raise CircularDependencyError(f"Circular dependency detected: {cycle}")

    def _has_circular_dependency(
        self,
        feature_map: FeatureMap,
        cap_id: str,
        visited: set[str],
        path: list[str],
    ) -> bool:
        """Recursively check for circular dependencies."""
        if cap_id in path:
            return True

        if cap_id in visited:
            return False

        visited.add(cap_id)
        path.append(cap_id)

        cap = feature_map.capabilities.get(cap_id)
        if cap:
            for dep_id in cap.dependencies:
                if self._has_circular_dependency(feature_map, dep_id, visited, path):
                    return True

        path.pop()
        return False
