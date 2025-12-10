"""Feature map loading with full processing pipeline."""

from __future__ import annotations

from pathlib import Path

from . import context
from .exceptions import CircularDependencyError, MissingReferenceError, ValidationError
from .models import FeatureMap
from .parser import FeatureMapParser, resolve_graph_edges
from .unified_config import (
    UnifiedConfig,
    WorkflowsConfig,
    get_valid_entity_types,
    load_unified_config,
)
from .workflows import expand_workflows


def _discover_config(
    feature_map_path: Path,
    config_path: Path | None = None,
) -> UnifiedConfig | None:
    """Discover unified config from various locations.

    Search order:
    1. Explicit config_path argument
    2. Global context (set via CLI --config)
    3. feature_map directory / mouc_config.yaml
    4. Current directory / mouc_config.yaml
    """
    # 1. Explicit argument
    if config_path and config_path.exists():
        return load_unified_config(config_path)

    # 2. Global context
    ctx_config = context.get_config_path()
    if ctx_config and ctx_config.exists():
        return load_unified_config(ctx_config)

    # 3. Feature map directory
    feature_map_dir = Path(feature_map_path).parent
    dir_config = feature_map_dir / "mouc_config.yaml"
    if dir_config.exists():
        return load_unified_config(dir_config)

    # 4. Current directory
    cwd_config = Path("mouc_config.yaml")
    if cwd_config.exists():
        return load_unified_config(cwd_config)

    return None


def load_feature_map(
    path: Path | str,
    config_path: Path | None = None,
    *,
    workflows_config: WorkflowsConfig | None = None,
    config: UnifiedConfig | None = None,
) -> FeatureMap:
    """Load and fully process a feature map.

    This is the main entry point for loading feature maps. It handles:
    1. YAML parsing
    2. Bidirectional edge resolution (pre-workflow)
    3. Workflow expansion
    4. Bidirectional edge resolution (post-workflow)
    5. Validation (references, cycles, and entity types)

    Args:
        path: Path to the feature map YAML file
        config_path: Optional explicit path to config file
        workflows_config: Optional explicit workflows config (overrides discovery)
        config: Optional explicit unified config (overrides discovery)

    Returns:
        Fully processed FeatureMap
    """
    path = Path(path)

    # Discover config if not provided
    if config is None:
        config = _discover_config(path, config_path)

    # 1. Parse YAML into raw entities
    parser = FeatureMapParser()
    feature_map = parser.parse_file(path, config=config)

    # 2. Resolve bidirectional edges (so workflows see full graph)
    resolve_graph_edges(feature_map.entities)

    # 3. Expand workflows
    if workflows_config is None:
        workflows_config = config.workflows if config else None
    feature_map.entities = expand_workflows(feature_map.entities, workflows_config)

    # 4. Resolve edges again (for new phase entities)
    resolve_graph_edges(feature_map.entities)

    # 5. Validate references, cycles, and entity types
    validate_feature_map(feature_map, config)

    return feature_map


def validate_feature_map(feature_map: FeatureMap, config: UnifiedConfig | None = None) -> None:
    """Validate the feature map for reference integrity, cycles, and entity types."""
    all_ids = feature_map.get_all_ids()
    valid_types = get_valid_entity_types(config)

    # Validate entity types
    for entity in feature_map.entities:
        if entity.type not in valid_types:
            raise ValidationError(
                f"Entity '{entity.id}' has invalid type '{entity.type}'. "
                f"Valid types are: {', '.join(sorted(valid_types))}"
            )

    # Validate all entity dependencies reference valid IDs
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
    _check_circular_dependencies(feature_map)


def _check_circular_dependencies(feature_map: FeatureMap) -> None:
    """Check for circular dependencies in all entities."""
    for entity in feature_map.entities:
        visited: set[str] = set()
        path: list[str] = []
        if _has_circular_dependency(feature_map, entity.id, visited, path):
            cycle = " -> ".join(path[path.index(entity.id) :] + [entity.id])
            raise CircularDependencyError(f"Circular dependency detected: {cycle}")


def _has_circular_dependency(
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
            if _has_circular_dependency(feature_map, dep_id, visited, path):
                return True

    path.pop()
    return False
