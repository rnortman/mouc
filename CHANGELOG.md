# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Gantt organization system: `@group_tasks` and `@sort_tasks` decorators for custom task organization
- Config-driven gantt grouping: `gantt.group_by` (none, type, resource, timeframe)
- Config-driven gantt sorting: `gantt.sort_by` (yaml_order, start, end, deadline, name, priority)
- CLI `--sort-by` option for gantt charts

### Changed
- Default gantt grouping changed from `type` to `none` (no sections)
- CLI `--group-by` option removed (use config or custom styling functions instead)

## [0.2.0] - 2025-11-18

### Added
- Global DNS periods: Company-wide DNS periods that apply to all resources (e.g., holidays, offsites)
- Format-specific styling: Decorators support `formats` parameter to filter by output format
- Gantt charts now display date axis at top via `topAxis: true`
- Markdown formatting in entity descriptions: Bold, italic, links, inline code, lists, and code blocks now supported in both markdown and DOCX output
- Timeline grouping: Infer timeframe from scheduler completion dates with configurable granularity (weekly, monthly, quarterly, half_year, yearly)
- Timeline sorting: Sort unscheduled section by completion date instead of entity type/ID
- Body organization: Use inferred timeframes in document body (not just ToC)
- Confirmed/inferred separation: Separate manual timeframes from auto-scheduled timeframes in output

### Changed
- "Requires" and "Enables" sections: markdown uses headings (h4/h5), DOCX uses bold text
- CLI exception handling removed to show full backtraces
- Entity ID, tags, and links now included in metadata, styleable via `@style_metadata` decorators

### Fixed
- Fixed task end dates now account for DNS periods when only start_date is specified
- Format filtering for `@style_metadata` decorators now works correctly

## [0.1.12] - 2025-11-13

### Fixed
- Missing source file from 0.1.11

## [0.1.11] - 2025-11-12

### Fixed
- DNS period handling edge case

### Added
- **Scheduling debug mode**: Use `-v 1/2/3` to view scheduling decisions at different detail levels
- **Verbose logging overhaul**: Improved logging structure and consistency

## [0.1.10] - 2025-11-11

### Added
- **Critical Ratio scheduling**: Scheduler now prioritizes tasks by CR (slack/duration) instead of raw deadlines, correctly accounting for task duration
- **Priority metadata field**: New `priority` field (0-100, default 50) controls task urgency independent of deadlines
- **Scheduling strategies**: Configurable via `SchedulingConfig` (programmatic only for now)
  - `priority_first`: Sort by priority, then CR (lexicographic)
  - `cr_first`: Sort by CR, then priority (lexicographic)
  - `weighted`: Composite score with tunable weights (default: CR-heavy with 10:1 ratio)
- **Adaptive median CR**: Tasks without deadlines automatically get median CR of deadline tasks, updated dynamically as work progresses
- **DNS-aware scheduling with completion-time foresight**: Scheduler now makes intelligent resource assignments accounting for DNS interruptions
  - Tasks can start before DNS and resume after if this completes sooner than waiting
  - Auto-assigned tasks compare completion times across resources and pick the fastest
  - High-urgency tasks wait for optimal resources while lower-urgency tasks backfill
- **DOCX output format**: `mouc doc --format docx` generates Microsoft Word documents
- **Markdown document organization**: New `markdown.organization` config controls entity grouping and sorting
  - Primary grouping: `by_type`, `by_timeframe`, `alpha_by_id`, or `yaml_order`
  - Secondary grouping: nest timeframes within types or types within timeframes
  - Configurable entity type order when using `by_type`
- **ToC suppression**: Set `markdown.toc_sections: []` to suppress table of contents

### Changed
- **Breaking**: `toc_sections` values changed from `["timeline", "capabilities", "user_stories", "outcomes"]` to `["timeline", "entity_types"]`
- **Breaking**: `markdown.sections` renamed to `markdown.toc_sections` for clarity
- **Breaking**: Refactored markdown generation to use pluggable backend architecture for future format support (docx, html)
- **Breaking**: Scheduler now uses CR-based prioritization; tasks with same deadline but different durations schedule differently

## [0.1.9] - 2025-11-09

### Fixed
- **Scheduler deadline propagation**: Fixed bug preventing deadlines from propagating through long dependency chains

### Added
- **Markdown output configuration**: New `markdown.sections` config controls which sections appear and in what order
- **Schedule annotations**: New `mouc schedule` command runs scheduling and outputs/persists results
- **Scheduling in doc command**: `mouc doc --schedule` computes annotations before rendering markdown
  - Enables styling functions to access and display computed scheduling information
  - Example styling file: `examples/schedule_markdown_style.py`
- **Gantt chart task styling**: Custom CSS colors for tasks via `@style_task` decorator (fill_color, stroke_color, text_color)
- **Gantt chart clickable links**: Tasks in gantt charts can now link to markdown documentation
- **Jira sync metadata**: New `jira_sync` metadata field controls sync behavior per entity
  - `ignore_fields`: Block specific fields from Jira sync entirely
  - `ignore_values`: Skip specific bad values from Jira history
  - `resolution_choices`: Remember user's conflict resolution decisions for future syncs
  - Validation layer detects invalid data (e.g., start_date > end_date) and creates conflicts
  - CLI commands: `jira ignore-field`, `jira ignore-value`, `jira show-overrides`
- **Unified configuration file**: New `mouc_config.yaml` format consolidates resources and Jira settings
- **`.netrc` credential support for Jira**: Jira credentials can now be retrieved from `~/.netrc` as an alternative to environment variables
- **Verbosity for Jira commands**: Global `-v/--verbose` flag with levels 0-3
  - **`jira sync`**:
    - Level 0 (default): Silent, only show summary
    - Level 1: Show field changes with "old → new" format
    - Level 2: Show all entities being checked, even without changes
    - Level 3: Debug mode with detailed Jira field extraction logging
    - `--dry-run` automatically enables verbosity level 1 if not already set
  - **`jira fetch`**:
    - Level 0 (default): Basic issue info and status transitions
    - Level 1: Enhanced display with status transition history
    - Level 2: Show all Jira fields from the issue
    - Level 3: Dump complete raw Jira API response (issue + changelog + field definitions)

### Changed
- **Breaking**: `mouc graph -v` short flag removed; use `--view` instead to avoid conflict with global verbosity flag
- **Breaking**: Separate `resources.yaml` and `jira_config.yaml` files no longer supported; must use unified `mouc_config.yaml`

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