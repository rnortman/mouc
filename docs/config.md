# Mouc Configuration

Mouc uses a single unified configuration file (`mouc_config.yaml`) that contains both resource definitions and Jira integration settings.

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration File Location](#configuration-file-location)
- [File Structure](#file-structure)
- [Entity Types Section](#entity-types-section)
- [Resources Section](#resources-section)
  - [Task Priority](#task-priority)
- [Scheduler Section](#scheduler-section)
- [Style Tags Section](#style-tags-section)
- [Markdown Section](#markdown-section)
- [DOCX Section](#docx-section)
- [Jira Section](#jira-section)
- [Complete Example](#complete-example)

## Quick Start

1. Copy the example configuration:
   ```bash
   cp mouc_config.example.yaml mouc_config.yaml
   ```

2. Edit `mouc_config.yaml` to match your setup

3. Use with any command:
   ```bash
   mouc --config mouc_config.yaml jira validate
   mouc gantt feature_map.yaml  # Auto-detects mouc_config.yaml
   ```

## Configuration File Location

Mouc looks for configuration in this order:

1. **Explicit path**: `mouc --config /path/to/config.yaml <command>`
2. **Current directory**: `./mouc_config.yaml`
3. **No config**: Commands that don't require config will run without it

Global `--config` option works with all commands:
```bash
mouc --config myconfig.yaml gantt feature_map.yaml
mouc --config myconfig.yaml jira sync
```

## File Structure

The unified config file has several sections:

```yaml
# REQUIRED: Resource definitions
resources:
  - name: alice
    jira_username: alice@example.com
    dns_periods: []

groups:
  team_a: [alice, bob]

default_resource: "*"

# OPTIONAL: Gantt chart settings
gantt:
  markdown_base_url: "./feature_map.md"

# OPTIONAL: Scheduler configuration
scheduler:
  auto_constraint_from_timeframe: "both"  # "both", "start", "end", or "none"
  strategy: "weighted"
  cr_weight: 10.0
  priority_weight: 1.0
  default_priority: 50
  default_cr_multiplier: 2.0
  default_cr_floor: 10.0

# OPTIONAL: Style tags for filtering styler functions
style_tags:
  - detailed
  - color-by-team

# OPTIONAL: Markdown output settings
markdown:
  toc_sections: [timeline, entity_types]
  organization:
    primary: "by_type"
    entity_type_order: [capability, user_story, outcome]

# OPTIONAL: DOCX output settings
docx:
  table_style: "Table Grid"
  toc_sections: [timeline, entity_types]
  organization:
    primary: "by_type"
    entity_type_order: [capability, user_story, outcome]

# OPTIONAL: Jira integration settings
jira:
  base_url: "https://example.atlassian.net"
  strip_email_domain: false

field_mappings:
  # ... Jira field mappings

defaults:
  # ... Jira sync defaults
```

## Entity Types Section

The `entity_types` section defines valid entity types for your feature map. This section is **optional** - if not specified, defaults to `capability`, `user_story`, and `outcome`.

```yaml
entity_types:
  types:
    - name: capability
      display_name: Capability
    - name: user_story
      display_name: User Story
    - name: outcome
      display_name: Outcome
    - name: milestone        # Custom type
      display_name: Milestone
  default_type: capability   # Used when 'type' field omitted
```

**`types`** (optional): List of valid entity types. Each type has:
- **`name`**: Identifier used in YAML (e.g., `milestone`)
- **`display_name`**: Human-readable name for documentation (e.g., `Milestone`)

**`default_type`** (optional): Type assigned when entity has no explicit `type` field.

### Custom Entity Types

Define your own entity types to match your workflow:

```yaml
entity_types:
  types:
    - name: epic
      display_name: Epic
    - name: feature
      display_name: Feature
    - name: task
      display_name: Task
    - name: bug
      display_name: Bug Fix
  default_type: task
```

Entities with undefined types are rejected during validation:

```yaml
# feature_map.yaml
entities:
  my_thing:
    type: unknown_type  # Error: invalid type
    name: My Thing
```

### Format Migration

Mouc supports both the old 3-section format and the new unified `entities` format. The old format emits a deprecation warning:

```bash
# Convert old format to new format
mouc convert-format feature_map.yaml > feature_map_new.yaml
```

Old format (deprecated):
```yaml
capabilities:
  cap1: { name: Cap 1, description: Desc }
user_stories:
  story1: { name: Story 1, description: Desc }
```

New format (preferred):
```yaml
entities:
  cap1:
    type: capability
    name: Cap 1
    description: Desc
  story1:
    type: user_story
    name: Story 1
    description: Desc
```

## Resources Section

The `resources` section defines your team members and their availability. This section is **required** even if you're not using Jira.

### Resource Definitions

Each resource can have:

- **`name`** (required): Unique identifier for the resource
- **`jira_username`** (optional): Maps to Jira user email
- **`dns_periods`** (optional): Do-not-schedule periods (holidays, PTO, etc.)

```yaml
resources:
  - name: alice
    jira_username: alice@example.com
    dns_periods:
      - start: 2025-12-15
        end: 2026-01-01

  - name: bob
    jira_username: bob.smith@example.com
    dns_periods:
      - start: 2025-07-01
        end: 2025-07-15
      - start: 2025-12-20
        end: 2026-01-05
```

### Resource Groups

Define reusable team groupings:

```yaml
groups:
  backend_team:
    - alice
    - bob
  frontend_team:
    - charlie
    - diana
```

Use in feature maps:
```yaml
capabilities:
  api_work:
    meta:
      resources: backend_team  # Expands to [alice, bob]
```

### Default Resource

Specifies what to use for unassigned tasks:

```yaml
default_resource: "*"  # Any available resource
```

Options:
- `"*"` - Any available resource (wildcard)
- `"alice|bob"` - Specific resource(s)
- `"backend_team"` - Group alias
- `""` - Leave unassigned

See [Resources Documentation](resources.md) for detailed scheduling behavior.

### Task Priority

Tasks can include a `priority` field in their metadata to control scheduling urgency:

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

**Priority Scale (0-100):**
- `100` - Maximum priority (critical/urgent)
- `50` - Neutral/default (typical work)
- `0` - Minimum priority (nice-to-have)

**How Priority Works:**

The scheduler uses **Critical Ratio (CR)** to prioritize tasks, which accounts for both deadline and duration:
- `CR = slack / duration` where slack = days until deadline

Priority modulates the CR-based urgency:
- **For deadline tasks**: Priority represents "importance of meeting this deadline"
- **For no-deadline tasks**: Priority represents "general importance"

By default, the scheduler uses a weighted combination:
```
urgency_score = 10×CR + 1×(100-priority)
```

Lower score = more urgent. This gives CR 10× influence vs priority, meaning:
- A 50-point priority difference shifts urgency by ~5 CR units
- High priority tasks can overcome moderate CR differences
- Very urgent deadlines (low CR) still dominate

See [Scheduling Documentation](scheduling.md) for detailed CR and priority behavior.

## Scheduler Section

The `scheduler` section configures task prioritization strategies. This section is **optional** - defaults are used if not specified.

```yaml
scheduler:
  auto_constraint_from_timeframe: "both"  # "both", "start", "end", or "none"
  strategy: "weighted"       # Prioritization strategy
  cr_weight: 10.0           # Weight for critical ratio
  priority_weight: 1.0      # Weight for priority
  default_priority: 50      # Default priority for tasks without priority metadata
  default_cr_multiplier: 2.0  # Multiplier for computing default CR
  default_cr_floor: 10.0    # Minimum default CR
  algorithm:
    type: parallel_sgs      # "parallel_sgs" or "bounded_rollout"
  rollout:                  # Only used when algorithm is bounded_rollout
    priority_threshold: 70
    min_priority_gap: 20
    cr_relaxed_threshold: 5.0
    min_cr_urgency_gap: 3.0
```

**`auto_constraint_from_timeframe`** (optional, default: `"both"`): Controls how `timeframe` metadata creates scheduling constraints.

Valid values:
- `"both"` - Timeframe sets both `start_after` and `end_before` constraints
- `"start"` - Timeframe only sets `start_after` (task won't start before timeframe begins)
- `"end"` - Timeframe only sets `end_before` (task has deadline at timeframe end)
- `"none"` - Timeframe doesn't create any scheduling constraints (useful when timeframe is only for documentation/grouping)

Note: Explicit `start_after` or `end_before` values in entity metadata always override timeframe-derived constraints.

**`strategy`** (optional, default: `"weighted"`): How to prioritize tasks for scheduling.

Valid values:
- `"weighted"` - Combines CR and priority: `score = cr_weight×CR + priority_weight×(100-priority)` (lower = more urgent)
- `"cr_first"` - Sort by Critical Ratio first, then priority as tiebreaker
- `"priority_first"` - Sort by priority first, then CR as tiebreaker

**`cr_weight`** (optional, default: `10.0`): Weight multiplier for critical ratio in weighted strategy.

**`priority_weight`** (optional, default: `1.0`): Weight multiplier for priority in weighted strategy.

**`default_priority`** (optional, default: `50`): Default priority (0-100) for tasks without explicit priority metadata.

**`default_cr_multiplier`** (optional, default: `2.0`): Multiplier for computing default CR for tasks without deadlines. The default CR is calculated as `max(max_cr × multiplier, floor)` where `max_cr` is the highest CR among deadline-driven tasks.

**`default_cr_floor`** (optional, default: `10.0`): Minimum CR for tasks without deadlines. Ensures no-deadline tasks aren't scheduled too aggressively when all deadline tasks are urgent.

**`algorithm.type`** (optional, default: `"parallel_sgs"`): Scheduling algorithm to use.

Valid values:
- `"parallel_sgs"` - Standard greedy chronological scheduling (fast, good quality)
- `"bounded_rollout"` - Lookahead simulation for better priority handling
- `"cpsat"` - Optimal scheduling using OR-Tools constraint solver (slower, best quality)

**`preprocessor.type`** (optional, default: `"auto"`): Preprocessor to run before scheduling.

Valid values:
- `"auto"` - Uses `backward_pass` for greedy algorithms, `none` for CP-SAT
- `"backward_pass"` - Propagates deadlines/priorities backward through dependencies
- `"none"` - No preprocessing

**CP-SAT Configuration** (only used when `algorithm.type` is `"cpsat"`):

- **`time_limit_seconds`** (default: `30.0`): Maximum solver time. Use `null` to run until optimal.
- **`tardiness_weight`** (default: `100.0`): Penalty weight for deadline violations
- **`earliness_weight`** (default: `0.0`): Reward for finishing before deadlines (slack). Set to 10-50 to encourage buffer time.
- **`priority_weight`** (default: `1.0`): Weight for priority-based completion time optimization
- **`random_seed`** (default: `42`): Fixed seed for deterministic results
- **`use_greedy_hints`** (default: `true`): Run greedy scheduler first to seed CP-SAT with hints and compute a tighter horizon

**Rollout Configuration** (only used when `algorithm.type` is `"bounded_rollout"`):

- **`priority_threshold`** (default: `70`): Trigger rollout for tasks with priority below this
- **`min_priority_gap`** (default: `20`): Upcoming task must have priority at least this much higher
- **`cr_relaxed_threshold`** (default: `5.0`): Trigger rollout for tasks with CR above this (relaxed deadline)
- **`min_cr_urgency_gap`** (default: `3.0`): Upcoming task must have CR at least this much lower to be considered more urgent

**Strategy Examples:**

```yaml
# Deadline-focused (default): CR dominates, priority is tiebreaker
scheduler:
  strategy: "weighted"
  cr_weight: 10.0
  priority_weight: 1.0
```

```yaml
# Balance deadlines and priorities equally
scheduler:
  strategy: "weighted"
  cr_weight: 5.0
  priority_weight: 5.0
```

```yaml
# Priority-driven: high priority tasks scheduled first regardless of deadlines
scheduler:
  strategy: "priority_first"
```

```yaml
# Bounded rollout for better global decisions
scheduler:
  strategy: "priority_first"
  algorithm:
    type: bounded_rollout
  rollout:
    priority_threshold: 70
    min_priority_gap: 20
    cr_relaxed_threshold: 5.0
    min_cr_urgency_gap: 3.0
```

See [Scheduling Documentation](scheduling.md) for detailed algorithm behavior.

## Style Tags Section

The `style_tags` field specifies default style tags that control which styler functions are active. This section is **optional**.

```yaml
style_tags:
  - detailed
  - color-by-team
```

**`style_tags`** (optional, default: `[]`): List of tags to activate for styler function filtering.

Style tags work with the `tags` parameter on styler decorators (e.g., `@style_node(tags=['detailed'])`). A function only runs if at least one of its tags matches an active tag (OR logic). Functions without tags always run.

**Activation sources:**
- Config file: `style_tags` list (shown above)
- CLI: `--style-tags detailed,color-by-team`

CLI tags and config tags are merged together.

See [Styling Documentation](styling.md#tag-based-filtering) for details on declaring tags on functions.

## Markdown Section

The `markdown` section configures the markdown documentation output generated by `mouc doc --format markdown` (the default). This section is **optional** - defaults are used if not specified.

### Document Organization

Control how entities are organized in the markdown document body:

```yaml
markdown:
  organization:
    primary: "by_type"                              # How to group entities
    secondary: null                                 # Optional nested grouping
    entity_type_order: [capability, user_story, outcome]  # Order when using by_type
```

**`organization.primary`** (optional, default: `"by_type"`): Primary grouping method for entities.

Valid values:
- `by_type` - Group by entity type (## Capabilities, ## User Stories, ## Outcomes)
- `by_timeframe` - Group by timeframe metadata (## 2025-Q1, ## 2025-Q2, etc.)
- `alpha_by_id` - Alphabetical by entity ID (single ## Entities section)
- `yaml_order` - Preserve order from YAML file (single ## Entities section)

**`organization.secondary`** (optional, default: `null`): Secondary grouping within primary groups.

Valid values:
- `by_timeframe` - Create timeframe subsections (###) within primary groups
- `by_type` - Create type subsections (###) within primary groups
- `null` - No secondary grouping

**`organization.entity_type_order`** (optional, default: `["capability", "user_story", "outcome"]`): Order of entity types when using `by_type` primary grouping.

### Table of Contents Control

Control the table of contents generation:

```yaml
markdown:
  toc_sections: [timeline, entity_types]
  toc_timeline:
    infer_from_schedule: false
    inferred_granularity: null
    sort_unscheduled_by_completion: false
  organization:
    primary: by_type
    secondary: null
    entity_type_order: [capability, user_story, outcome]
    separate_confirmed_inferred: false
    timeline:
      infer_from_schedule: false
      inferred_granularity: null
```

**`toc_sections`** (optional, default: `["timeline", "entity_types"]`): Specifies which sections appear in the table of contents.

Valid section names:
- `timeline` - Timeline view grouped by timeframe (if entities have timeframe metadata)
- `entity_types` - All entity type sections (capabilities, user_stories, outcomes) in the order specified by `organization.entity_type_order`

Examples:
- `[timeline]` - TOC shows only timeline
- `[entity_types]` - TOC shows only entity type sections
- `[timeline, entity_types]` - TOC shows timeline followed by entity types
- `[entity_types, timeline]` - TOC shows entity types followed by timeline
- `[]` - No table of contents generated

Note: `toc_sections` only controls the table of contents navigation. The document body always contains all entities as organized by the `organization` configuration.

### Timeline Configuration

Mouc provides two independent timeline configurations:
- **ToC Timeline** (`toc_timeline`) - Controls timeline ToC section behavior
- **Body Timeline** (`organization.timeline`) - Controls body organization by timeframe

Both configurations use the same options and must be explicitly enabled.

#### ToC Timeline Configuration

Controls how the timeline ToC section groups and sorts entities:

```yaml
markdown:
  toc_timeline:
    infer_from_schedule: true
    inferred_granularity: weekly
    sort_unscheduled_by_completion: true
```

**`toc_timeline.infer_from_schedule`** (optional, default: `false`): When enabled with `mouc doc --schedule`, infers timeframe from scheduler completion dates for entities without manual `timeframe` metadata.

**`toc_timeline.inferred_granularity`** (required when `infer_from_schedule: true`): Granularity for grouping inferred timeframes. Valid values: `weekly`, `monthly`, `quarterly`, `half_year`, `yearly`.

**`toc_timeline.sort_unscheduled_by_completion`** (optional, default: `false`): When enabled, sorts unscheduled entities by `estimated_end` date instead of entity type/ID.

#### Body Timeline Configuration

Controls timeframe inference for body organization (when using `primary: by_timeframe` or `secondary: by_timeframe`):

```yaml
markdown:
  organization:
    primary: by_timeframe
    separate_confirmed_inferred: true
    timeline:
      infer_from_schedule: true
      inferred_granularity: quarterly
```

**`organization.timeline.infer_from_schedule`** (optional, default: `false`): When enabled with `mouc doc --schedule`, uses inferred timeframes from scheduler completion dates in addition to manual `timeframe` metadata.

**`organization.timeline.inferred_granularity`** (required when `infer_from_schedule: true`): Granularity for grouping inferred timeframes. Valid values: `weekly`, `monthly`, `quarterly`, `half_year`, `yearly`.

**`organization.timeline.separate_confirmed_inferred`** (optional, default: `false`): When enabled, creates separate sections for confirmed (manual) vs inferred (auto-scheduled) timeframes at the same heading level.

**`toc_timeline.separate_confirmed_inferred`** (optional, default: `false`): When enabled in ToC timeline section, creates separate sections for confirmed vs inferred timeframes.

**Timeframe Precedence**: Manual `timeframe` metadata always takes precedence over inferred timeframes from scheduler.

**Behavior:**
- Manual `timeframe` metadata always takes precedence over inferred timeframes
- Inference only applies when `--schedule` flag is used with `mouc doc`
- Configuration fails fast if `infer_from_schedule: true` without `inferred_granularity`
- Entities without completion dates sort to end when `sort_unscheduled_by_completion` is enabled

**Examples:**

ToC timeline with weekly inference:
```yaml
markdown:
  toc_timeline:
    infer_from_schedule: true
    inferred_granularity: weekly
```

Body organization with confirmed/inferred separation:
```yaml
markdown:
  organization:
    primary: by_timeframe
    timeline:
      infer_from_schedule: true
      inferred_granularity: quarterly
      separate_confirmed_inferred: true
```

Using both independently:
```yaml
markdown:
  toc_timeline:
    infer_from_schedule: true
    inferred_granularity: weekly  # ToC uses weekly grouping
  organization:
    primary: by_timeframe
    timeline:
      infer_from_schedule: true
      inferred_granularity: quarterly  # Body uses quarterly grouping
```

### Organization Examples

**Default behavior** (group by type):
```yaml
markdown:
  organization:
    primary: "by_type"
    entity_type_order: [capability, user_story, outcome]
```
Produces: ## Capabilities, ## User Stories, ## Outcomes

**Business-first view** (outcomes first):
```yaml
markdown:
  organization:
    primary: "by_type"
    entity_type_order: [outcome, user_story, capability]
```
Produces: ## Outcomes, ## User Stories, ## Capabilities

**Timeline-based organization**:
```yaml
markdown:
  organization:
    primary: "by_timeframe"
```
Produces: ## 2025-Q1, ## 2025-Q2, etc. (entities sorted by timeframe)

**Timeline with type subsections**:
```yaml
markdown:
  organization:
    primary: "by_timeframe"
    secondary: "by_type"
```
Produces: ## 2025-Q1 with ### Capabilities, ### User Stories, ### Outcomes

**Type sections with timeline subsections**:
```yaml
markdown:
  organization:
    primary: "by_type"
    secondary: "by_timeframe"
    entity_type_order: [capability, user_story, outcome]
```
Produces: ## Capabilities with ### 2025-Q1, ### 2025-Q2, then ## User Stories with its timeframes, etc.

**Alphabetical flat list**:
```yaml
markdown:
  organization:
    primary: "alpha_by_id"
```
Produces: Single ## Entities section with all entities sorted alphabetically

**Exclude entity types**:
```yaml
markdown:
  organization:
    primary: "by_type"
    entity_type_order: [capability, outcome]  # Omit user_story
```
Produces: Only ## Capabilities and ## Outcomes sections

**Suppress table of contents**:
```yaml
markdown:
  toc_sections: []  # No ToC
  organization:
    primary: "by_type"
```

## DOCX Section

The `docx` section configures the DOCX (Microsoft Word) documentation output generated by `mouc doc --format docx`. This section is **optional** - defaults are used if not specified.

### Table Styling

Control the appearance of tables in DOCX output:

```yaml
docx:
  table_style: "Table Grid"  # Word built-in table style name
```

**`table_style`** (optional, default: `"Table Grid"`): The built-in Word table style to apply to all tables in the document.

Common Word table styles:
- `"Table Grid"` (default) - Simple black grid lines, no colors
- `"Light Grid Accent 1"` - Light blue headers with grid lines
- `"Medium Shading 1 Accent 1"` - Blue shaded headers
- `"Colorful Grid"` - Colorful alternating rows
- `""` (empty string) - No styling (plain table)

### Document Organization

The `docx` section inherits the same organization options as the `markdown` section:

```yaml
docx:
  table_style: "Table Grid"
  toc_sections: [timeline, entity_types]
  organization:
    primary: "by_type"
    secondary: null
    entity_type_order: [capability, user_story, outcome]
  timeline:
    infer_from_schedule: false
    inferred_granularity: null
    sort_unscheduled_by_completion: false
```

All organization and timeline options work identically to the markdown section (see [Document Organization](#document-organization) and [Timeline Configuration](#timeline-configuration) above).

### Link Rendering

External links in metadata tables (design docs, Jira tickets, etc.) are automatically rendered as clickable blue underlined hyperlinks in Word:

```yaml
# In feature_map.yaml
entities:
  my_feature:
    links:
      - design:[DD-123](https://docs.google.com/document/d/abc123)  # Clickable link
      - jira:JIRA-456  # Plain text (no URL)
```

In the generated DOCX:
- Links with URLs are rendered as blue, underlined, clickable hyperlinks
- Links without URLs (e.g., `jira:JIRA-456`) are rendered as plain text

## Jira Section

The `jira` section configures integration with Jira. This section is **optional** - only needed if using Jira sync features.

### Connection Settings

```yaml
jira:
  base_url: "https://example.atlassian.net"
  strip_email_domain: false  # Opt-in domain stripping
  ignored_jira_users: []     # List of users to ignore during sync
```

**`base_url`** (required for Jira commands): Your Jira instance URL

**`strip_email_domain`** (optional, default: `false`): Automatically strip domain from Jira usernames for resource mapping.

When enabled:
- Jira user `john@example.com` → maps to resource `john` (if resource `john` exists)
- Explicit `jira_username` mappings always take priority
- Falls back to full email if no match

**`ignored_jira_users`** (optional, default: `[]`): List of Jira usernames/emails to ignore during sync.

When a Jira issue is assigned to an ignored user, the resources field in the YAML will not be updated (preserving any existing value). This is useful for:
- Automated/bot accounts that shouldn't be treated as real assignees
- System users that manage tickets but don't do the actual work
- Placeholder accounts used during ticket triage

Example:
```yaml
jira:
  ignored_jira_users:
    - "bot@example.com"
    - "jira-automation@example.com"
    - "system@example.com"
```

### Resource Mapping Priority

When syncing Jira assignees to Mouc resources:

1. **Ignored users**: If assignee is in `ignored_jira_users` list → skip update (don't modify resources field)
2. **Unassigned**: If no assignee in Jira → skip update (don't modify resources field)
3. **Explicit `jira_username`**: If resource has `jira_username` defined → use that mapping
4. **Domain stripping** (if enabled): Strip `@domain` and match resource name
5. **Fallback**: Use full Jira email as resource name

Example:
```yaml
resources:
  - name: jdoe
    jira_username: john.doe@example.com  # Priority 3: Explicit mapping

  - name: jane  # Priority 4: Auto-maps jane@example.com if strip_email_domain: true

jira:
  strip_email_domain: true
  ignored_jira_users:
    - "bot@example.com"  # Priority 1: Ignored users
```

**Note:** When resources field is not updated (priorities 1-2), any existing value in the YAML is preserved. This allows you to manually assign resources in Mouc even when Jira has no assignee or an ignored assignee.

### Field Mappings

Configure how Jira fields map to Mouc metadata:

```yaml
field_mappings:
  start_date:
    explicit_field: "Start date"           # Custom field name
    transition_to_status: "In Progress"    # Fallback to transition date
    conflict_resolution: "jira_wins"       # How to handle conflicts

  end_date:
    explicit_field: "Due Date"
    transition_to_status: "Done"

  effort:
    jira_field: "customfield_10001"        # Story points field ID
    unit: "sp"
    conversion: "1sp=1d"                   # Convert story points to days

  status:
    status_map:
      "Done": "done"
      "In Progress": "in_progress"
      "To Do": "todo"

  resources: {}  # Resource mapping configured via jira_username in resources section
```

See [Jira Documentation](jira.md) for detailed field mapping options.

### Defaults

Global defaults for Jira sync:

```yaml
defaults:
  conflict_resolution: "ask"        # "jira_wins" | "mouc_wins" | "ask"
  skip_missing_fields: true         # Skip fields that don't exist in Jira
  timezone: "UTC"                   # Timezone for date conversions
  save_resolution_choices: true     # Save choices to YAML for reuse
```

## Complete Example

```yaml
# Complete mouc_config.yaml example

# ============================================================================
# RESOURCES (Required)
# ============================================================================

resources:
  - name: alice
    jira_username: alice@example.com
    dns_periods:
      - start: 2025-12-15
        end: 2026-01-01

  - name: bob
    jira_username: bob.smith@example.com
    dns_periods:
      - start: 2025-07-01
        end: 2025-07-15

  - name: charlie
    # No jira_username - will use automatic mapping if strip_email_domain: true
    dns_periods: []

groups:
  backend_team:
    - alice
    - bob
  frontend_team:
    - charlie

default_resource: "*"

# ============================================================================
# SCHEDULER (Optional)
# ============================================================================

scheduler:
  auto_constraint_from_timeframe: "both"  # "both", "start", "end", or "none"
  strategy: "weighted"       # "priority_first" | "cr_first" | "weighted"
  cr_weight: 10.0           # Weight for critical ratio
  priority_weight: 1.0      # Weight for priority
  default_priority: 50      # Default priority for tasks without metadata
  default_cr_multiplier: 2.0  # Multiplier for default CR calculation
  default_cr_floor: 10.0    # Minimum default CR

# ============================================================================
# STYLE TAGS (Optional)
# ============================================================================

style_tags:
  - detailed                 # Activate styler functions tagged with 'detailed'
  - color-by-team           # Can also pass --style-tags on CLI

# ============================================================================
# MARKDOWN OUTPUT (Optional)
# ============================================================================

markdown:
  toc_sections: [timeline, entity_types]
  organization:
    primary: "by_type"
    secondary: null
    entity_type_order: [capability, user_story, outcome]
  timeline:
    infer_from_schedule: true
    inferred_granularity: monthly
    sort_unscheduled_by_completion: true

# ============================================================================
# DOCX OUTPUT (Optional)
# ============================================================================

docx:
  table_style: "Table Grid"
  toc_sections: [timeline, entity_types]
  organization:
    primary: "by_type"
    secondary: null
    entity_type_order: [capability, user_story, outcome]
  timeline:
    infer_from_schedule: true
    inferred_granularity: monthly
    sort_unscheduled_by_completion: true

# ============================================================================
# JIRA INTEGRATION (Optional)
# ============================================================================

jira:
  base_url: "https://example.atlassian.net"
  strip_email_domain: false  # Set to true to auto-map john@example.com → john
  ignored_jira_users: []     # Add bot/system accounts to ignore

field_mappings:
  start_date:
    explicit_field: "Start date"
    transition_to_status: "In Progress"
    conflict_resolution: "jira_wins"

  end_date:
    explicit_field: "Due Date"
    transition_to_status: "Done"

  effort:
    jira_field: "customfield_10001"
    unit: "sp"
    conversion: "1sp=1d"

  status:
    status_map:
      "Done": "done"
      "In Progress": "in_progress"
      "To Do": "todo"

  resources: {}

defaults:
  conflict_resolution: "ask"
  skip_missing_fields: true
  timezone: "UTC"
  save_resolution_choices: true
```

## See Also

- [Resources Documentation](resources.md) - Detailed resource scheduling behavior
- [Jira Documentation](jira.md) - Detailed Jira sync features
- [Gantt Charts](gantt.md) - Gantt chart generation with resources