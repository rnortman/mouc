# Gantt Scheduling Algorithm

This document describes the resource-constrained project scheduling algorithm used by the Mouc Gantt scheduler.

## Overview

The scheduler implements a variant of the **Parallel Schedule Generation Scheme (Parallel SGS)**, a standard algorithm for Resource-Constrained Project Scheduling Problems (RCPSP). The algorithm schedules tasks to:

1. **Respect dependencies** - Tasks only start after their dependencies complete
2. **Respect constraints** - Honor `start_after` and `end_before` dates
3. **Manage resources** - Prevent resource over-allocation
4. **Minimize gaps** - Fill available time slots as early as possible
5. **Meet deadlines** - Prioritize tasks by deadline urgency

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

    # Step 2: Sort by deadline urgency
    eligible.sort(key=lambda t: (
        latest_dates.get(t, date.max),  # Primary: deadline
        t.id                             # Secondary: stable sort
    ))

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
  effort: 5d
  resources: [alice]
  # No constraints

task_B:
  effort: 5d
  resources: [alice]
  end_before: 2025-11-20  # Deadline

task_C:
  effort: 5d
  resources: [alice]
  start_after: 2025-12-01  # Can't start until December
```

**Backward Pass Results:**
- task_B: latest_date = 2025-11-20 (explicit deadline)
- task_A: latest_date = None (no deadline)
- task_C: latest_date = None (no deadline)

**Forward Pass Execution:**

*Time = 2025-11-04:*
- Eligible: task_A (no constraints), task_B (no constraints)
- NOT eligible: task_C (start_after > current_time)
- Sort by deadline: [task_B (2025-11-20), task_A (None)]
- Schedule: task_B from Nov 4-9
- Alice is now busy until Nov 9

*Time = 2025-11-10:*
- Eligible: task_A (no constraints)
- NOT eligible: task_C (start_after > current_time)
- Schedule: task_A from Nov 10-15
- Alice is now busy until Nov 15

*Time = 2025-11-16:*
- No eligible tasks (task_C still can't start)
- Advance to next event: 2025-12-01

*Time = 2025-12-01:*
- Eligible: task_C (start_after satisfied)
- Schedule: task_C from Dec 1-6

**Result:** No gaps! Tasks are scheduled contiguously when possible, with deadline-constrained tasks getting priority.

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

## Benefits

1. **No gaps**: The algorithm naturally fills available time slots
2. **Deadline aware**: Tasks with deadlines get appropriate priority
3. **Predictable**: Chronological processing is intuitive
4. **Optimal**: Follows proven RCPSP scheduling approaches
5. **Flexible**: Handles various constraints (dependencies, time windows, resources)