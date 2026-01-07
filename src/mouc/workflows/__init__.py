"""Workflow expansion system for Mouc.

Workflows are factory functions that expand a single entity into multiple phase entities.
All workflows come from extensions - there are no built-in workflows. A standard library
is bundled in mouc.workflows.stdlib and can be enabled via config.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from mouc.exceptions import ValidationError
from mouc.models import Entity
from mouc.workflows import stdlib as stdlib_module

if TYPE_CHECKING:
    from mouc.unified_config import WorkflowsConfig


@dataclass
class PhaseDiscovery:
    """Result of workflow discovery phase.

    Workflows return this from discover_phases() to declare what phases they'll create
    and optionally provide pre-computed state to avoid duplicating logic during expansion.
    """

    phase_ids: list[str]
    state: Any = None


@dataclass
class WorkflowContext:
    """Context passed to workflow functions for graph-aware expansion.

    Provides access to the full entity graph so workflows can make intelligent
    dependency wiring decisions (e.g., if B requires A, wire B_design to require A_design).
    """

    all_entities: list[Entity]
    entity_map: dict[str, Entity] = field(default_factory=lambda: {})
    entity_workflows: dict[str, str | None] = field(default_factory=lambda: {})
    phase_map: dict[str, list[str]] = field(default_factory=lambda: {})

    def get_phases_for(self, entity_id: str) -> list[str]:
        """Get phase IDs that will be created for an entity."""
        return self.phase_map.get(entity_id, [entity_id])

    def has_phase(self, entity_id: str, phase_suffix: str) -> bool:
        """Check if entity will have a specific phase (e.g., 'design')."""
        return f"{entity_id}_{phase_suffix}" in self.phase_map.get(entity_id, [])

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get an entity by ID."""
        return self.entity_map.get(entity_id)

    def get_workflow(self, entity_id: str) -> str | None:
        """Get the workflow name for an entity."""
        return self.entity_workflows.get(entity_id)


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


def _get_workflow_name(
    entity: Entity,
    workflows_config: WorkflowsConfig,
) -> str | None:
    """Get the effective workflow name for an entity."""
    workflow_name = entity.workflow
    if workflow_name is None:
        workflow_name = workflows_config.defaults.get(entity.type)
    if workflow_name == "none":
        return None
    return workflow_name


def _discover_phases_for_workflow(
    entity: Entity,
    workflow_name: str,
    factory: WorkflowFactory,
    defaults: dict[str, Any],
) -> PhaseDiscovery:
    """Run discovery for a workflow, with fallback for old-style workflows."""
    # Check if factory has discover_phases method (not part of Protocol, so use getattr)
    discover_fn = getattr(factory, "discover_phases", None)
    if discover_fn is not None:
        result: PhaseDiscovery = discover_fn(entity, defaults)
        return result

    # Check for stdlib fallback
    if workflow_name in stdlib_module.STDLIB_PHASE_DISCOVERY:
        phase_ids = stdlib_module.STDLIB_PHASE_DISCOVERY[workflow_name](entity.id)
        return PhaseDiscovery(phase_ids=phase_ids, state=None)

    # Default: assume workflow creates entity with same ID (no expansion)
    return PhaseDiscovery(phase_ids=[entity.id], state=None)


def _call_workflow_factory(  # noqa: PLR0913 - matches workflow protocol
    factory: WorkflowFactory,
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
    context: WorkflowContext,
    discovery_state: Any,
) -> list[Entity]:
    """Call workflow factory with appropriate signature (backward compatible)."""
    # Get the signature to determine which parameters the factory accepts
    sig = inspect.signature(factory)
    params = sig.parameters

    # Build kwargs based on what the factory accepts
    kwargs: dict[str, Any] = {}
    if "context" in params:
        kwargs["context"] = context
    if "discovery_state" in params:
        kwargs["discovery_state"] = discovery_state

    return factory(entity, defaults, phase_overrides, **kwargs)


def expand_workflows(  # noqa: PLR0912, PLR0915 - complex validation logic
    entities: list[Entity],
    workflows_config: WorkflowsConfig | None,
) -> list[Entity]:
    """Expand all entities with workflow field into phase entities.

    Uses two-pass expansion:
    1. Discovery pass: Determine what phases each workflow will create
    2. Expansion pass: Call workflows with full context (including phase_map)

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

    # === PASS 1: Discovery ===
    # Determine workflow for each entity and discover phases
    entity_workflows: dict[str, str | None] = {}
    phase_map: dict[str, list[str]] = {}
    discovery_states: dict[str, Any] = {}

    for entity in entities:
        workflow_name = _get_workflow_name(entity, workflows_config)
        entity_workflows[entity.id] = workflow_name

        if workflow_name is None:
            # No workflow - entity stays as-is
            phase_map[entity.id] = [entity.id]
            continue

        # Validate workflow exists
        if workflow_name not in workflow_lookup:
            available = ", ".join(sorted(workflow_lookup.keys())) or "(none)"
            raise ValidationError(
                f"Entity '{entity.id}' references unknown workflow '{workflow_name}'. "
                f"Available workflows: {available}"
            )

        factory, defaults = workflow_lookup[workflow_name]
        discovery = _discover_phases_for_workflow(entity, workflow_name, factory, defaults)
        phase_map[entity.id] = discovery.phase_ids
        discovery_states[entity.id] = discovery.state

    # === Build Context ===
    context = WorkflowContext(
        all_entities=entities,
        entity_map={e.id: e for e in entities},
        entity_workflows=entity_workflows,
        phase_map=phase_map,
    )

    # === PASS 2: Expansion ===
    existing_ids = {e.id for e in entities}
    result: list[Entity] = []

    for entity in entities:
        workflow_name = entity_workflows[entity.id]

        # Skip if no workflow
        if workflow_name is None:
            result.append(entity)
            continue

        factory, defaults = workflow_lookup[workflow_name]
        discovery_state = discovery_states.get(entity.id)

        # Expand the entity
        try:
            expanded = _call_workflow_factory(
                factory, entity, defaults, entity.phases, context, discovery_state
            )
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
