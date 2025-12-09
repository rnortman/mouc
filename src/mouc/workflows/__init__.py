"""Workflow expansion system for Mouc.

Workflows are factory functions that expand a single entity into multiple phase entities.
All workflows come from extensions - there are no built-in workflows. A standard library
is bundled in mouc.workflows.stdlib and can be enabled via config.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from mouc.exceptions import ValidationError
from mouc.models import Entity
from mouc.workflows import stdlib as stdlib_module

if TYPE_CHECKING:
    from mouc.unified_config import WorkflowsConfig


class WorkflowFactory(Protocol):
    """Protocol for workflow factory functions.

    A workflow factory takes an entity and expands it into multiple phase entities.
    The returned list must include an entity with the same ID as the input entity
    to preserve dependency references.
    """

    def __call__(
        self,
        entity: Entity,
        defaults: dict[str, Any],
        phase_overrides: dict[str, Any] | None,
    ) -> list[Entity]:
        """Expand entity into phase entities.

        Args:
            entity: The entity to expand
            defaults: Default values from workflow config
            phase_overrides: Per-phase overrides from entity.phases

        Returns:
            List of entities including one with the original entity's ID
        """
        ...


def load_workflow(handler: str) -> WorkflowFactory:
    """Load a workflow function from a handler string.

    Supports two formats:
    - "module.path.function" - Import from an installed module
    - "file/path.py:function" - Load from a file

    Args:
        handler: Handler specification string

    Returns:
        The workflow factory function

    Raises:
        ValidationError: If the handler cannot be loaded
    """
    if ":" in handler and not handler.startswith("mouc."):
        # File-based handler: "path/to/file.py:function_name"
        file_path_str, func_name = handler.rsplit(":", 1)
        file_path = Path(file_path_str)

        if not file_path.exists():
            raise ValidationError(f"Workflow handler file not found: {file_path}")

        # Load module from file
        spec = importlib.util.spec_from_file_location(f"workflow_{file_path.stem}", file_path)
        if spec is None or spec.loader is None:
            raise ValidationError(f"Failed to load workflow from file: {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        if not hasattr(module, func_name):
            raise ValidationError(f"Workflow function '{func_name}' not found in {file_path}")

        return getattr(module, func_name)  # type: ignore[no-any-return]

    # Module-based handler: "module.path.function"
    try:
        module_path, func_name = handler.rsplit(".", 1)
        module = importlib.import_module(module_path)

        if not hasattr(module, func_name):
            raise ValidationError(
                f"Workflow function '{func_name}' not found in module '{module_path}'"
            )

        return getattr(module, func_name)  # type: ignore[no-any-return]
    except ImportError as e:
        raise ValidationError(f"Failed to import workflow module '{handler}': {e}") from e


def expand_workflows(  # noqa: PLR0912 - complex validation logic
    entities: list[Entity],
    workflows_config: WorkflowsConfig | None,
) -> list[Entity]:
    """Expand all entities with workflow field into phase entities.

    Args:
        entities: List of entities to process
        workflows_config: Workflow configuration (None means no expansion)

    Returns:
        New list with workflow entities expanded into phases

    Raises:
        ValidationError: If a workflow reference is invalid or expansion fails
    """
    if workflows_config is None:
        return entities

    # Build workflow lookup including stdlib if enabled
    workflow_lookup: dict[str, tuple[WorkflowFactory, dict[str, Any]]] = {}

    # Load stdlib workflows if enabled
    if workflows_config.stdlib:
        for name in stdlib_module.STDLIB_WORKFLOWS:
            func = getattr(stdlib_module, name)
            workflow_lookup[name] = (func, {})

    # Load configured workflows (can override stdlib)
    for name, config in workflows_config.definitions.items():
        func = load_workflow(config.handler)
        workflow_lookup[name] = (func, config.defaults)

    # Track existing IDs to detect collisions
    existing_ids = {e.id for e in entities}

    result: list[Entity] = []

    for entity in entities:
        workflow_name = entity.workflow

        # Apply type-specific default if no explicit workflow
        if workflow_name is None:
            workflow_name = workflows_config.defaults.get(entity.type)

        # Skip if no workflow or explicitly disabled
        if workflow_name is None or workflow_name == "none":
            result.append(entity)
            continue

        # Validate workflow exists
        if workflow_name not in workflow_lookup:
            available = ", ".join(sorted(workflow_lookup.keys())) or "(none)"
            raise ValidationError(
                f"Entity '{entity.id}' references unknown workflow '{workflow_name}'. "
                f"Available workflows: {available}"
            )

        factory, defaults = workflow_lookup[workflow_name]

        # Expand the entity
        try:
            expanded = factory(entity, defaults, entity.phases)
        except Exception as e:
            raise ValidationError(
                f"Workflow '{workflow_name}' failed to expand entity '{entity.id}': {e}"
            ) from e

        # Validate expansion result
        if not expanded:
            raise ValidationError(
                f"Workflow '{workflow_name}' returned empty list for entity '{entity.id}'"
            )

        # Check that original ID is preserved
        expanded_ids = {e.id for e in expanded}
        if entity.id not in expanded_ids:
            raise ValidationError(
                f"Workflow '{workflow_name}' must return an entity with ID '{entity.id}' "
                f"to preserve dependency references. Got: {sorted(expanded_ids)}"
            )

        # Check for ID collisions with other entities (excluding original)
        for exp_entity in expanded:
            if exp_entity.id != entity.id and exp_entity.id in existing_ids:
                raise ValidationError(
                    f"Workflow '{workflow_name}' generated entity ID '{exp_entity.id}' "
                    f"which already exists. Consider renaming the parent entity."
                )

        # Check for nested workflows (not supported in v1)
        for exp_entity in expanded:
            if exp_entity.workflow is not None and exp_entity.id != entity.id:
                raise ValidationError(
                    f"Workflow '{workflow_name}' generated entity '{exp_entity.id}' "
                    f"with workflow field set. Nested workflows are not supported."
                )

        # Add expanded entities and track new IDs
        result.extend(expanded)
        existing_ids.update(expanded_ids)

    return result
