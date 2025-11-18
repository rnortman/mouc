# Resource Management and Automatic Assignment

Mouc supports automatic resource assignment for Gantt chart scheduling. This allows you to define available resources, specify assignment preferences, and let the scheduler automatically assign tasks to resources based on availability and priority.

## Overview

Without a resource configuration, tasks with no assigned resources are tracked as "unassigned" and execute serially. With a resource configuration file, you can:

- Define available resources (people, teams, etc.)
- Specify Do-Not-Schedule (DNS) periods for each resource
- Create resource groups/aliases
- Use wildcards and preferences for automatic assignment
- Configure a default resource for unassigned tasks

## Resource Configuration File

Create a `mouc_config.yaml` file with resource definitions. See [Configuration Documentation](config.md) for the complete file format.

The resources section has the following structure:

```yaml
# Resources section (required)
resources:
  - name: alice
    dns_periods:
      - start: 2025-01-15
        end: 2025-01-20
      - start: 2025-02-10
        end: 2025-02-14

  - name: bob
    dns_periods: []

  - name: charlie
    dns_periods:
      - start: 2025-01-01
        end: 2025-01-07

# Define resource groups (aliases)
groups:
  team_a:
    - alice
    - bob
  team_b:
    - charlie
  backend_team:
    - alice
    - charlie

# Optional: default resource for tasks with no assignment
default_resource: "*"  # Can be "*", "alice|bob", "team_a", etc.
```

### Fields

#### `resources` (required)
List of available resources. Each resource has:
- `name` (required): Unique identifier for the resource
- `dns_periods` (optional): List of do-not-schedule periods
  - `start` (required): Start date (YYYY-MM-DD)
  - `end` (required): End date (YYYY-MM-DD)

#### `groups` (optional)
Dictionary mapping group names to lists of resource names. Groups provide convenient aliases for multiple resources.

#### `default_resource` (optional)
Resource specification to use for tasks with no explicit resource assignment. Can be:
- `"*"` - wildcard (any available resource)
- `"alice|bob|charlie"` - pipe-separated preference list
- `"team_a"` - group alias
- `"alice"` - specific resource

If not specified, unassigned tasks use the special "unassigned" resource and execute serially.

## Using the Resource Configuration

The `gantt` command auto-detects `mouc_config.yaml` in the current directory:

```bash
mouc gantt feature_map.yaml --output schedule.md
```

Or specify a custom config location:

```bash
mouc --config /path/to/config.yaml gantt feature_map.yaml
```

## Resource Assignment in Feature Maps

In your `feature_map.yaml`, specify resources in the `meta` section:

### Explicit Assignment

```yaml
entities:
  api_development:
    type: capability
    name: API Development
    description: Build REST API endpoints
    meta:
      effort: "2w"
      resources: ["alice"]  # Explicitly assigned to alice
```

### Wildcard Assignment

Use `"*"` to assign to any available resource (based on config order):

```yaml
entities:
  code_review:
    type: capability
    name: Code Review
    description: Review pull requests
    meta:
      effort: "3d"
      resources: ["*"]  # Assign to first available resource
```

### Preference List

Use pipe-separated values to specify preference order:

```yaml
entities:
  database_work:
    type: capability
    name: Database Migration
    description: Migrate schema
    meta:
      effort: "1w"
      resources: ["alice|bob|charlie"]  # Try alice, then bob, then charlie
```

### Group Assignment

Use group aliases defined in mouc_config.yaml:

```yaml
entities:
  backend_feature:
    type: capability
    name: Backend Feature
    description: Implement backend logic
    meta:
      effort: "2w"
      resources: ["backend_team"]  # Expands to alice|charlie
```

### Unassigned Tasks

Tasks with no resources use the `default_resource` from config, or fall back to "unassigned":

```yaml
entities:
  documentation:
    type: capability
    name: Update Documentation
    description: Write API docs
    meta:
      effort: "2d"
      resources: []  # Uses default_resource or "unassigned"
```

## How Assignment Works

The scheduler uses a **dynamic assignment algorithm** during the scheduling loop:

### 1. Resource Spec Expansion

When a task becomes eligible for scheduling, the scheduler expands its resource specification:

- `"*"` → all resources from config (in config order)
- `"alice|bob|charlie"` → `["alice", "bob", "charlie"]` (preserves order)
- `"team_a"` → members of team_a group (in group order)
- `"alice"` → `["alice"]` (explicit assignment)

### 2. Availability Filtering

The scheduler filters candidates based on:

**DNS Periods:** Resources in a DNS period at the current schedule time are excluded.

**Resource Conflicts:** Resources already busy with other tasks at the current time are excluded.

### 3. Resource Selection

The scheduler picks the **first available resource** from the filtered list. This respects:

- Order specified in pipe-separated lists
- Order defined in the resource config (for wildcards)
- Order defined in groups (for group aliases)

### 4. Task Waiting

If no resources are available, the task waits and is retried at the next time point (when another task completes or a constraint becomes active).

### Priority and Deadline Handling

The scheduler maintains deadline prioritization:

- Tasks with earlier deadlines are scheduled first
- High-priority tasks get first pick of available resources
- Tasks wait for resources rather than violating deadline priorities

## DNS (Do Not Schedule) Periods

DNS periods block resource assignment during specific time ranges. Use them for:

- Vacations and time off
- Dedicated meeting/training time
- Scheduled maintenance windows
- Cross-team commitments

### Per-Resource DNS Periods

Define DNS periods for individual resources:

```yaml
resources:
  - name: alice
    dns_periods:
      - start: 2025-01-15  # MLK Day
        end: 2025-01-15
      - start: 2025-07-01  # Summer vacation
        end: 2025-07-14
```

### Global DNS Periods

Define company-wide DNS periods that apply to all resources:

```yaml
global_dns_periods:
  - start: 2025-12-24  # Company holiday break
    end: 2025-12-31
  - start: 2025-07-04  # Independence Day
    end: 2025-07-04

resources:
  - name: alice
    dns_periods:
      - start: 2025-08-01  # Personal vacation
        end: 2025-08-14
```

Global DNS periods are merged with per-resource DNS periods. In the example above, alice will be unavailable during both the company holiday break (global) and her personal vacation (per-resource).

Tasks that need a resource during DNS periods will:
1. Skip that resource if scheduled during DNS periods
2. Try the next resource in the preference list
3. Wait if the resource is the only option

## Resource Groups

Groups provide convenient aliases for sets of resources:

```yaml
groups:
  frontend_team:
    - alice
    - bob
  backend_team:
    - charlie
    - david
  full_stack:
    - alice
    - charlie
```

Use groups in feature maps:

```yaml
meta:
  resources: ["frontend_team"]  # Expands to alice|bob
```

Groups are especially useful for:
- Team-based assignment
- Skill-based pools (e.g., "database_experts")
- Rotating assignments (first available team member)

## Examples

### Example 1: Round-Robin with Wildcard

```yaml
# mouc_config.yaml
resources:
  - name: alice
    dns_periods: []
  - name: bob
    dns_periods: []
  - name: charlie
    dns_periods: []

default_resource: "*"
```

```yaml
# feature_map.yaml
entities:
  task1:
    type: capability
    name: Task 1
    meta:
      effort: "1w"
      resources: []  # Uses default_resource: "*"

  task2:
    type: capability
    name: Task 2
    meta:
      effort: "1w"
      resources: []  # Uses default_resource: "*"
```

Result: task1 gets alice (first in config), task2 gets bob (alice is busy).

### Example 2: Skill-Based Assignment

```yaml
# mouc_config.yaml
resources:
  - name: alice
    dns_periods: []
  - name: bob
    dns_periods: []
  - name: charlie
    dns_periods: []

groups:
  database_team:
    - alice
    - charlie
  frontend_team:
    - bob
```

```yaml
# feature_map.yaml
entities:
  database_migration:
    type: capability
    name: Database Migration
    meta:
      effort: "1w"
      resources: ["database_team"]  # alice or charlie

  ui_redesign:
    type: capability
    name: UI Redesign
    meta:
      effort: "1w"
      resources: ["frontend_team"]  # bob
```

### Example 3: Preferences with Fallback

```yaml
# feature_map.yaml
entities:
  critical_feature:
    type: capability
    name: Critical Feature
    meta:
      effort: "2w"
      resources: ["alice|bob"]  # Prefer alice, fall back to bob
      end_before: "2025-03-31"  # Hard deadline
```

If alice is available, she gets the task. If alice is busy or in a DNS period, bob gets it.

### Example 4: Mixed Assignment Strategies

```yaml
# feature_map.yaml
entities:
  infrastructure:
    type: capability
    name: Infrastructure Setup
    meta:
      effort: "1w"
      resources: ["alice"]  # Explicit: only alice can do this

  code_review:
    type: capability
    name: Code Review
    requires: [infrastructure]
    meta:
      effort: "3d"
      resources: ["*"]  # Anyone available

  deployment:
    type: capability
    name: Deployment
    requires: [code_review]
    meta:
      effort: "2d"
      resources: ["alice|bob"]  # Prefer alice, fall back to bob
```

## Best Practices

### 1. Order Matters

Resource order in the config file determines priority for wildcards:

```yaml
resources:
  - name: senior_dev  # Tried first for "*"
  - name: mid_dev     # Tried second
  - name: junior_dev  # Tried last
```

### 2. Use Groups for Flexibility

Groups make it easy to adjust team membership without changing feature maps:

```yaml
# Change team composition in one place
groups:
  api_team:
    - alice
    - bob
    - new_hire  # Just add here
```

### 3. DNS Periods for Realistic Schedules

Add DNS periods for known absences to get realistic schedules:

```yaml
resources:
  - name: alice
    dns_periods:
      - start: 2025-12-20  # Holiday break
        end: 2025-12-31
```

### 4. Default Resource for Flexibility

Use `default_resource: "*"` to ensure unassigned tasks are automatically distributed:

```yaml
default_resource: "*"  # Unassigned tasks get any available resource
```

### 5. Explicit Assignment for Critical Work

For critical tasks requiring specific expertise, use explicit assignment:

```yaml
meta:
  resources: ["security_expert"]  # Only this person
```

### 6. Preference Lists for Knowledge Sharing

Use preference lists to prefer primary experts but allow fallback:

```yaml
meta:
  resources: ["expert|backup"]  # Prefer expert, but backup can do it
```

## Troubleshooting

### Tasks Not Being Assigned

**Problem:** Tasks stay unassigned even with `resources: ["*"]`

**Solutions:**
- Verify resource config file is being loaded (`--resources mouc_config.yaml`)
- Check that resource names in groups match resource definitions
- Ensure resources aren't all in DNS periods

### Tasks Waiting Too Long

**Problem:** Tasks wait for specific resources instead of using available ones

**Solutions:**
- Use wildcards or preference lists instead of explicit assignment
- Check DNS periods aren't blocking too many resources
- Consider adding more resources to groups

### Unexpected Resource Assignment

**Problem:** Wrong resource gets assigned

**Solutions:**
- Check resource order in config file (affects wildcard expansion)
- Check group membership (groups expand in member order)
- Check for conflicting DNS periods

## Technical Details

### Resource Semantics

**Resource Exclusivity:** A resource can only work on one task at a time. When assigned to a task, the resource is blocked for the task's duration.

**Capacity:** Resource allocation (e.g., `"alice:0.5"`) affects task duration but not concurrency. A 0.5 allocation means the task takes twice as long, but alice is still fully blocked during that time.

### Algorithm Complexity

The scheduler runs in O(n * m * r) time where:
- n = number of tasks
- m = average number of dependencies per task
- r = number of resources

For typical project sizes (< 100 tasks, < 10 resources), this is effectively instant.

### Determinism

Given the same input (feature map, resource config, current date), the scheduler produces the same schedule. Task ordering is deterministic based on:
1. Deadline priority (earlier deadlines first)
2. Task ID (lexicographic order as tiebreaker)

### Limitations

**No Preemption:** Once a task starts, it cannot be paused or reassigned.

**No Resource Sharing:** Multiple tasks cannot share a resource concurrently, even with partial allocations.

**No Cost Optimization:** The scheduler optimizes for deadline compliance, not resource utilization or cost.

## See Also

- [Gantt Chart Documentation](gantt.md) - General Gantt chart features
- [YAML Schema Reference](../README.md#yaml-schema) - Complete schema documentation
- [Styling System](styling.md) - Customizing output appearance
