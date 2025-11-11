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

Tasks without `end_before` constraints get assigned the **median CR** of all deadline tasks at each scheduling step. This median adapts as work progresses:
- Tight project (median CR=2): No-deadline work waits for urgent deadline work
- Relaxed project (median CR=20): No-deadline work gets scheduled sooner
- If no deadline tasks exist, fallback CR of 15.0 is used

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
- Median CR for no-deadline tasks: 3.75 (median of [1.5, 6.0])
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
- No deadline tasks left, so task_C gets fallback CR = 15.0
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
  default_cr: "median"      # Default CR for tasks without deadlines ("median" | numeric value)
```

**Default values** (if not specified):
- `strategy: "weighted"`
- `cr_weight: 10.0`
- `priority_weight: 1.0`
- `default_cr: "median"`

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

## Benefits

1. **No gaps**: The algorithm naturally fills available time slots
2. **Duration-aware**: CR accounts for task duration when prioritizing deadlines
3. **User control**: Priority metadata allows manual urgency adjustments
4. **Adaptive**: Median CR for no-deadline tasks adjusts to project urgency
5. **Predictable**: Chronological processing is intuitive
6. **Optimal**: Follows proven RCPSP scheduling approaches
7. **Flexible**: Handles various constraints (dependencies, time windows, resources, priorities)
8. **DNS-aware**: Accounts for DNS interruptions when choosing resources and calculating completion times