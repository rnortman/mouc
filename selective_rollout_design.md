# Selective Rollout for Resource Choice Optimization

## Overview

This document describes a more sophisticated approach to resource selection in the critical path scheduler. Instead of using a heuristic, this approach uses rollout simulation to compare outcomes when assigning a task to different resources.

**Status**: Design only. Not implemented. See `prefer_fungible_resources` config flag for the simpler heuristic approach.

## Problem Statement

When auto-assigning resources to tasks, the scheduler may pick a "scarce" resource (one that is explicitly required by other pending tasks) when other "fungible" resources are equally available. This can cause downstream blocking.

Example:
- Task A can use any resource (auto-assignment via resource_spec)
- Task B specifically requires resource `alice` (explicit assignment)
- Scheduler assigns `alice` to Task A (because she's first in `resource_order`)
- Task B gets blocked until `alice` finishes Task A

## Proposed Solution: Selective Rollout

Instead of using a heuristic, simulate both scenarios and pick the one with the better schedule score.

### When to Trigger

Only run rollout when ALL conditions are met:
1. Auto-assignment task with multiple available candidates
2. All candidates have the same completion time (true tie)
3. At least one candidate is "scarce" (has exclusive tasks becoming eligible soon)
4. At least one candidate is "fungible" (no exclusive tasks becoming eligible soon)

This keeps rollout targeted and avoids unnecessary computation.

### Algorithm

```
function check_resource_choice_rollout(task, candidates, state, ctx):
    # Identify scarce vs fungible candidates
    task_end = current_time + task.duration
    scarce = []
    fungible = []

    for candidate in candidates:
        blocking_count = count_exclusive_tasks_eligible_before(candidate.resource_id, task_end)
        if blocking_count > 0:
            scarce.append((candidate, blocking_count))
        else:
            fungible.append(candidate)

    # Fast path: no scarcity concern
    if scarce.is_empty() or fungible.is_empty():
        return candidates[0]  # Use default selection

    # Pick representative from each category
    scarce_resource = scarce[0].candidate
    fungible_resource = fungible[0]

    # Scenario A: Assign to scarce resource
    state_a = state.clone()
    assign_task_to_resource(state_a, task, scarce_resource)
    score_a = run_simulation_to_horizon(state_a, horizon)

    # Scenario B: Assign to fungible resource
    state_b = state.clone()
    assign_task_to_resource(state_b, task, fungible_resource)
    score_b = run_simulation_to_horizon(state_b, horizon)

    # Pick better outcome (lower score is better)
    if score_b < score_a:
        return fungible_resource
    else:
        return scarce_resource
```

### Key Differences from Existing Rollout

The existing rollout (`check_rollout_skip_int`) compares:
- Scenario A: Schedule task now
- Scenario B: Skip task entirely

The resource choice rollout compares:
- Scenario A: Schedule task on resource X
- Scenario B: Schedule task on resource Y

Both scenarios schedule the task, just on different resources. This is actually simpler since we don't need to handle the "skip" logic.

### Required Data Structures

```rust
/// For each resource ID, tasks that explicitly require it
resource_exclusive_tasks: Vec<Vec<TaskId>>
```

Build once during `schedule_critical_path()`:
```rust
fn build_resource_exclusive_tasks(&self, ctx: &TaskData) -> Vec<Vec<TaskId>> {
    let mut result: Vec<Vec<TaskId>> = vec![Vec::new(); self.resource_index.len()];

    for (idx, req) in ctx.resource_reqs.iter().enumerate() {
        if let Some(req) = req {
            if req.requires_all {
                // Explicit assignment - task requires ALL resources in mask
                for res_id in req.mask.iter_set() {
                    result[res_id as usize].push(idx as TaskId);
                }
            }
        }
    }

    result
}
```

### Horizon Selection

Use the same horizon logic as existing rollout:
```rust
let horizon = competing_exclusive_tasks
    .iter()
    .map(|task_int| estimate_completion(task_int, ctx, state))
    .max()
    .unwrap_or(current_task_completion);

// Cap to configured max
let horizon = match config.rollout_max_horizon_days {
    Some(max_days) => horizon.min(current_time + max_days),
    None => horizon,
};
```

### Integration Points

1. **Trigger location**: `try_schedule_auto_assignment()` after finding tied candidates
2. **Config flag**: `rollout_resource_choice_enabled: bool` (separate from `rollout_enabled`)
3. **Logging**: Add verbosity level 2 logging for rollout decisions

### Estimated Complexity

- Data structure build: O(tasks) once
- Per-decision check: O(candidates × exclusive_tasks_per_resource)
- Rollout simulation: O(tasks × iterations) per scenario
- Expected frequency: Low (only on true ties with scarcity)

Given current performance (~200 tasks in 0.5s), this should be acceptable.

### Testing Strategy

1. Unit test: Construct scenario where heuristic and rollout disagree
2. Verify rollout gives better final schedule
3. Benchmark: Ensure no significant performance regression

### Future Enhancements

1. **Multi-way comparison**: Compare all candidates, not just scarce vs fungible
2. **Score caching**: Cache partial simulation results across decisions
3. **Adaptive triggering**: Only trigger when blocked task has high priority/urgency

## Relationship to Heuristic

The `prefer_fungible_resources` heuristic is a fast approximation of this rollout:
- Heuristic: Prefer resources with fewer exclusive tasks
- Rollout: Simulate to verify which choice is actually better

The heuristic will be wrong when:
- The exclusive task is low priority (blocking it doesn't matter much)
- The exclusive task won't be eligible for a long time anyway
- Other factors in the schedule make the "scarce" choice better

For most cases, the heuristic should work well. Rollout is the fallback for when accuracy matters more than speed.
