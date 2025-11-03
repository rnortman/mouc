# Mouc - Mapping Outcomes User stories and Capabilities

A lightweight dependency tracking system for software development that maps relationships between technical capabilities, user stories, and organizational outcomes.

## Overview

Mouc helps engineering teams track and visualize dependencies between:

- **Capabilities** - Technical work your team builds
- **User Stories** - What other teams need from you
- **Outcomes** - Business/organizational goals that depend on the work

This is **not** a project management system. It's a technical dependency tracker that answers "what depends on what" and "what blocks what."

Dependencies can be specified from either direction using `requires` (what this needs) or `enables` (what this unblocks), and the system automatically creates bidirectional edges.

## Installation

Install with uv (recommended):
```bash
uv pip install mouc
```

Or with pip:
```bash
pip install mouc
```

## Quick Start

1. Create a `feature_map.yaml` file:

```yaml
metadata:
  version: 1.0
  team: middleware_platform

entities:
  message_bus:
    type: capability
    name: Inter-Process Message Bus
    description: |
      High-performance message passing system for services.
      Provides reliable, ordered message delivery.
    enables: [service_communication]  # This unblocks the service communication story
    links:
      - jira:INFRA-123
    tags: [infrastructure]

  service_communication:
    type: user_story
    name: Service Communication
    description: Frontend team needs services to communicate
    requires: [message_bus]  # Or you can specify from this end
    meta:
      requestor: frontend_team
    links:
      - jira:STORY-456

  q3_launch:
    type: outcome
    name: Q3 Product Launch
    description: Launch new product features in Q3
    requires: [service_communication]
    links:
      - jira:EPIC-789
    meta:
      target_date: 2024-Q3
```

2. Generate documentation:
```bash
mouc doc
```

3. Generate dependency graph:
```bash
mouc graph all > deps.dot
dot -Tpng deps.dot -o deps.png
```

## Commands

### Documentation Generation

Generate markdown documentation from your feature map:

```bash
mouc doc                           # Output to stdout
mouc doc --output docs.md          # Output to file
mouc feature_map.yaml doc          # Specify input file
```

### Gantt Chart Scheduling

Generate Mermaid Gantt charts with resource-aware scheduling:

```bash
mouc gantt                         # Output to stdout
mouc gantt --output schedule.md    # Output to markdown file
mouc gantt --start-date 2025-01-01 # Set project start date
mouc gantt --title "Q1 Schedule"  # Custom chart title
```

Add scheduling metadata to entities in your YAML:
```yaml
meta:
  effort: "2w"                     # Duration (days, weeks, months)
  resources: ["alice", "bob"]      # Assigned people/teams
  timeframe: "2025q1"              # Quarter, week, month, etc.
  end_before: "2025-03-31"         # Hard deadline
```

See [docs/gantt.md](docs/gantt.md) for detailed documentation.

### Graph Generation

Generate dependency graphs in DOT format:

```bash
# All entities and relationships
mouc graph --view all

# Critical path to a specific outcome
mouc graph --view critical-path --target q3_launch

# Filter by tags
mouc graph --view filtered --tags infrastructure monitoring

# Timeline view grouped by timeframe
mouc graph --view timeline

# Timeframe-colored view (colors indicate time progression)
mouc graph --view timeframe-colored
```

Render graphs with Graphviz:
```bash
mouc graph --view all | dot -Tpng -o graph.png
mouc graph --view all | dot -Tsvg -o graph.svg
```

## YAML Schema

### Full Example

```yaml
metadata:
  version: 1.0
  last_updated: 2024-01-15
  team: middleware

entities:
  lock_free_queue:
    type: capability
    name: Lock-Free Queue Implementation
    description: |
      High-performance thread-safe queue using atomic operations.

      Performance targets:
      - 10M ops/sec single producer/consumer
      - Sub-microsecond latency at p99
    requires: []  # List of entity IDs this depends on
    links:
      - design:[DD-123](https://docs.google.com/document/d/abc123)
      - jira:INFRA-456
    tags: [critical, performance]  # Arbitrary tags

  message_bus:
    type: capability
    name: Inter-Process Message Bus
    description: Reliable message passing built on lock-free queue
    requires: [lock_free_queue]
    links:
      - jira:INFRA-789
    tags: [infrastructure]
    meta:
      timeframe: Q1 2025  # Optional: for timeline view

  analytics_realtime:
    type: user_story
    name: Real-time Analytics Pipeline
    description: |
      Analytics team needs to process streaming data at 100Hz
      with strict latency requirements.
    requires: [message_bus]  # Can depend on capabilities or other user stories
    meta:
      requestor: analytics_team  # Who asked for this
    links:
      - jira:STORY-100
    tags: [q2_commitment]

  mobile_app:
    type: outcome
    name: Mobile App Launch
    description: Launch new mobile application by Q3
    requires: [analytics_realtime]  # Can depend on user stories or capabilities
    links:
      - jira:EPIC-1000  # Always present for exec visibility
    meta:
      target_date: 2024-Q3
    tags: [company_priority]
```

### Field Reference

**Required fields** for all entities:
- `type`: Entity type (`capability`, `user_story`, or `outcome`)
- `name`: Human-readable name
- `description`: Can be single line or multi-paragraph markdown

**Optional fields** for all entities:
- `requires`: List of entity IDs this depends on (what must be completed before this)
  - Capabilities can only depend on other capabilities
  - User stories can depend on capabilities or other user stories
  - Outcomes can depend on any entity (capabilities, user stories, or other outcomes)
- `enables`: List of entity IDs that depend on this (what this unblocks)
  - You can specify edges from either end - use `requires` OR `enables` or both
  - The system automatically creates bidirectional edges
- `dependencies`: ⚠️ **Deprecated** - Use `requires` instead (backward compatible)
- `links`: List of links in various formats:
  - `design:[DD-123](https://...)` - Design doc with markdown link
  - `jira:TICKET-123` - Jira ticket reference
  - `https://...` - Plain URL
- `tags`: List of arbitrary tags
- `meta`: Dictionary of metadata. Common fields include:
  - `timeframe`: Time period for timeline view (e.g., `"Q1 2025"`, `"Sprint 23"`)
  - `requestor`: Team or person requesting (for user stories)
  - `target_date`: Target completion date (for outcomes)

**Specifying Dependencies**:

You can specify edges from either direction:

```yaml
# Option 1: Specify what each entity requires
entities:
  cap1:
    type: capability
    name: Foundation
    requires: []

  cap2:
    type: capability
    name: Feature
    requires: [cap1]  # cap2 depends on cap1

# Option 2: Specify what each entity enables
entities:
  cap1:
    type: capability
    name: Foundation
    enables: [cap2]  # cap1 unblocks cap2

  cap2:
    type: capability
    name: Feature
    requires: []

# Option 3: Mix both (useful for complex graphs)
entities:
  cap1:
    type: capability
    name: Foundation
    enables: [cap2, cap3]

  cap2:
    type: capability
    name: Feature A
    requires: [cap1]
    enables: [story1]
```

All three examples create the same dependency graph. The system automatically resolves bidirectional edges.

## Styling System

Mouc provides a flexible styling system that lets you customize how graphs and markdown output are rendered. You can write Python functions to compute styles based on entity data and graph structure.

### Basic Usage

```bash
# Import from Python module (must be on PYTHONPATH)
mouc graph --style-module myproject.docs.styling

# Import from file path
mouc graph --style-file ./my_styles.py

# Same for markdown
mouc doc --style-module myproject.docs.styling
mouc doc --style-file ./my_styles.py
```

### Quick Example

```python
# my_styles.py
from mouc.styling import *

@style_node
def timeframe_colors(entity, context):
    """Color entities by their timeframe."""
    if 'timeframe' in entity.meta:
        timeframes = context.collect_metadata_values('timeframe')
        return {
            'fill_color': sequential_hue(
                entity.meta['timeframe'],
                timeframes,
                hue_range=(120, 230)
            )
        }
    return {}

@style_node(priority=20)
def highlight_blockers(entity, context):
    """Highlight entities that block company priorities."""
    priority_outcomes = [
        e for e in context.get_entities_by_type('outcome')
        if 'company_priority' in e.tags
    ]

    enabled = context.transitively_enables(entity.id)
    for outcome in priority_outcomes:
        if outcome.id in enabled:
            return {'border_color': '#ff0000', 'border_width': 3}
    return {}

@style_label
def custom_labels(entity, context):
    """Show custom labels in markdown output."""
    if entity.type == 'capability' and 'critical' in entity.tags:
        return '[🔥 Critical Capability]'
    return ''  # Use default label
```

See also the [full styling documentation](docs/styling.md).

## Use Cases

### Find Critical Path

What needs to be done for the Q3 launch?
```bash
mouc graph --view critical-path --target q3_launch | dot -Tpng -o critical_path.png
```

### Filter by Team

What infrastructure work is planned?
```bash
mouc graph --view filtered --tags infrastructure | dot -Tpng -o infra_work.png
```

### Generate Reports

Create documentation for architecture review:
```bash
mouc doc --output architecture_review.md
```

### View Timeline

Group work by time periods (quarters, sprints, etc.):
```bash
# Add timeframe metadata to entities:
# meta:
#   timeframe: "Q1 2025"

# Clustered by timeframe
mouc graph --view timeline | dot -Tpng -o timeline.png

# Colored by timeframe
mouc graph --view timeframe-colored | dot -Tpng -o timeframe_colored.png
```

## Best Practices

1. **Keep it current**: Update dependencies when architecture changes
2. **Don't over-specify**: Only use fields you need
3. **Rich descriptions**: Spend time documenting critical capabilities
4. **Consistent tags**: Agree on tag conventions with your team
5. **Version control**: Keep feature_map.yaml in git
6. **Review regularly**: Quarterly reviews to prune obsolete items

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/rnortman/mouc.git
cd mouc

# Install with development dependencies
uv pip install -e ".[dev]"
```

### Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=mouc

# Type checking
pyright

# Linting
ruff check src tests
ruff format src tests
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run linting and tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details