# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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