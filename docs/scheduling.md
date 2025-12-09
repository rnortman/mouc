# Gantt Scheduling Algorithm

This document describes the resource-constrained project scheduling algorithm used by the Mouc Gantt scheduler.

## Overview

The scheduler implements a variant of the **Parallel Schedule Generation Scheme (Parallel SGS)**, a standard algorithm for Resource-Constrained Project Scheduling Problems (RCPSP). The algorithm schedules tasks to:

1. **Respect dependencies** - Tasks only start after their dependencies complete
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

The scheduler combines CR and Priority using one of three strategies (currently hardcoded to `weighted`; configuration planned for future):

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
- During those 20 days, Alice is 50% busy and can do other 50% work

### Unassigned Work

Tasks with no specified resources (or `resources: [unassigned]`) don't compete for resource slots and can be scheduled in parallel with other work.

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
  strategy: "weighted"       # "priority_first" | "cr_first" | "weighted"
  cr_weight: 10.0           # Weight for critical ratio in weighted strategy
  priority_weight: 1.0      # Weight for priority in weighted strategy
  default_priority: 50      # Default priority for tasks without metadata (0-100)
  default_cr_multiplier: 2.0  # Multiplier for computing default CR
  default_cr_floor: 10.0    # Minimum default CR for no-deadline tasks
```

**Default values** (if not specified):
- `strategy: "weighted"`
- `cr_weight: 10.0`
- `priority_weight: 1.0`
- `default_priority: 50`
- `default_cr_multiplier: 2.0`
- `default_cr_floor: 10.0`

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