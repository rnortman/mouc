# Critical Path Cache Optimization (Archived)

This document describes the cache-based optimization that was used in the critical path rollout simulation before it was replaced with direct scheduler execution. This approach is preserved for potential future restoration if profiling shows performance issues.

## Overview

The original rollout simulation used a `CriticalPathCache` to avoid recomputing critical paths during simulation. When the scheduler needed to evaluate "schedule now vs skip" scenarios, it would run forward simulations using cached target information.

## How It Worked

### CriticalPathCache Structure

```rust
pub struct CriticalPathCache {
    // Cached target info by target_id
    targets: FxHashMap<String, TargetInfo>,
    // Reverse index: task_id -> set of target_ids that have this task on their CP
    task_to_targets: FxHashMap<String, FxHashSet<String>>,
}
```

### Key Operations

1. **Build Cache**: At simulation start, compute critical paths for all unscheduled tasks and store them in the cache.

2. **Invalidation (not recomputation)**: When a task is scheduled during simulation:
   - Remove the task itself as a target
   - Remove any targets that had this task on their critical path
   - Do NOT recompute - just remove affected entries

3. **Ranking**: Get remaining targets sorted by score descending.

### Why Invalidation Without Recomputation?

The simulation was an "approximation" for comparing two scenarios. The code comment said:
> "This is a reasonable approximation for comparing two scenarios."

The rationale was:
- Critical path computation is O(V+E) per target
- With N unscheduled tasks, full recomputation is O(N * (V+E)) per scheduled task
- Invalidation is O(1) per scheduled task
- For rollout decisions, we only need relative comparison between scenarios

### Performance Characteristics

**Advantages:**
- O(1) cache invalidation vs O(N * (V+E)) recomputation
- Fast forward simulation when many tasks to schedule
- Pre-computed targets avoid redundant work

**Disadvantages:**
- Approximation may diverge from real scheduler behavior
- Cache entries become stale (targets with scheduled deps may still appear)
- Different code path than main scheduler can lead to bugs

## Implementation Details

### Files Involved

- `rust/src/critical_path/rollout/mod.rs`: `CriticalPathCache` struct and methods
- `rust/src/critical_path/rollout/simulation.rs`: `run_forward_simulation()` using the cache
- `rust/src/critical_path/rollout/detection.rs`: `find_competing_targets()` for rollout trigger

### Simulation Flow (Old)

```
1. check_rollout_skip() detects competing targets
2. Build CriticalPathCache from all_targets
3. Scenario A: Clone cache, add current task to scheduled, run simulation
4. Scenario B: Clone cache, skip current task, run simulation
5. Compare scores, decide whether to skip
```

### Key Differences from Main Scheduler

| Aspect | Main Scheduler | Old Simulation |
|--------|---------------|----------------|
| Critical path calculation | Every iteration | Once at start, then invalidate |
| Urgency computation | `compute_urgency_with_context()` | `score_target()` directly |
| Task selection | Full eligible task check | Only from cached critical paths |
| Target ranking | Fresh computation | From stale cache |

## Restoring This Optimization

If profiling shows rollout simulation is a performance bottleneck:

1. Add a configuration option to choose simulation mode (full vs cached)
2. Implement hybrid approach: use cache but recompute after N tasks scheduled
3. Consider incremental critical path updates instead of full invalidation
4. Profile specific scenarios to understand the cost/benefit tradeoff

## Related Code (New Approach)

The new approach runs the actual scheduler for simulation:

```rust
fn simulate_rollout(&self, state: CriticalPathSchedulerState, horizon: NaiveDate) -> SimulationResult {
    let mut scheduler = self.clone_for_simulation(state);
    scheduler.set_horizon(horizon);
    let result = scheduler.run_from_state();
    SimulationResult { scheduled_tasks: result, score: evaluate_schedule(&result) }
}
```

This ensures simulation behavior exactly matches the real scheduler, eliminating bugs from logic divergence.
