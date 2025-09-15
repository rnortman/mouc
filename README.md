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

capabilities:
  message_bus:
    name: Inter-Process Message Bus
    description: |
      High-performance message passing system for services.
      Provides reliable, ordered message delivery.
    dependencies: []
    links:
      - jira:INFRA-123
    tags: [infrastructure]

user_stories:
  service_communication:
    name: Service Communication
    description: Frontend team needs services to communicate
    requires: [message_bus]
    requestor: frontend_team
    links:
      - jira:STORY-456

outcomes:
  q3_launch:
    name: Q3 Product Launch
    description: Launch new product features in Q3
    enables: [service_communication]
    links:
      - jira:EPIC-789
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
mouc graph all

# Critical path to a specific outcome
mouc graph critical-path --target q3_launch

# Filter by tags
mouc graph filtered --tags infrastructure monitoring
```

Render graphs with Graphviz:
```bash
mouc graph all | dot -Tpng -o graph.png
mouc graph all | dot -Tsvg -o graph.svg
```

## YAML Schema

### Full Example

```yaml
metadata:
  version: 1.0
  last_updated: 2024-01-15
  team: middleware

capabilities:
  lock_free_queue:
    name: Lock-Free Queue Implementation
    description: |
      High-performance thread-safe queue using atomic operations.
      
      Performance targets:
      - 10M ops/sec single producer/consumer
      - Sub-microsecond latency at p99
    dependencies: []  # List of capability IDs this depends on
    links:
      - design:[DD-123](https://docs.google.com/document/d/abc123)
      - jira:INFRA-456
    tags: [critical, performance]  # Arbitrary tags

  message_bus:
    name: Inter-Process Message Bus
    description: Reliable message passing built on lock-free queue
    dependencies: [lock_free_queue]
    links:
      - jira:INFRA-789
    tags: [infrastructure]

user_stories:
  analytics_realtime:
    name: Real-time Analytics Pipeline
    description: |
      Analytics team needs to process streaming data at 100Hz
      with strict latency requirements.
    requires: [message_bus]  # Required capabilities
    requestor: analytics_team  # Who asked for this
    links:
      - jira:STORY-100
    tags: [q2_commitment]

outcomes:
  mobile_app:
    name: Mobile App Launch
    description: Launch new mobile application by Q3
    enables: [analytics_realtime]  # User stories that deliver this
    links:
      - jira:EPIC-1000  # Always present for exec visibility
    target_date: 2024-Q3
    tags: [company_priority]
```

### Field Reference

**Required fields** for all entities:
- `name`: Human-readable name
- `description`: Can be single line or multi-paragraph markdown

**Optional fields**:

For capabilities:
- `dependencies`: List of capability IDs this depends on
- `links`: List of links in various formats:
  - `design:[DD-123](https://...)` - Design doc with markdown link
  - `jira:TICKET-123` - Jira ticket reference
  - `https://...` - Plain URL
- `tags`: List of arbitrary tags

For user stories:
- `requires`: List of required capability IDs
- `requestor`: Team or person requesting
- `links`: List of links (same format as capabilities)
- `tags`: List of arbitrary tags

For outcomes:
- `enables`: List of user story IDs that deliver this outcome
- `links`: List of links (usually includes jira:EPIC-xxx for exec visibility)
- `target_date`: Target completion date (e.g., "2024-Q3")
- `tags`: List of arbitrary tags

## Use Cases

### Find Critical Path

What needs to be done for the Q3 launch?
```bash
mouc graph critical-path --target q3_launch | dot -Tpng -o critical_path.png
```

### Filter by Team

What infrastructure work is planned?
```bash
mouc graph filtered --tags infrastructure | dot -Tpng -o infra_work.png
```

### Generate Reports

Create documentation for architecture review:
```bash
mouc doc --output architecture_review.md
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