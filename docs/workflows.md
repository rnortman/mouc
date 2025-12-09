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
   - `auth_redesign_design` - Design phase (3d default)
   - `auth_redesign_impl` - Implementation phase (inherits 2w effort)
   - `auth_redesign` - Milestone (0d, requires impl)

## Standard Library Workflows

Enable with `workflows.stdlib: true` in config.

### design_impl

Expands into: design -> [signoff lag] -> impl -> milestone

**Defaults:**
- `design_effort`: "3d"
- `signoff_lag`: "1w"

**Phase keys:** `design`, `impl`

### impl_pr

Expands into: impl -> [review lag] -> pr -> milestone

**Defaults:**
- `pr_effort`: "2d"
- `review_lag`: "3d"

**Phase keys:** `impl`, `pr`

### full

Expands into: design -> [signoff lag] -> impl -> [review lag] -> pr -> milestone

**Defaults:**
- `design_effort`: "3d"
- `signoff_lag`: "1w"
- `pr_effort`: "2d"
- `review_lag`: "3d"

**Phase keys:** `design`, `impl`, `pr`

### phased_rollout

Expands into: impl -> canary -> [bake time] -> rollout -> milestone

**Defaults:**
- `canary_effort`: "1d"
- `bake_time`: "1w"
- `rollout_effort`: "1d"

**Phase keys:** `impl`, `canary`, `rollout`

## Configuration

### Workflow Config Location

Workflows are configured in `mouc_config.yaml`:

```yaml
workflows:
  stdlib: true  # Enable standard library (default: false)
  definitions:
    my_workflow:
      handler: my_module.workflow_func  # Module path
      defaults:
        custom_default: "1w"
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
        meta:
          effort: "5d"              # Override effort
          status: done              # Mark phase done
      impl:
        meta:
          lag: "2w"                 # Override signoff lag
```

### What Gets Inherited

- First phase inherits parent's `requires`
- Last phase (milestone) inherits parent's `enables`
- All phases inherit parent's `type`, `description`, `tags`, and `meta`
- Phase overrides take precedence over inherited values

## Dependency Wiring

When an entity uses a workflow:

1. **Parent's `requires`** → First phase's `requires`
2. **Inter-phase dependencies** → Created by the workflow (with lag)
3. **Milestone** → Requires last work phase, has `effort: 0d`
4. **Parent's `enables`** → Milestone's `enables`

This means other entities can still reference the original entity ID, and they'll wait for the entire workflow to complete.

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
