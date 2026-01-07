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

### Workflow Function Signature

```python
from mouc.models import Entity

def my_workflow(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into phase entities.

    Must return a list that includes an entity with the same ID
    as the input entity (to preserve dependency references).
    """
    ...
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
