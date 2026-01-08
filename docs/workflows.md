# Workflows

Workflows are factory functions that expand a single entity into multiple phase entities. This allows you to define common development patterns (like design-then-implement) once and apply them to many entities.

## Quick Start

1. Enable workflows in `mouc_config.yaml`:

```yaml
workflows:
  stdlib: true  # Enable standard library workflows
```

2. Use a workflow on an entity in `feature_map.yaml`:

```yaml
entities:
  auth_redesign:
    type: capability
    name: Auth Redesign
    description: Redesign authentication system
    workflow: design_impl
    meta:
      effort: "2w"
      resources: [alice]
```

3. The entity expands into phases:
   - `auth_redesign_design` - Design phase (3d default, floats freely)
   - `auth_redesign` - Parent entity (impl, now requires design + signoff lag)

## Standard Library Workflows

Enable with `workflows.stdlib: true` in config.

### design_impl

Expands into: design (floats) -> [signoff lag] -> parent (impl)

The design phase has no dependencies (floats freely). The parent entity becomes the implementation, requiring the design phase plus signoff lag.

**Defaults:**
- `design_effort`: "3d"
- `signoff_lag`: "1w"

**Phase keys:** `design`

### impl_pr

Expands into: parent (impl) -> [review lag] -> pr

The parent entity stays as the implementation. A PR phase is added that requires the parent plus review lag.

**Defaults:**
- `pr_effort`: "2d"
- `review_lag`: "3d"

**Phase keys:** `pr`

### full

Expands into: design (floats) -> [signoff lag] -> parent (impl) -> [review lag] -> pr

Combines design_impl and impl_pr patterns.

**Defaults:**
- `design_effort`: "3d"
- `signoff_lag`: "1w"
- `pr_effort`: "2d"
- `review_lag`: "3d"

**Phase keys:** `design`, `pr`

### phased_rollout

Expands into: parent (impl) -> canary -> [bake time] -> rollout

The parent entity stays as the implementation. Canary and rollout phases are added after it.

**Defaults:**
- `canary_effort`: "1d"
- `bake_time`: "1w"
- `rollout_effort`: "1d"

**Phase keys:** `canary`, `rollout`

## Configuration

### Workflow Config Location

Workflows are configured in `mouc_config.yaml`:

```yaml
workflows:
  stdlib: true  # Enable standard library (default: false)
  defaults:
    capability: design_impl  # Default workflow for capabilities
    user_story: design_impl  # Default workflow for user stories
    # outcome not specified = no default
  definitions:
    my_workflow:
      handler: my_module.workflow_func  # Module path
      defaults:
        custom_default: "1w"
```

### Type-Based Defaults

The `defaults` field maps entity types to workflow names. Entities without an explicit `workflow` field get the default for their type:

```yaml
workflows:
  stdlib: true
  defaults:
    capability: design_impl
    user_story: impl_pr
```

To disable a default for a specific entity, use `workflow: none`:

```yaml
entities:
  simple_task:
    type: capability
    name: Simple Task
    workflow: none  # Skip expansion even with default
```

### Custom Workflows

You can define custom workflows via Python modules or files.

**Module-based:**
```yaml
workflows:
  definitions:
    custom:
      handler: my_project.workflows.custom_flow
```

**File-based:**
```yaml
workflows:
  definitions:
    custom:
      handler: ./my_workflows.py:custom_flow
```

**With phase discovery (recommended for graph-aware workflows):**
```yaml
workflows:
  definitions:
    custom:
      handler: ./my_workflows.py:custom_flow
      phases: ["{id}_design", "{id}"]  # Phase ID templates
```

The `phases` field declares what phase IDs your workflow creates using `{id}` as a placeholder for the entity ID. This enables:
- **Graph-aware workflows**: The `WorkflowContext.phase_map` is populated correctly, so your workflow can check what phases other entities have
- **Cross-entity wiring**: Use `context.has_phase()` to intelligently wire dependencies between phases

Without `phases`, custom workflows fall back to assuming no expansion (just `[entity.id]`), which means `WorkflowContext.phase_map` won't accurately reflect what phases your workflow creates.

### Workflow Function Signature

```python
from mouc.models import Entity
from mouc.workflows import WorkflowContext

def my_workflow(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
    context: WorkflowContext | None = None,      # Optional: graph context
    discovery_state: Any = None,                  # Optional: pre-computed state
) -> list[Entity]:
    """Expand entity into phase entities.

    Must return a list that includes an entity with the same ID
    as the input entity (to preserve dependency references).
    """
    ...
```

### Graph-Aware Workflows (WorkflowContext)

Workflows can access the full entity graph via the optional `context` parameter. This enables intelligent dependency wiring across entities.

**WorkflowContext API:**

```python
@dataclass
class WorkflowContext:
    all_entities: list[Entity]           # All entities before expansion
    entity_map: dict[str, Entity]        # id -> entity lookup
    entity_workflows: dict[str, str]     # id -> workflow name
    phase_map: dict[str, list[str]]      # id -> phase IDs it will create

    def has_phase(self, entity_id: str, phase_suffix: str) -> bool:
        """Check if entity will have a specific phase (e.g., 'design')."""

    def get_phases_for(self, entity_id: str) -> list[str]:
        """Get phase IDs that will be created for an entity."""

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get an entity by ID."""

    def get_workflow(self, entity_id: str) -> str | None:
        """Get the workflow name for an entity."""
```

**Example: Smart Dependency Wiring**

```python
def smart_design_impl(entity, defaults, phase_overrides, context=None, discovery_state=None):
    """If B requires A, then B_design requires A_design (if A has one)."""
    design = _create_design_phase(entity, ...)

    # Wire design->design dependencies using context
    if context:
        for dep in entity.requires:
            if context.has_phase(dep.entity_id, "design"):
                design.requires.add(Dependency(f"{dep.entity_id}_design"))

    return [design, parent]
```

### Phase Discovery (Two-Pass Expansion)

Workflows are expanded in two passes:

1. **Discovery**: Determine what phase IDs each workflow will create
2. **Expansion**: Call workflows with full context (including all phase IDs)

**Phase discovery priority (highest to lowest):**

1. **`discover_phases()` method** - If your workflow function has a `discover_phases` attribute, it's called for maximum control
2. **`phases` config** - Declarative phase ID templates in workflow definition (recommended for most custom workflows)
3. **Stdlib fallback** - Built-in knowledge of standard library workflow phase IDs
4. **Default** - Assumes workflow creates only `[entity.id]` (no expansion)

**Option 1: Declarative `phases` config (recommended)**

```yaml
workflows:
  definitions:
    my_workflow:
      handler: ./my_workflows.py:my_workflow
      phases: ["{id}_design", "{id}"]  # Simple template substitution
```

**Option 2: `discover_phases()` method (for complex logic)**

```python
from mouc.workflows import PhaseDiscovery

def my_workflow_discover(entity, defaults):
    """Discover phases and optionally pre-compute state."""
    return PhaseDiscovery(
        phase_ids=[f"{entity.id}_phase1", entity.id],
        state={"computed_value": some_expensive_calculation()},
    )

def my_workflow(entity, defaults, phase_overrides, context=None, discovery_state=None):
    # Use pre-computed state from discovery
    computed = discovery_state.get("computed_value") if discovery_state else None
    ...

# Attach discovery to workflow function
my_workflow.discover_phases = my_workflow_discover
```

## Per-Entity Configuration

### Phase Overrides

Override defaults per-entity via the `phases` field:

```yaml
entities:
  auth_redesign:
    type: capability
    name: Auth Redesign
    workflow: design_impl
    meta:
      effort: "2w"
    phases:
      design:
        name: Auth Design Document  # Custom name
        requires: [prereq_task]     # Add dependencies (merged with workflow defaults)
        meta:
          effort: "5d"              # Override effort
          status: done              # Mark phase done
      impl:
        meta:
          lag: "2w"                 # Override signoff lag
```

### Phase Requirements

By default, design phases float freely (no `requires`). You can add explicit dependencies to any phase using the `requires` field:

```yaml
entities:
  entity_a:
    type: capability
    workflow: design_impl
    # ...

  entity_b:
    type: capability
    workflow: design_impl
    phases:
      design:
        requires: [entity_a_design]  # B's design depends on A's design
```

Phase `requires` support:
- **Merge behavior**: Override requires are merged (union) with workflow-determined requires
- **Lag syntax**: Supports lag like entity-level requires: `requires: ["prereq + 1w"]`
- **Cross-entity references**: Can reference workflow-created phase IDs from other entities (e.g., `entity_a_design`)

### What Gets Inherited

- Phase entities inherit parent's `type`, `description`, `tags`, and `meta`
- Design phases float freely by default (no `requires`), but can have requires added via overrides
- Parent entity keeps its original `requires` plus gains design dependency
- Last phase (e.g., pr, rollout) takes over parent's `enables`
- Phase overrides take precedence over inherited values
- Phase `requires` from overrides are merged with workflow-determined requires

## Dependency Wiring

When an entity uses a workflow:

1. **Design phases** → Float freely by default, but can have explicit `requires` via phase overrides
2. **Parent entity** → Keeps original `requires` AND gains design dependency (with lag)
3. **Later phases** (pr, rollout) → Require parent/preceding phase (plus any phase override `requires`)
4. **Last phase** → Takes over parent's `enables`

Other entities can still reference the original entity ID, and the workflow ensures proper sequencing.

## Gantt Display

Each phase appears as a separate bar in the Gantt chart:

```
Auth Redesign - Design    |████|
Auth Redesign - Impl                  |████████████|
```

The gap between phases visually shows the lag period (e.g., signoff time).

## Limitations

- Nested workflows are not supported (a generated phase entity cannot have a workflow field)
- Workflow expansion happens before validation, so circular dependencies through workflows are caught normally
- Generated entity IDs must be unique (e.g., don't have both `auth_design` and `auth` with `workflow: design_impl`)
