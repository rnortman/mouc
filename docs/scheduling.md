# Gantt Scheduling Algorithm

This document describes the resource-constrained project scheduling algorithm used by the Mouc Gantt scheduler.

## Overview

The scheduler implements a variant of the **Parallel Schedule Generation Scheme (Parallel SGS)**, a standard algorithm for Resource-Constrained Project Scheduling Problems (RCPSP). The algorithm schedules tasks to:

1. **Respect dependencies** - Tasks only start after their dependencies complete (including lag)
2. **Respect constraints** - Honor `start_after` and `end_before` dates
3. **Manage resources** - Prevent resource over-allocation
4. **Minimize gaps** - Fill available time slots as early as possible
5. **Prioritize intelligently** - Use Critical Ratio and Priority to determine task urgency

## Algorithm Phases

The scheduling algorithm consists of three phases:

### Phase 1: Topological Sort

First, we compute a topological ordering of tasks based on the dependency graph. This ensures we can:
- Process tasks in a valid order for the backward pass
- Detect circular dependencies (which would make scheduling impossible)

```python
topo_order = topological_sort(tasks, dependencies)
```

### Phase 2: Backward Pass (Deadline Propagation)

We calculate the latest acceptable finish date for each task by:

1. **Initialize** with explicit deadlines:
   - Tasks with `end_before` constraints get that as their latest date
   - Tasks with `timeframe` get the end of that timeframe as their latest date

2. **Propagate** deadlines backward through dependencies:
   - If task B depends on task A, and B must finish by date X
   - Then A must finish by (X - duration_of_B)
   - If A already has a deadline, use the earlier of the two

```python
latest_dates = {}

# Initialize with explicit deadlines
for task in tasks:
    if task.end_before:
        latest_dates[task] = task.end_before
    elif task.timeframe:
        latest_dates[task] = end_of_timeframe(task.timeframe)

# Propagate backwards through dependency chain
for task in reverse(topo_order):
    if task in latest_dates:
        deadline = latest_dates[task]
        for dependency in task.requires:
            dep_deadline = deadline - duration(task)
            if dependency in latest_dates:
                latest_dates[dependency] = min(latest_dates[dependency], dep_deadline)
            else:
                latest_dates[dependency] = dep_deadline
```

### Phase 3: Forward Pass (Parallel SGS)

This is where actual scheduling happens. We advance through time chronologically, scheduling all eligible tasks at each time point.

```python
scheduled = {}
unscheduled = set(all_tasks)
resource_schedules = {r: ResourceSchedule() for r in resources}
current_time = current_date

while unscheduled:
    # Step 1: Find eligible tasks at current_time
    eligible = []
    for task in unscheduled:
        if all_dependencies_complete(task, scheduled):
            earliest_start = max(
                current_time,
                task.start_after or current_time,
                latest_dependency_end(task, scheduled) + 1
            )
            if earliest_start <= current_time:
                eligible.append(task)

    # Step 2: Sort by urgency (Critical Ratio + Priority)
    default_cr = compute_median_cr(unscheduled, current_time, latest_dates)
    eligible.sort(key=lambda t:
        compute_sort_key(t, current_time, latest_dates, default_cr)
    )

    # Step 3: Schedule tasks that fit
    scheduled_any = False
    for task in eligible:
        # Check resource availability
        if all_resources_available(task, current_time, resource_schedules):
            schedule_task(task, current_time, resource_schedules)
            scheduled[task] = (current_time, end_date)
            unscheduled.remove(task)
            scheduled_any = True

    # Step 4: Advance to next event
    if not scheduled_any:
        current_time = find_next_event_time(scheduled, unscheduled)
```

## Key Concepts

### Critical Ratio (CR)

**Critical Ratio** measures the urgency of a deadline task by comparing available time to work needed:

```
CR = slack / duration
```

Where:
- `slack` = days until deadline (from current scheduling time)
- `duration` = days of work needed

**Interpretation:**
- **CR = 1.0**: Exactly enough time, must start now (critical)
- **CR < 1.0**: Deadline will be missed without intervention
- **CR = 2-3**: Tight deadline, urgent
- **CR = 5-8**: Normal buffer
- **CR = 10+**: Relaxed, plenty of time

**Lower CR = more urgent**

**Example:**

At Jan 1, two tasks with the same deadline (Jan 31):
- Task A: duration 20 days → slack=30, CR=30/20=1.5 (tight, needs to start soon)
- Task B: duration 1 day → slack=30, CR=30/1=30.0 (relaxed, can wait)

CR correctly identifies that Task A needs to start earlier despite having the same deadline as Task B.

**Why Critical Ratio?**

The old approach sorted tasks by raw deadline, ignoring duration. This caused problems:
- Task with 1-day duration and Jan 31 deadline got same priority as
- Task with 20-day duration and Jan 31 deadline

CR fixes this by accounting for how long each task takes.

### Priority

**Priority** is a user-specified urgency indicator (0-100, default 50) in task metadata:

```yaml
task_id:
  effort: 5d
  resources: [alice]
  end_before: 2025-01-31
  meta:
    priority: 80  # Higher than default = more urgent
```

**For tasks with deadlines:** Priority represents "importance of meeting this deadline"
- High priority = treat as more urgent than CR alone suggests
- Low priority = treat as less urgent than CR alone suggests

**For tasks without deadlines:** Priority represents "general importance/urgency"
- High priority = should be done soon despite no deadline
- Low priority = background work, do when there's slack

**No-Deadline Tasks:**

Tasks without `end_before` constraints get assigned a **default CR** calculated as:
```
default_cr = max(max_cr × multiplier, floor)
```

Where:
- `max_cr` = highest CR among deadline-driven tasks
- `multiplier` = configurable (default 2.0)
- `floor` = configurable minimum (default 10.0)

This ensures no-deadline tasks are scheduled after deadline-driven work of similar priority:
- If max deadline CR is 5.0: default CR = max(5.0 × 2.0, 10.0) = 10.0
- If max deadline CR is 8.0: default CR = max(8.0 × 2.0, 10.0) = 16.0
- If no deadline tasks exist: default CR = floor (10.0)

### Scheduling Strategies

The scheduler combines CR and Priority using one of four configurable strategies:

**1. Weighted (default):**
```
score = cr_weight × CR + priority_weight × (100 - priority)
```
- Default weights: `cr_weight=10.0`, `priority_weight=1.0`
- Lower score = more urgent
- Smoothly blends both factors
- High priority can overcome moderate CR differences

**2. Priority-First (lexicographic):**
```
sort_key = (-priority, CR, task_id)
```
- Priority dominates, CR only breaks ties
- Use when priority is paramount

**3. CR-First (lexicographic):**
```
sort_key = (CR, -priority, task_id)
```
- CR dominates, priority only breaks ties
- Use when deadlines are critical

**4. ATC (Apparent Tardiness Cost):**
```
ATC = (priority / duration) × exp(-max(0, slack) / (K × avg_duration))
      ├── WSPT term ──────┤   ├── Urgency multiplier (0-1) ────────┤
```
- Combines weighted shortest processing time (WSPT) with exponential deadline urgency
- Higher ATC = more urgent (negated for sorting)
- **WSPT term** (`priority / duration`): High-priority short tasks score highest
- **Urgency multiplier**: Decays exponentially as slack increases
  - `slack ≤ 0` (deadline imminent/passed): urgency = 1.0 (maximum)
  - `slack > 0`: urgency = exp(-slack / (K × avg_duration))
- **K parameter** (`atc_k`): Controls urgency ramp-up speed
  - K = 1.5: Aggressive, urgency kicks in early
  - K = 3.0: Relaxed, only urgent near deadline
- **No-deadline tasks**: Get a computed default urgency (see below)
- Use when you need non-linear deadline urgency that ramps up as deadlines approach

**Default urgency for no-deadline tasks:**

Tasks without deadlines need an urgency value to compete with deadline-driven tasks. This is computed similarly to `default_cr`:

```
default_urgency = max(min_urgency × atc_default_urgency_multiplier, atc_default_urgency_floor)
```

Where `min_urgency` is the **lowest** urgency among deadline-driven tasks (the most relaxed task with a deadline). This ensures no-deadline tasks get urgency relative to the current project state:
- If deadlines are tight (high min urgency), no-deadline tasks get higher urgency
- If deadlines are relaxed (low min urgency), no-deadline tasks get lower urgency
- The floor ensures no-deadline tasks always have some urgency (default 0.3)

### Eligible Tasks

A task is **eligible** at time T if:
- All its dependencies are complete
- Its `start_after` constraint (if any) is satisfied: `start_after <= T`
- Its earliest possible start (considering dependencies) is `<= T`

### Resource Tracking

Resources are tracked using a `ResourceSchedule` object that maintains a sorted list of busy periods:

```python
class ResourceSchedule:
    def __init__(self):
        self.busy_periods = []  # List of (start_date, end_date) tuples

    def is_available(self, start, duration):
        # Check if resource is free for the entire duration starting at start

    def add_busy_period(self, start, end):
        # Add a new busy period, maintaining sorted order
```

### Time Advancement

When no eligible tasks can be scheduled at the current time, we advance to the next "event":
- **Task completion**: When a running task finishes, freeing its resources
- **Constraint satisfaction**: When a `start_after` date is reached
- **Dependency completion**: When a task's last dependency finishes

## Example Walkthrough

Consider three tasks, all requiring the same resource "alice":

```yaml
task_A:
  effort: 20d
  resources: [alice]
  end_before: 2025-01-31  # 30 days out

task_B:
  effort: 5d
  resources: [alice]
  end_before: 2025-01-31  # Same deadline, but shorter!
  meta:
    priority: 50

task_C:
  effort: 5d
  resources: [alice]
  start_after: 2025-02-01  # Can't start until February
  meta:
    priority: 80  # High priority
```

**Backward Pass Results:**
- task_A: latest_date = 2025-01-31 (explicit deadline)
- task_B: latest_date = 2025-01-31 (same deadline)
- task_C: latest_date = None (no deadline)

**Forward Pass Execution (starting Jan 1, 2025):**

*Time = 2025-01-01:*
- Eligible: task_A, task_B (both have satisfied constraints)
- NOT eligible: task_C (start_after > current_time)
- Compute CRs:
  - task_A: CR = 30/20 = 1.5 (tight! needs to start soon)
  - task_B: CR = 30/5 = 6.0 (relaxed, can wait)
- Default CR for no-deadline tasks: max(6.0 × 2.0, 10.0) = 12.0
- Compute weighted scores (cr_weight=10, priority_weight=1):
  - task_A: 10×1.5 + 1×50 = 65
  - task_B: 10×6.0 + 1×50 = 110
- Sort: [task_A (65), task_B (110)] — task_A wins despite same deadline!
- Schedule: task_A from Jan 1-21
- Alice is now busy until Jan 21

*Time = 2025-01-22:*
- Eligible: task_B (no constraints)
- NOT eligible: task_C (start_after > current_time)
- Schedule: task_B from Jan 22-27
- Alice is now busy until Jan 27

*Time = 2025-01-28:*
- No eligible tasks (task_C still can't start)
- Advance to next event: 2025-02-01

*Time = 2025-02-01:*
- Eligible: task_C (start_after satisfied)
- No deadline tasks left, so task_C gets default CR = floor (10.0)
- Schedule: task_C from Feb 1-6

**Result:** CR-based scheduling correctly prioritized the long-duration task (task_A) over the short-duration task (task_B) even though they had the same deadline. The old deadline-only approach would have scheduled them arbitrarily or by task ID, potentially missing the Jan 31 deadline for task_A.

## Differences from Priority Queue Approach

The previous (buggy) implementation used a different approach:

```python
# OLD APPROACH (creates gaps)
priority_queue = sort_all_tasks_by_urgency()
while priority_queue:
    task = priority_queue.pop()  # Highest global urgency
    earliest = find_earliest_valid_start(task)
    schedule(task, earliest)  # Might be far in future!
```

Problems with this approach:
- Tasks are processed in a fixed global order
- A task with `start_after: December` might be processed before unconstrained tasks
- This "reserves" the resource even though the task can't start yet, creating gaps

The Parallel SGS approach fixes this by:
- Processing time chronologically, not task-by-task
- Only considering tasks that can start "now"
- Filling each time slot before advancing

## Special Cases

### Fixed Tasks

Tasks with explicit `start_date` and/or `end_date` are scheduled first, before the main algorithm runs. They "block out" their time slots in the resource schedules.

### Multiple Resources

When a task requires multiple resources (e.g., `resources: [alice, bob]`), all resources must be simultaneously available. The scheduler finds the earliest time when all required resources are free for the task's duration.

### Partial Allocation

Resources can be partially allocated (e.g., `resources: [alice:0.5]` for 50% allocation). The task duration is adjusted accordingly:
- If a 10-day task has 50% of Alice, it takes 20 calendar days
- During those 20 days, Alice is fully blocked from other tasks

### Unassigned Work

Tasks with no specified resources (or `resources: [unassigned]`) don't compete for resource slots and can be scheduled in parallel with other work.

### Dependency Lag

Dependencies can specify a **lag** — a minimum time that must pass after the dependency completes before the dependent task can start:

```yaml
entities:
  design_doc:
    type: capability
    name: Auth Design Doc
    meta:
      effort: "3d"
      resources: ["alice"]

  implementation:
    type: capability
    name: Auth Implementation
    requires:
      - design_doc + 1w   # Must wait 1 week after design completes
    meta:
      effort: "2w"
      resources: ["alice"]
```

**Lag syntax:** `entity_id + duration` where duration can be:
- `Nd` — N days (e.g., `task_a + 5d`)
- `Nw` — N weeks (e.g., `task_a + 2w` = 14 days)
- `Nm` — N months (e.g., `task_a + 1m` = 30 days)

**Use cases:**
- Review/signoff periods between design and implementation
- Deployment bake time before enabling dependents
- Waiting for external team feedback
- Compliance review periods

**How it works:**
- During forward scheduling, a task with lagged dependencies can only start after `dependency_end + 1 day + lag`
- During backward deadline propagation, lag is subtracted from the dependent's deadline to compute the dependency's deadline

Lag can be specified on both `requires` and `enables`:
```yaml
# These are equivalent:
task_a:
  enables: [task_b + 1w]

task_b:
  requires: [task_a + 1w]
```

When edges are made bidirectional, lag is preserved on both sides.

## Performance Characteristics

- **Time Complexity**: O(n² × m) where n = number of tasks, m = number of time events
  - In practice, m is small (typically < 100 events)
  - For typical project sizes (< 1000 tasks), this performs well

- **Space Complexity**: O(n × r) where r = number of resources
  - Need to track busy periods for each resource
  - ResourceSchedule uses sorted lists for efficient interval queries

## Configuration

The scheduler supports configurable prioritization strategies via `mouc_config.yaml`:

```yaml
scheduler:
  strategy: "weighted"       # "priority_first" | "cr_first" | "weighted" | "atc"
  cr_weight: 10.0           # Weight for critical ratio in weighted strategy
  priority_weight: 1.0      # Weight for priority in weighted strategy
  default_priority: 50      # Default priority for tasks without metadata (0-100)
  default_cr_multiplier: 2.0  # Multiplier for computing default CR
  default_cr_floor: 10.0    # Minimum default CR for no-deadline tasks
  # ATC strategy parameters (only used when strategy: atc)
  atc_k: 2.0                         # Lookahead parameter (1.5-3.0 typical)
  atc_default_urgency_multiplier: 1.0  # Multiplier for default urgency
  atc_default_urgency_floor: 0.3     # Minimum urgency for no-deadline tasks
```

**Default values** (if not specified):
- `strategy: "weighted"`
- `cr_weight: 10.0`
- `priority_weight: 1.0`
- `default_priority: 50`
- `default_cr_multiplier: 2.0`
- `default_cr_floor: 10.0`
- `atc_k: 2.0`
- `atc_default_urgency_multiplier: 1.0`
- `atc_default_urgency_floor: 0.3`

These parameters control how CR and Priority are combined to determine task urgency.

**Priority in YAML:**

Add priority to task metadata:

```yaml
capabilities:
  - id: auth_service
    name: "Authentication Service"
    meta:
      effort: "20d"
      priority: 80  # High priority (0-100, default 50)
      resources: ["backend_team"]
      end_before: "2025-01-31"
```

## DNS-Aware Scheduling with Completion-Time Foresight

The scheduler accounts for DNS (Do Not Schedule) periods when making resource assignments:

- **DNS interruptions are allowed**: Tasks can start before DNS and resume after, if this completes the task sooner than waiting for an alternative resource
- **Completion-time comparison**: For auto-assigned tasks (`*` or `alice|bob`), the scheduler compares when each candidate resource would actually complete the task (accounting for DNS gaps), and picks the fastest
- **Greedy with foresight**: High-urgency tasks wait for the optimal resource if it's not immediately available, while lower-urgency tasks backfill with available resources
- **Multi-resource tasks**: Tasks with multiple explicit resources (e.g., `[alice, bob]`) schedule when all resources are available and calculate completion time based on the slowest resource

This allows the scheduler to make globally better decisions (e.g., "start now with a short DNS interruption" vs "wait for a resource with a long delay") while maintaining the efficient greedy chronological processing of Parallel SGS.

## Debug Mode

The scheduler supports debug output at multiple verbosity levels using the `-v` CLI flag:

```bash
mouc gantt feature_map.yaml -v 1    # Basic output
mouc gantt feature_map.yaml -v 2    # Detailed output
mouc gantt feature_map.yaml -v 3    # Full debug trace
```

### Verbosity Levels

**Level 0 (default)** - Silent
- No scheduling debug output

**Level 1 (`-v 1`)** - Basic
- Shows current date at each scheduling time step
- Shows task assignments with resource and date ranges
- Example output:
  ```
  Time: 2025-01-01
  Scheduled task task_A on alice from 2025-01-01 to 2025-01-21
  Time: 2025-01-22
  Scheduled task task_B on alice from 2025-01-22 to 2025-01-27
  ```

**Level 2 (`-v 2`)** - Detailed
- All of Level 1, plus:
- Shows each task being considered for scheduling
- Shows priority and critical ratio for each task
- Shows why tasks are skipped (resource conflicts, dependency issues)
- Shows which resource is selected for each task
- Example output:
  ```
  Time: 2025-01-01
  Considering task task_A (priority=50, CR=1.50)
  Selected alice for task_A (completes 2025-01-21)
  Scheduled task task_A on alice from 2025-01-01 to 2025-01-21
  Considering task task_B (priority=50, CR=6.00)
  Skipping task_B: Best resource alice not available until 2025-01-22
  ```

**Level 3 (`-v 3`)** - Full Debug Trace
- All of Level 2, plus:
- Shows all eligible tasks at each time step in urgency sort order
- Shows available resources at each time step
- Shows sort keys used for prioritization
- Shows time advancement decisions
- Example output:
  ```
  Time: 2025-01-01
  === Eligible tasks: 2, Available resources: alice ===
    task_A: priority=50, CR=1.50, sort_key=(65.0, 'task_A'), duration=20.0d
    task_B: priority=50, CR=6.00, sort_key=(110.0, 'task_B'), duration=5.0d
  Considering task task_A (priority=50, CR=1.50)
  Scheduled task task_A on alice from 2025-01-01 to 2025-01-21
  Considering task task_B (priority=50, CR=6.00)
  Skipping task_B: Best resource alice not available until 2025-01-22
  No tasks scheduled at 2025-01-01, advancing time to 2025-01-22
  ```

### Use Cases

- **Troubleshooting**: Understand why specific tasks are scheduled in a particular order
- **Validation**: Verify that priorities and critical ratios are computed correctly
- **Optimization**: Identify resource bottlenecks and scheduling inefficiencies
- **Learning**: Understand how the scheduler makes decisions

## Benefits

1. **No gaps**: The algorithm naturally fills available time slots
2. **Duration-aware**: CR accounts for task duration when prioritizing deadlines
3. **User control**: Priority metadata allows manual urgency adjustments
4. **Adaptive**: Default CR for no-deadline tasks adjusts based on deadline task urgency
5. **Predictable**: Chronological processing is intuitive
6. **Optimal**: Follows proven RCPSP scheduling approaches
7. **Flexible**: Handles various constraints (dependencies, time windows, resources, priorities)
8. **DNS-aware**: Accounts for DNS interruptions when choosing resources and calculating completion times
9. **Debuggable**: Multiple verbosity levels help understand scheduling decisions

## Bounded Rollout Algorithm

The scheduler also supports an advanced **Bounded Rollout** algorithm that can make better global decisions by simulating the impact of scheduling decisions.

### The Problem with Greedy Scheduling

The standard Parallel SGS makes locally optimal decisions at each time step. This can lead to globally suboptimal schedules:

**Example scenario:**
- Resource Alice is free now
- Task A (priority 30, no deadline) is eligible now and takes 10 days
- Task B (priority 90, deadline in 3 weeks) becomes eligible in 2 days (blocked by a dependency)
- Greedy scheduler assigns Task A to Alice immediately
- When Task B becomes eligible on day 2, Alice is busy until day 10
- Task B starts on day 10, finishes day 20, cutting it close on the deadline
- **Better decision**: Leave Alice idle for 2 days, assign Task B on day 3, it finishes day 13 with margin. Then assign Task A.

### How Bounded Rollout Works

When about to schedule a low-priority task, the scheduler checks if a higher-priority task will become eligible before the current task would complete. If so, it runs a bounded simulation:

1. **Scenario A**: Schedule the current task, run greedy until horizon
2. **Scenario B**: Skip the current task (stay idle), run greedy until horizon
3. **Compare** both scenarios using an objective function
4. **Choose** the better option

The "horizon" is when the current task would complete, keeping computation bounded.

### Configuration

Enable bounded rollout via CLI or config:

```bash
mouc gantt feature_map.yaml --algorithm bounded_rollout
```

Or in `mouc_config.yaml`:

```yaml
scheduler:
  algorithm:
    type: bounded_rollout
  rollout:
    priority_threshold: 70      # Trigger for tasks below this priority
    min_priority_gap: 20        # Minimum priority gap to consider
    cr_relaxed_threshold: 5.0   # Trigger for tasks with CR above this
    min_cr_urgency_gap: 3.0     # Minimum CR gap to consider
```

**Parameters:**
- `priority_threshold`: Trigger rollout for tasks with priority below this (default: 70)
- `min_priority_gap`: The upcoming task must have priority at least this much higher (default: 20)
- `cr_relaxed_threshold`: Trigger rollout for tasks with CR above this, even if priority is high (default: 5.0)
- `min_cr_urgency_gap`: The upcoming task must have CR at least this much lower to be considered more urgent (default: 3.0)

**Triggering Logic:**

Rollout triggers when the current task is "relaxed" (low priority OR high CR) and a more urgent task is coming:

1. **Relaxed task**: Either `priority < priority_threshold` OR `CR > cr_relaxed_threshold`
2. **Urgent upcoming task**: Either `priority >= current + min_priority_gap` OR (`CR_diff >= min_cr_urgency_gap` AND `priority >= current - min_priority_gap`)

### Objective Function

The rollout compares scenarios using a score (lower is better):

**For scheduled tasks:**
- **Start time penalty**: `days_from_start × (priority / 100)` — earlier starts for high-priority tasks are better
- **Tardiness penalty**: `days_late × priority × 10` — heavy penalty for missing deadlines

**For unscheduled tasks (within the horizon):**
- **Delay penalty**: `days_delayed × (priority / 100) × urgency_multiplier` — penalizes waiting, scaled by urgency
- **Expected tardiness**: If the task has a deadline, calculates how late it would be if scheduled at the horizon, and applies the same heavy tardiness penalty

The **expected tardiness** is key: if Task B (deadline Jan 12, duration 10 days) is unscheduled at horizon Jan 11, it would complete Jan 21 (9 days late). This adds a penalty of `9 × priority × 10`, making scenarios that leave urgent tasks unscheduled very costly.

### Explainability

Rollout decisions are logged and can be retrieved programmatically:

```python
scheduler = BoundedRolloutScheduler(tasks, current_date, config=config)
result = scheduler.schedule()
decisions = scheduler.get_rollout_decisions()

for decision in decisions:
    print(f"Task {decision.task_id} (pri={decision.task_priority}): "
          f"{'skipped' if decision.decision == 'skip' else 'scheduled'} "
          f"to wait for {decision.competing_task_id} (pri={decision.competing_priority})")
```

### When to Use Bounded Rollout

Use bounded rollout when:
- You have tasks with significantly different priorities
- Lower-priority tasks might block higher-priority work
- Schedule optimality is more important than scheduling speed

Use standard Parallel SGS when:
- All tasks have similar priorities
- Scheduling speed is critical
- The greedy solution is likely optimal

### Limitations

- **Not multi-level**: Rollout doesn't recurse (rollout within rollout)
- **No preemption**: Can't interrupt running tasks
- **Bounded horizon**: Only looks ahead to current task's completion time
- **Performance overhead**: Runs simulations, so slower than pure greedy

## Critical Path Scheduler

The critical path scheduler is an alternative approach that **eliminates priority contamination** - a problem where slack tasks inherit urgency from high-priority dependents in traditional backward-pass schedulers.

### The Priority Contamination Problem

With standard backward pass deadline propagation, consider this scenario:

```
Target A (priority 90, deadline Jan 31)
  └─ Slack Task (priority 20, no deadline)

Target B (priority 80, deadline Jan 31)
```

The backward pass propagates Target A's deadline to Slack Task, making it appear as urgent as A itself. But Slack Task has low priority (20) - it's not critical, just happens to be a dependency. The greedy scheduler may prioritize Slack Task over Target B's actual work, even though B is more important.

### How Critical Path Scheduling Works

The critical path scheduler takes a different approach:

1. **Every task is a potential target** - not just leaves, every unscheduled task
2. **Targets are scored by attractiveness**: `(priority / total_work) × urgency`
3. **Only critical path tasks are considered** - tasks with zero slack to the target
4. **Recalculate after each decision** - critical paths change as tasks complete

**Target Scoring:**
```
target_score = (priority / total_work) × urgency
```
- `priority`: Task's priority (0-100)
- `total_work`: Sum of all dependency durations leading to this target
- `urgency`: Exponential decay based on deadline proximity

This naturally favors **low-hanging fruit** (high priority, low total work) while respecting deadlines.

**Urgency Calculation:**
```
urgency = exp(-max(0, slack) / (K × avg_work))
```
- Tasks with tight deadlines get urgency → 1.0
- Tasks with slack get exponentially decreasing urgency
- No-deadline tasks get: `min(deadline_urgency) × multiplier`, with a floor

**Task Scoring (within critical path):**
```
task_score = priority / duration  # WSPT (Weighted Shortest Processing Time)
```

### Configuration

Enable via CLI:
```bash
mouc gantt feature_map.yaml --algorithm critical_path --rust
mouc schedule feature_map.yaml --algorithm critical_path --rust
```

Or in `mouc_config.yaml`:
```yaml
scheduler:
  algorithm:
    type: critical_path
  implementation: rust  # Required - critical_path is Rust-only
  default_priority: 50             # Global setting used by all algorithms
  critical_path:
    k: 2.0                         # Urgency decay parameter
    no_deadline_urgency_multiplier: 0.5  # Multiplier for no-deadline tasks
    urgency_floor: 0.1             # Minimum urgency (prevents zero)
```

**Parameters:**
- `k` (default: 2.0): Controls urgency ramp-up. Lower = more aggressive (1.5), higher = relaxed (3.0)
- `no_deadline_urgency_multiplier` (default: 0.5): No-deadline tasks get `min_urgency × multiplier`
- `urgency_floor` (default: 0.1): Minimum urgency to prevent tasks from never scheduling

Note: The critical path scheduler uses the global `default_priority` from `SchedulingConfig`.

### When to Use Critical Path Scheduling

Use critical path scheduling when:
- You have complex dependency graphs with mixed priorities
- Low-priority tasks are blocking high-priority targets inappropriately
- You want "low-hanging fruit" behavior (quick wins first)
- Traditional greedy scheduling produces counterintuitive results

Use Parallel SGS or Bounded Rollout when:
- Dependency graphs are simple or flat
- All tasks have similar priorities
- You need the Python implementation (critical_path is Rust-only)

### Rollout for Resource Assignment

The critical path scheduler includes rollout simulation for resource assignment decisions. When about to assign a resource to a task, the scheduler checks if a higher-scored target has a critical path task that will need the same resource soon.

**How it works:**

1. **Detection**: Before committing to a resource assignment, check if any target with a higher score has a critical path task that:
   - Needs the same resource (via resource_spec expansion)
   - Becomes eligible before the current task would complete

2. **Simulation**: If competing targets exist, simulate two scenarios:
   - **Scenario A**: Schedule the current task now, run greedy until horizon
   - **Scenario B**: Skip the task (leave resource idle), run greedy until horizon

3. **Evaluation**: Compare scenarios using a hybrid score (lower is better):
   - Priority-weighted completion times for scheduled tasks
   - Heavy tardiness penalty (10x) for deadline violations
   - Delay penalty for unscheduled eligible tasks

4. **Decision**: If skipping produces a better score, leave the resource idle.

**Example:**
```
Target T1 (score=4): low_task (priority 40, 10 days) on alice
Target T2 (score=20): high_task (priority 100, 5 days) blocked by blocker (2 days)
```

Without rollout, greedy schedules low_task immediately, blocking alice until day 11. With rollout, the scheduler recognizes that high_task (better target score) will need alice on day 3, simulates both scenarios, and leaves alice idle to prioritize the higher-scored work.

**Configuration:**

```yaml
scheduler:
  algorithm:
    type: critical_path
  critical_path:
    rollout_enabled: true           # Enable rollout simulation (default)
    rollout_score_ratio_threshold: 1.0  # Competing target must have score >= ratio * current
    rollout_max_horizon_days: null  # Cap simulation depth (null = unlimited)
```

### Limitations

- **Rust only**: No Python implementation available
- **Recomputes each iteration**: More expensive than simple greedy (but still fast)

## CP-SAT Optimal Scheduler

The scheduler supports an **optimal** scheduling algorithm using Google OR-Tools CP-SAT (Constraint Programming with SAT solving). Unlike the greedy algorithms above, CP-SAT finds globally optimal solutions by exploring the entire solution space.

### When to Use CP-SAT

Use CP-SAT when:
- You need the **best possible** schedule, not just a good one
- Greedy algorithms produce schedules that miss deadlines or delay high-priority work
- You have complex constraint combinations that greedy heuristics handle poorly
- Schedule quality is more important than computation time

Use Parallel SGS or Bounded Rollout when:
- Schedules need to be computed in milliseconds
- The problem is large (500+ tasks)
- Greedy solutions are already good enough

### How It Works

CP-SAT models your scheduling problem mathematically and uses constraint programming to find optimal solutions:

1. **Variables**: Each task gets start/end time variables
2. **Constraints**: Dependencies, resource capacity, deadlines, start_after dates
3. **Objective**: Minimize tardiness + priority-weighted start times
4. **Solver**: Explores solutions systematically, proving optimality when possible

The solver considers **all valid schedules** and finds the one with the best objective value, rather than building a schedule incrementally like greedy algorithms.

### Configuration

Enable CP-SAT via CLI or config:

```bash
mouc gantt feature_map.yaml --algorithm cpsat
```

Or in `mouc_config.yaml`:

```yaml
scheduler:
  algorithm:
    type: cpsat
  cpsat:
    time_limit_seconds: 30.0    # Maximum solve time (null = no limit)
    num_workers: null           # Parallel threads (null = all cores, 1 = single-threaded)
    tardiness_weight: 100.0     # Penalty for deadline violations
    earliness_weight: 0.0       # Reward for slack before deadlines
    priority_weight: 1.0        # Weight for priority optimization
    random_seed: 42             # Seed for deterministic results
    use_greedy_hints: true      # Seed solver with greedy solution
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `time_limit_seconds` | 30.0 | Maximum solve time. Use `null` to run until optimal. |
| `num_workers` | null | Number of parallel threads. `null` uses all cores, `1` for deterministic. |
| `tardiness_weight` | 100.0 | Penalty multiplier for deadline violations |
| `earliness_weight` | 0.0 | Reward multiplier for finishing before deadlines (slack) |
| `priority_weight` | 1.0 | Multiplier for priority-based completion time optimization |
| `random_seed` | 42 | Fixed seed for reproducible results |
| `use_greedy_hints` | true | Run greedy scheduler first to seed CP-SAT with hints |
| `warn_on_incomplete_hints` | true | Warn if greedy hints are incomplete or rejected |
| `log_solver_progress` | false | Log solver progress at verbosity level 1 |

### Objective Function

CP-SAT minimizes a weighted combination of three terms:

**1. Tardiness (deadline violations):**
```
tardiness = Σ max(0, end_time - deadline) × priority
```
- Only applies to tasks with deadlines
- Higher priority tasks incur larger penalties for being late
- Weight controlled by `tardiness_weight`

**2. Earliness (slack before deadlines):**
```
earliness = Σ max(0, deadline - end_time) × priority
```
- Only applies to tasks with deadlines
- Rewards finishing before deadlines (buffer for unexpected issues)
- Weight controlled by `earliness_weight` (default 0 = disabled)
- Negative contribution (reward, not penalty)

**3. Priority-weighted completion times:**
```
priority_cost = Σ end_time × priority
```
- Encourages high-priority tasks to complete earlier
- A priority-90 task ending on day 10 costs 900
- A priority-20 task ending on day 10 costs 200
- Weight controlled by `priority_weight`

**Combined objective:**
```
minimize: tardiness_weight × tardiness
        - earliness_weight × earliness
        + priority_weight × priority_cost
```

**Tuning the weights:**

- **High `tardiness_weight`** (default 100): Prioritizes meeting deadlines. Good when deadlines are firm.
- **High `earliness_weight`**: Creates buffer time before deadlines - useful when "shit happens" and you want slack. Set to 10-50 to encourage finishing early.
- **High `priority_weight`**: Prioritizes getting high-priority work done early, even if it risks some deadline slippage. Good when priorities reflect business value.
- **Balanced weights**: Trade off between the objectives.

### Resource Modeling

CP-SAT uses **no-overlap constraints** to model resources:

- Each resource can only work on one task at a time
- DNS periods and fixed tasks are merged into blocked intervals
- The allocation value (e.g., `alice:0.5`) affects task duration but not concurrency

### Auto-Assignment

For tasks with `resource_spec` (e.g., `*` or `alice|bob`), CP-SAT:

1. Creates **optional intervals** for each candidate resource
2. Adds an **exactly-one constraint**: exactly one resource must be selected
3. The solver jointly optimizes assignment and scheduling

This can find better assignments than greedy "first available" selection.

### Fixed Tasks

Tasks with `start_on` or `end_on` are handled as constants:
- They're scheduled at their fixed times before optimization
- Other tasks schedule around them
- Dependencies on fixed tasks use the fixed dates

### Preprocessor

By default, CP-SAT **skips the backward pass preprocessor**. The preprocessor propagates deadlines backward through dependencies, which is essential for greedy algorithms but unnecessary for CP-SAT since it optimizes globally.

The default `preprocessor.type: auto` resolves to:
- `backward_pass` for Parallel SGS and Bounded Rollout
- `none` for CP-SAT

You can override this:
```yaml
scheduler:
  algorithm:
    type: cpsat
  preprocessor:
    type: backward_pass  # Force backward pass with CP-SAT
```

### Determinism

By default, CP-SAT uses all available CPU cores for faster solving, which may produce different results across runs. For **deterministic results**, set:

```yaml
cpsat:
  num_workers: 1  # Single-threaded for reproducibility
  random_seed: 42  # Fixed seed (default)
```

With these settings, the same inputs always produce the same schedule.

### Greedy Hints

By default (`use_greedy_hints: true`), CP-SAT runs the greedy Parallel SGS scheduler first to:

1. **Compute a tighter horizon**: Uses greedy makespan + 30 days instead of heuristic estimates. Smaller horizons mean faster solving.

2. **Provide complete solution hints**: Seeds the solver with values for ALL variables via `model.add_hint()`:
   - Start and end times for each task
   - Size variables (calendar span accounting for DNS gaps)
   - Resource selection for auto-assigned tasks
   - Per-resource size and completion variables
   - Objective variables (lateness, earliness for deadline tasks)

**Benefits:**
- Solver immediately has a feasible solution
- Better upper bound for pruning (branches worse than the hint are cut early)
- Faster time to first solution and often faster to optimal
- Complete hints allow OR-Tools to verify feasibility immediately

**Production validation:**

By default (`warn_on_incomplete_hints: true`), a warning is logged if hints are incomplete:
```
CP-SAT greedy hints incomplete: 3 hints provided but solver reports 'accepted (partial)'. This may indicate a bug in hint generation.
```

**Solver progress logging:**

Enable `log_solver_progress: true` to see the full OR-Tools solver trace at verbosity level 1 (`-v 1`). This shows search progress, hint acceptance, and solution quality over time.

**When to disable:**
- If greedy and optimal solutions differ significantly (hints may slow search)
- For benchmarking raw CP-SAT performance

```yaml
scheduler:
  cpsat:
    use_greedy_hints: false  # Disable greedy seeding
    warn_on_incomplete_hints: false  # Disable warning
    log_solver_progress: true  # Enable solver trace at -v 1
```

### Solution Status

The solver returns one of:
- **OPTIMAL**: Proven best solution
- **FEASIBLE**: Valid solution found, may not be optimal (time limit reached)
- **INFEASIBLE**: No valid schedule exists (conflicting constraints)

Check `result.algorithm_metadata["status"]` to see which was returned.

### Performance Characteristics

| Problem Size | Expected Time | Solution Quality |
|--------------|---------------|------------------|
| < 100 tasks | Seconds | Optimal likely |
| 100-200 tasks | Seconds to 1 minute | Optimal or near-optimal |
| 200-300 tasks | 1-5 minutes | Good feasible |
| 300+ tasks | May hit time limit | Feasible, quality varies |

For large problems, increase `time_limit_seconds` or use Bounded Rollout.

### Example

```yaml
# mouc_config.yaml
scheduler:
  algorithm:
    type: cpsat
  cpsat:
    time_limit_seconds: 60.0      # Allow up to 1 minute
    tardiness_weight: 100.0       # Strong penalty for missing deadlines
    priority_weight: 2.0          # Moderate priority optimization
```

```yaml
# feature_map.yaml
entities:
  critical_feature:
    type: capability
    meta:
      effort: 10d
      priority: 95
      end_before: 2025-02-01
      resources: [alice]

  nice_to_have:
    type: capability
    meta:
      effort: 5d
      priority: 30
      resources: [alice]
```

With these inputs, CP-SAT will:
1. Ensure `critical_feature` meets its deadline (priority 95 × tardiness is expensive)
2. Schedule `critical_feature` before `nice_to_have` (priority 95 vs 30)
3. Find the globally optimal ordering, not just a greedy approximation

### Comparison with Other Algorithms

| Feature | Parallel SGS | Bounded Rollout | Critical Path | CP-SAT |
|---------|--------------|-----------------|---------------|--------|
| Speed | Fast (ms) | Moderate (ms-s) | Fast (ms) | Slow (s-min) |
| Solution quality | Good | Better | Better | Optimal* |
| Handles priority/deadline trade-offs | Heuristically | With lookahead | Per-target | Globally |
| Priority contamination | Yes | Yes | **No** | No |
| Deterministic | Yes | Yes | Yes | Yes |
| Scales to 500+ tasks | Yes | Yes | Yes | Limited |
| Explainability | High | High | High | Medium |
| Python implementation | Yes | Yes | No | Yes |
| Rust implementation | Yes | Yes | Yes | No |

*Optimal when solver completes; best-found when time-limited.

## Rust Implementation

The greedy schedulers (Parallel SGS and Bounded Rollout) have both Python and Rust implementations with identical behavior. The Critical Path scheduler is **Rust-only**. The Rust implementation offers better performance for large projects.

### Usage

Via CLI flag:
```bash
mouc gantt feature_map.yaml --rust
mouc schedule feature_map.yaml --rust
```

Via configuration:
```yaml
scheduler:
  implementation: "rust"  # or "python" (default)
  algorithm:
    type: parallel_sgs  # or bounded_rollout, critical_path
```

### When to Use Rust

- **Large projects**: 100+ tasks benefit from Rust's speed
- **Critical path scheduling**: Only available in Rust
- **Benchmarking**: Compare Python vs Rust performance
- **CI/CD pipelines**: Faster scheduling in automated workflows

Note: CP-SAT always uses Python (OR-Tools). Critical Path is Rust-only. Parallel SGS and Bounded Rollout have both implementations.

## Scenario Comparison

Compare "what-if" scenarios by exporting schedules to CSV and using the `compare` command.

### Exporting a Schedule

```bash
mouc schedule feature_map.yaml --output-csv baseline.csv
```

The CSV contains: `task_id`, `task_name`, `priority`, `deadline`, `completion_date`.

### Creating Scenarios

Modify your feature map (priorities, deadlines, resources, algorithm parameters) and export again:

```bash
# Tweak priorities or deadlines in feature_map.yaml
mouc schedule feature_map.yaml --output-csv scenario_high_priority.csv
```

### Comparing Scenarios

```bash
mouc compare baseline.csv scenario1.csv scenario2.csv -o comparison.csv
```

The comparison CSV includes:
- Task metadata from baseline (id, name, priority, deadline)
- `completion_baseline` - completion date from baseline
- `completion_<scenario>` - completion date per scenario (name from filename)
- `delta_<scenario>` - days difference vs baseline (positive = later, negative = earlier)

Missing tasks show blank values. Import to a spreadsheet for analysis.