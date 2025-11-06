# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`.netrc` credential support for Jira**: Jira credentials can now be retrieved from `~/.netrc` as an alternative to environment variables

## [0.1.8] - 2025-11-06

### Fixed
- **Scheduler now resumes work after DNS periods end**: Fixed a critical bug where the scheduler would fail to schedule tasks after resource DNS (Do Not Schedule) periods ended, leaving large gaps in the schedule even when resources were available. The scheduler now properly considers DNS period end dates when advancing time.

## [0.1.7] - 2025-11-06

### Added
- **Task completion tracking**: New `status: done` metadata field marks tasks as completed
  - Tasks with `status: done` and dates render with `:done` tag (gray) in Gantt charts
  - Tasks with `status: done` but no dates are excluded from Gantt output but satisfy dependencies
  - Warning generated for done tasks without dates: "Task '{id}' marked done without dates - excluded from schedule"
  - Done tasks without dates allow dependent tasks to start immediately
- **Alpha-quality Jira integration**: Adds the ability to query Jira for entities with `jira` links and sync start/end dates, status, and assignee. See [docs/jira.md](docs/jira.md) for information. This feature is very rough and is likely to change substantially in the future.

### Fixed
- Manual scheduling now correctly overrides DNS periods: tasks with explicit `start_date` or `end_date` are always scheduled at those times, even if the assigned resource has a DNS (Do Not Schedule) period during that time

## [0.1.6] - 2025-11-05

### Added
- **Automatic resource assignment**: Scheduler can now automatically assign tasks to resources
  - Resource configuration file (`resources.yaml`) defines available resources, DNS periods, and groups
  - Wildcard assignment: `resources: ["*"]` assigns to first available resource
  - Preference lists: `resources: ["alice|bob|charlie"]` tries resources in order
  - Resource groups: define aliases like `team_a: [alice, bob]` for convenient assignment
  - DNS (Do Not Schedule) periods block resource assignment during specified time ranges
  - `default_resource` configuration option for tasks with no explicit assignment
  - CLI option `--resources resources.yaml` to enable automatic assignment
  - Dynamic assignment respects deadline priorities (high-priority tasks get first pick)
- Gantt chart customization options for Mermaid output
  - `--tick-interval` option to control x-axis tick spacing (e.g., `1week`, `1month`, `3month`)
  - `--axis-format` option to customize date display format (e.g., `%Y-%m-%d`, `%b %Y`)
  - `--vertical-dividers` option to add visual markers for quarters, half-years, or years
  - `--compact` option

## [0.1.5] - 2025-11-04

### Added
- **Gantt chart scheduling**: New `mouc gantt` command generates resource-aware Gantt charts in Mermaid format
  - Resource-constrained project scheduling with deadline tracking and propagation
  - Support for effort estimates (`1d`, `2w`, `1.5m`, `L`) and resource allocations (`alice:0.5`)
  - Flexible timeframe parsing: quarters (`2025q1`), weeks (`2025w01`), months (`2025-01`)
  - Resource grouping option: `--group-by resource` to organize by person/team
  - Fixed-date tasks with `start_date`/`end_date` metadata
  - Visual indicators for deadline violations and unassigned tasks
  - Dual date system: `--start-date` for chart start, `--current-date` for scheduling baseline

## [0.1.4] - 2025-09-30

### Added
- Bidirectional edge specification: can now use `requires` and `enables` fields to specify dependencies from either direction
- **Styling system**: Flexible styling system for customizing graph and markdown output
  - User-defined styling functions via Python decorators (`@style_node`, `@style_edge`, `@style_label`)
  - Protocol-based API compatible with mypy/pyright
  - Priority-based composition of multiple style functions
  - Graph analysis context with transitive dependency queries
  - Utility functions for sequential color generation and contrast calculation
  - CLI options `--style-module` and `--style-file` for loading styling functions

### Changed
- Renamed `dependencies` field to `requires` (old field still works with deprecation warning)
- Markdown section headers changed from "Dependencies" to "Requires" and "Required by" to "Enables"
- Graph output now includes default styling that can be overridden by user styling functions

### Deprecated
- `dependencies` field is deprecated in favor of `requires` (backward compatible with warning to stderr)

## [0.1.3] - 2025-09-30

### Changed
- Updated graph coloring for better visibility

## [0.1.2] - 2025-09-30

### Added
- New `timeframe-colored` graph view that uses sequential colors to represent timeframes

## [0.1.1] - 2025-09-30

### Fixed
- Fixed backward-in-time dependency check to correctly flag scheduled entities depending on unscheduled entities as backward dependencies

## [0.1.0] - 2025-09-30

### Added
- Initial release
- YAML-based feature map tracking capabilities, user stories, and outcomes
- Entity dependency tracking and validation
- Markdown documentation generator with timeline view
- Graph visualization using Graphviz
- Backward dependency detection for timeline-scheduled entities
- CLI interface with commands for validation, markdown generation, and graph visualization
- Support for custom metadata fields on entities
- Link tracking (Jira, design docs, etc.)