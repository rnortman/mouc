# Mouc - Mapping Outcomes User stories and Capabilities

A lightweight dependency tracking system for software development that maps relationships between technical capabilities, user stories, and organizational outcomes.

## Overview

Mouc helps engineering teams, especially infrastructure and middleware teams, track and visualize dependencies between:

- **Capabilities** - Technical work your team builds (infrastructure, middleware, platform features)
- **User Stories** - What other teams need from you
- **Outcomes** - Business/organizational goals that depend on the work

This is **not** a project management system. It's a technical dependency tracker that answers "what depends on what" and "what blocks what."

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
    dependencies: []
    links:
      - jira:INFRA-123
    tags: [infrastructure]

  service_communication:
    type: user_story
    name: Service Communication
    description: Frontend team needs services to communicate
    dependencies: [message_bus]
    meta:
      requestor: frontend_team
    links:
      - jira:STORY-456

  q3_launch:
    type: outcome
    name: Q3 Product Launch
    description: Launch new product features in Q3
    dependencies: [service_communication]
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
    dependencies: []  # List of entity IDs this depends on
    links:
      - design:[DD-123](https://docs.google.com/document/d/abc123)
      - jira:INFRA-456
    tags: [critical, performance]  # Arbitrary tags

  message_bus:
    type: capability
    name: Inter-Process Message Bus
    description: Reliable message passing built on lock-free queue
    dependencies: [lock_free_queue]
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
    dependencies: [message_bus]  # Can depend on capabilities or other user stories
    meta:
      requestor: analytics_team  # Who asked for this
    links:
      - jira:STORY-100
    tags: [q2_commitment]

  mobile_app:
    type: outcome
    name: Mobile App Launch
    description: Launch new mobile application by Q3
    dependencies: [analytics_realtime]  # Can depend on user stories or capabilities
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
- `dependencies`: List of entity IDs this depends on
  - Capabilities can only depend on other capabilities
  - User stories can depend on capabilities or other user stories
  - Outcomes can depend on any entity (capabilities, user stories, or other outcomes)
- `links`: List of links in various formats:
  - `design:[DD-123](https://...)` - Design doc with markdown link
  - `jira:TICKET-123` - Jira ticket reference
  - `https://...` - Plain URL
- `tags`: List of arbitrary tags
- `meta`: Dictionary of metadata. Common fields include:
  - `timeframe`: Time period for timeline view (e.g., `"Q1 2025"`, `"Sprint 23"`)
  - `requestor`: Team or person requesting (for user stories)
  - `target_date`: Target completion date (for outcomes)

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

mouc graph --view timeline | dot -Tpng -o timeline.png
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
git clone https://github.com/yourusername/mouc.git
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