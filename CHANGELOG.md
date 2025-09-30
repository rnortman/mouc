# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Bidirectional edge specification: can now use `requires` and `enables` fields to specify dependencies from either direction

### Changed
- Renamed `dependencies` field to `requires` (old field still works with deprecation warning)
- Markdown section headers changed from "Dependencies" to "Requires" and "Required by" to "Enables"

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