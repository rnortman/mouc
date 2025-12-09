# Jira Integration

Mouc supports read-only synchronization with Jira to automatically populate entity metadata from Jira issues. This allows you to maintain a single source of truth in Jira while using Mouc for dependency tracking and scheduling.

## Overview

The Jira integration can:

- Fetch issue metadata (status, dates, effort, assignee) from Jira
- Automatically populate Mouc entities with Jira data
- Detect and resolve conflicts between Mouc and Jira values
- Support custom Jira field names and workflows
- Map Jira assignees to Mouc resources
- Convert Jira story points to time estimates

## Quick Start

### 1. Set up credentials

You have three options for providing Jira credentials (in order of precedence):

#### Option A: Environment Variables

Create a `.env` file in your project root, or set these env vars:

```bash
JIRA_EMAIL=your.email@company.com
JIRA_API_TOKEN=your_api_token_here
```

#### Option B: .netrc File

Add credentials to `~/.netrc` (Unix/Linux/macOS) or `~/_netrc` (Windows):

```
machine yourcompany.atlassian.net
login your.email@company.com
password your_api_token_here
```

**Note:** Ensure the file has restrictive permissions:
```bash
chmod 600 ~/.netrc
```

#### Option C: Pass Credentials Explicitly

You can pass credentials directly to `JiraClient` in code (not available via CLI).

---

Get your API token from: https://id.atlassian.com/manage/api-tokens

**Credential Priority:**
1. Explicitly passed credentials (programmatic use only)
2. Environment variables (`JIRA_EMAIL` and `JIRA_API_TOKEN`)
3. `.netrc` file (fallback)

### 2. Create configuration

Copy the example config and customize for your Jira instance:

```bash
cp mouc_config.example.yaml mouc_config.yaml
```

Edit `mouc_config.yaml` to add your Jira settings (see [Configuration](config.md) for full reference).

### 3. Add Jira links to entities

In your `feature_map.yaml`:

```yaml
entities:
  auth_service:
    type: capability
    name: Authentication Service
    description: OAuth2 authentication
    links:
      - jira:AUTH-123
    meta:
      # These will be synced from Jira
```

### 4. Validate connection

```bash
mouc jira validate
# Auto-detects mouc_config.yaml in current directory
```

### 5. Sync with Jira

```bash
# Dry run to preview changes
mouc jira sync feature_map.yaml --dry-run

# Apply changes
mouc jira sync feature_map.yaml --apply
```

## Commands

### `mouc jira validate`

Test Jira connection and configuration.

```bash
mouc jira validate [--config PATH]
```

**Options:**
- `--config PATH` - Path to mouc_config.yaml (default: `mouc_config.yaml`)

**Example output:**
```
✓ Config loaded: https://yourcompany.atlassian.net
✓ Connected to Jira successfully
✓ Authenticated as: your.email@company.com
```

### `mouc jira fetch`

Fetch and display data for a single Jira ticket.

```bash
mouc jira fetch TICKET-ID [--config PATH]
```

**Options:**
- `--config PATH` - Path to mouc_config.yaml (default: `mouc_config.yaml`)

**Example:**
```bash
$ mouc jira fetch AUTH-123 --config mouc_config.yaml

============================================================
Key: AUTH-123
Summary: Implement OAuth2 authentication
Status: In Progress
Assignee: john.doe@company.com

Status Transitions:
  In Progress: 2025-01-10 09:30:00 UTC
============================================================
```

### `mouc jira list`

List all entities with Jira links.

```bash
mouc jira list [FEATURE_MAP]
```

**Example:**
```bash
$ mouc jira list feature_map.yaml

Found 3 entities with Jira links:

auth_service (capability):
  Name: Authentication Service
  Jira: AUTH-123

user_dashboard (user_story):
  Name: User Dashboard
  Jira: DASH-456
```

### `mouc jira sync`

Sync Mouc entities with Jira issues.

```bash
mouc jira sync [FEATURE_MAP] [OPTIONS]
```

**Options:**
- `--config PATH` - Path to mouc_config.yaml (default: `mouc_config.yaml`)
- `--dry-run` - Show what would change without modifying files
- `--apply` - Apply changes to feature_map.yaml (required to write changes)
- `--report FILE` - Generate CSV report of conflicts
- `--answers FILE` - Load conflict answers from YAML or CSV file (auto-detects format by extension)
- `--interactive` - Prompt for conflicts interactively (terminal only)

**Workflows:**

#### Dry Run (Preview Changes)
```bash
mouc jira sync feature_map.yaml --config mouc_config.yaml --dry-run
```

Shows what would change without modifying any files.

#### Structured Q&A (Default - Recommended)

When conflicts are detected and no resolution method is specified, Mouc automatically generates questions files in both YAML and CSV formats:

```bash
# Step 1: Run sync - automatically generates jira_conflicts.yaml and jira_conflicts.csv
mouc jira sync feature_map.yaml --config mouc_config.yaml

# Output:
# Found 3 conflicts that require resolution.
# Questions files generated:
#   YAML: jira_conflicts.yaml
#   CSV:  jira_conflicts.csv
# Fill in the 'choice' column (jira/mouc/skip), then re-run with --answers <file> --apply
# (Accepts either YAML or CSV format)

# Step 2: Edit either file and fill in 'choice' field for each conflict
# - Use jira_conflicts.yaml for version control-friendly editing
# - Use jira_conflicts.csv for spreadsheet tools (Excel, Google Sheets)
# choice can be: jira, mouc, or skip

# Step 3: Apply with answers (accepts either format)
mouc jira sync feature_map.yaml --config mouc_config.yaml --answers jira_conflicts.yaml --apply
# OR
mouc jira sync feature_map.yaml --config mouc_config.yaml --answers jira_conflicts.csv --apply
```

This is the **default behavior** because it works well for both humans and automation (coding agents, scripts, etc.). Both formats can be edited manually or programmatically. The CSV format is particularly useful for TPMs and stakeholders who prefer spreadsheet tools.

#### CSV Report (For Delegation)
```bash
mouc jira sync feature_map.yaml --config mouc_config.yaml --report conflicts.csv
```

Generates a CSV file with all conflicts for offline review. Useful for:
- Delegating conflict resolution to others (PM, team lead)
- Reviewing conflicts in Excel/Google Sheets
- Generating reports for stakeholders

**Example YAML questions file (`jira_conflicts.yaml`):**
```yaml
conflicts:
- conflict_id: 1
  entity_id: auth_service
  field: resources
  mouc_value: "['alice']"
  jira_value: "['bob']"
  ticket_id: AUTH-123
  choice: 'jira'  # Fill this in: jira, mouc, or skip
instructions: Fill in 'choice' field for each conflict with: jira, mouc, or skip
```

**Example CSV questions file (`jira_conflicts.csv`):**
```csv
conflict_id,entity_id,field,mouc_value,jira_value,ticket_id,choice
1,auth_service,resources,"['alice']","['bob']",AUTH-123,jira
2,api_gateway,start_date,2025-01-15,2025-01-20,API-456,mouc
3,database,effort,5d,3d,DB-789,skip
```

#### Direct Apply (No Conflicts)
```bash
mouc jira sync feature_map.yaml --config mouc_config.yaml --apply
```

Applies all changes directly. Fails if conflicts are found.

## Configuration

The `mouc_config.yaml` file contains both resource definitions and Jira settings. See [Configuration Documentation](config.md) for the complete reference.

This section covers Jira-specific configuration details.

### Basic Structure

```yaml
# Connection settings
jira:
  base_url: https://yourcompany.atlassian.net

# Field mappings
field_mappings:
  start_date:
    explicit_field: "Start date"
    transition_to_status: "In Progress"
    conflict_resolution: "ask"

  end_date:
    explicit_field: "Due Date"
    transition_to_status: "Done"
    conflict_resolution: "jira_wins"

  effort:
    jira_field: "Story Points"
    unit: "story_points"
    conversion: "1sp=1d"
    conflict_resolution: "mouc_wins"

  status:
    status_map:
      "Done": "done"
      "Closed": "done"
    conflict_resolution: "jira_wins"

  resources:
    conflict_resolution: "ask"

# Global defaults
defaults:
  conflict_resolution: "ask"
  skip_missing_fields: true
  timezone: "UTC"
  save_resolution_choices: true
```

### Connection Settings

#### `jira.base_url` (required)

Your Jira instance URL (without trailing slash).

**Example:**
```yaml
jira:
  base_url: https://yourcompany.atlassian.net
```

**Authentication:**

Credentials are read from multiple sources (not stored in config):

**Environment Variables:**
- `JIRA_EMAIL` - Your Jira account email
- `JIRA_API_TOKEN` - API token from https://id.atlassian.com/manage/api-tokens

**Or .netrc file:**
- Add entry for your Jira hostname with login and password (API token)
- See [Quick Start](#1-set-up-credentials) for details

#### `jira.ignored_jira_users` (optional)

List of Jira usernames/emails to ignore during sync. When a Jira issue is assigned to an ignored user, the resources field in YAML will not be updated.

**Default:** `[]` (empty list)

**Use cases:**
- Automated/bot accounts (e.g., `"jira-automation@company.com"`)
- System users that manage tickets but don't do work
- Placeholder accounts used during triage

**Example:**
```yaml
jira:
  base_url: https://yourcompany.atlassian.net
  ignored_jira_users:
    - "bot@company.com"
    - "jira-automation@company.com"
    - "system@company.com"
```

**Behavior:** When an issue is assigned to an ignored user, it's treated the same as an unassigned issue - the resources field in YAML is left unchanged, preserving any manually assigned resources.

### Field Mappings

Field mappings define how to extract data from Jira and resolve conflicts.

#### `start_date`

Extract task start date from Jira.

**Options:**
- `explicit_field` - Jira custom field name (e.g., "Start date")
- `transition_to_status` - Derive from status transition (e.g., "In Progress")
- `conflict_resolution` - How to resolve conflicts (see [Conflict Resolution](#conflict-resolution))

**Precedence:** Explicit field takes precedence over status transition.

**Example:**
```yaml
start_date:
  explicit_field: "Start date"      # Check this field first
  transition_to_status: "In Progress"  # Fallback to transition date
  conflict_resolution: "ask"
```

#### `end_date`

Extract task end date from Jira.

**Options:** Same as `start_date`

**Example:**
```yaml
end_date:
  explicit_field: "Due Date"
  transition_to_status: "Done"
  conflict_resolution: "jira_wins"
```

#### `effort`

Extract effort estimate from Jira.

**Options:**
- `jira_field` - Jira field name (e.g., "Story Points", "Original Estimate")
- `unit` - Unit of the field value
- `conversion` - Conversion rule from Jira units to Mouc time format
- `conflict_resolution` - How to resolve conflicts

**Conversion format:** `Xsp=Yt` where:
- `X` = number of story points
- `Y` = number of time units
- `t` = time unit (`d`=days, `w`=weeks, `m`=months)

**Time Tracking Fields:**

Jira's built-in time tracking fields (`"Original Estimate"`, `"Remaining Estimate"`, `"Time Spent"`) return human-readable strings like `"3w"`, `"5d"`, `"2h"`. These values are automatically compatible with mouc's effort format, so **no conversion is needed**. Simply use:

```yaml
effort:
  jira_field: "Original Estimate"
```

**Examples:**
```yaml
# 1 story point = 1 day
effort:
  jira_field: "Story Points"
  conversion: "1sp=1d"

# 2 story points = 1 week
effort:
  jira_field: "Story Points"
  conversion: "2sp=1w"

# Use Jira's built-in time tracking (Original Estimate)
# This returns values like "3w", "5d", etc. - no conversion needed
effort:
  jira_field: "Original Estimate"

# Use Remaining Estimate instead
effort:
  jira_field: "Remaining Estimate"

# No conversion (use raw value)
effort:
  jira_field: "Original Estimate"
  unit: "days"
```

#### `status`

Map Jira statuses to Mouc status values.

**Options:**
- `status_map` - Dictionary mapping Jira status → Mouc status
- `conflict_resolution` - How to resolve conflicts

**Currently supported Mouc statuses:**
- `"done"` - Task is complete

**Example:**
```yaml
status:
  status_map:
    "Done": "done"
    "Closed": "done"
    "Resolved": "done"
  conflict_resolution: "jira_wins"
```

#### `resources`

Map Jira assignees to Mouc resources.

**Options:**
- `conflict_resolution` - How to resolve conflicts

**Behavior:**
- Resource mapping is configured through the `resources` section using `jira_username` fields
- Unassigned Jira issues (no assignee) will not update the resources field in YAML
- Ignored users (configured in `jira.ignored_jira_users`) will not update the resources field
- When resources field is not updated, any existing value in YAML is preserved

**Example:**
```yaml
# In the resources section
resources:
  - name: jdoe
    jira_username: john.doe@company.com
  - name: jsmith
    jira_username: jane.smith@company.com

# In jira section
jira:
  ignored_jira_users:
    - "bot@company.com"
    - "system@company.com"

# In field_mappings
field_mappings:
  resources:
    conflict_resolution: "ask"
```

### Conflict Resolution

When Mouc has an existing value that differs from Jira, a conflict occurs. The `conflict_resolution` setting determines how to handle it.

**Options:**

- `"jira_wins"` - Automatically use Jira value, overwrite Mouc
- `"mouc_wins"` - Keep existing Mouc value, ignore Jira
- `"ask"` - Prompt for resolution (via interactive mode, answers file, or report)

**Per-field vs. global:**

Each field mapping can specify its own `conflict_resolution`. If not specified, the `defaults.conflict_resolution` is used.

**Example:**
```yaml
field_mappings:
  start_date:
    conflict_resolution: "jira_wins"  # Always trust Jira for dates
  effort:
    conflict_resolution: "mouc_wins"  # Keep manual estimates
  resources:
    conflict_resolution: "ask"        # Require human decision

defaults:
  conflict_resolution: "ask"  # Default for fields without specific setting
```

### Global Defaults

#### `defaults.conflict_resolution`

Default conflict resolution strategy for fields that don't specify one.

**Options:** `"jira_wins"`, `"mouc_wins"`, `"ask"`

**Default:** `"ask"`

#### `defaults.skip_missing_fields`

Whether to skip fields that don't exist in Jira rather than erroring.

**Options:** `true`, `false`

**Default:** `true`

**Example:**
```yaml
defaults:
  skip_missing_fields: true  # Don't error if "Story Points" field doesn't exist
```

#### `defaults.timezone`

Timezone for date conversions.

**Default:** `"UTC"`

**Example:**
```yaml
defaults:
  timezone: "America/New_York"
```

#### `defaults.save_resolution_choices`

Whether to save conflict resolution choices to the YAML file for automatic reuse in future syncs.

**Options:** `true`, `false`

**Default:** `true`

When enabled, after you resolve a conflict (e.g., choosing "jira" for a start_date conflict), that choice is stored in the entity's `meta.jira_sync.resolution_choices` field. On subsequent syncs, the same choice is applied automatically without prompting.

Set to `false` to disable this behavior and always prompt for conflicts.

**Example:**
```yaml
defaults:
  save_resolution_choices: false  # Don't remember conflict resolutions
```

## Jira Link Format

In your `feature_map.yaml`, add Jira links to entity `links` lists:

### Supported Formats

```yaml
links:
  - jira:PROJ-123                          # Simple ticket ID
  - jira:[PROJ-456](https://...)           # With URL
  - https://company.atlassian.net/browse/PROJ-789  # Direct URL (auto-detected)
```

### Multiple Tickets

An entity can have multiple Jira tickets:

```yaml
links:
  - jira:BACKEND-100
  - jira:FRONTEND-200
  - design:[Design Doc](https://...)
```

**Note:** Currently, only the first Jira link is synced. Support for multiple tickets is planned.

## Synced Fields

The following Mouc `meta` fields can be synced from Jira:

| Mouc Field | Jira Source | Notes |
|------------|-------------|-------|
| `start_date` | Custom field or status transition | Format: `YYYY-MM-DD` |
| `end_date` | Custom field or status transition | Format: `YYYY-MM-DD` |
| `effort` | Story Points, Original Estimate, etc. | Converted to Mouc format (e.g., `"2w"`) |
| `status` | Issue status | Mapped via `status_map` |
| `resources` | Assignee | Mapped via `assignee_map` |

**Unsynced fields:** These Mouc fields are never modified by sync:
- `timeframe`, `start_after`, `end_before` - Mouc-specific constraints
- Entity structure (type, name, description, requires, enables, tags)

## Workflow Examples

### Example 1: Initial Sync

You have Jira tickets with dates and want to import them to Mouc.

```bash
# 1. Add jira links to feature_map.yaml
# entities:
#   auth_service:
#     links:
#       - jira:AUTH-123

# 2. Preview what will be synced
mouc jira sync feature_map.yaml --dry-run

# 3. Apply if everything looks good
mouc jira sync feature_map.yaml --apply
```

### Example 2: Resolve Conflicts with Team Review

You want your team to review conflicts before applying.

```bash
# 1. Generate questions files
mouc jira sync feature_map.yaml
# Creates jira_conflicts.yaml and jira_conflicts.csv

# 2. Share file with team lead for review
# - Send jira_conflicts.yaml for version control workflow
# - OR send jira_conflicts.csv for spreadsheet review
# They edit the file and fill in 'choice' fields

# 3. Apply approved changes (accepts either format)
mouc jira sync feature_map.yaml --answers jira_conflicts.yaml --apply
# OR
mouc jira sync feature_map.yaml --answers jira_conflicts.csv --apply
```

### Example 3: CSV Report for PM

Your PM wants to see all discrepancies in a spreadsheet.

```bash
# Generate CSV report
mouc jira sync feature_map.yaml --report discrepancies.csv

# PM reviews in Excel and tells you which to use
# You manually update feature_map.yaml or jira_conflicts.yaml
```

### Example 4: Automated Sync (CI/CD)

You trust Jira completely and want automated sync.

```yaml
# mouc_config.yaml - Set all fields to jira_wins
field_mappings:
  start_date:
    conflict_resolution: "jira_wins"
  end_date:
    conflict_resolution: "jira_wins"
  status:
    conflict_resolution: "jira_wins"
  resources:
    conflict_resolution: "jira_wins"
```

```bash
# In CI pipeline
mouc jira sync feature_map.yaml --apply
git commit -am "Auto-sync from Jira"
```

## Troubleshooting

### Authentication Errors

**Error:** `Authentication error: Jira credentials not found`

**Solution:** Ensure credentials are available via one of these methods:

**Option 1: Environment variables**
```bash
# Check environment variables
echo $JIRA_EMAIL
echo $JIRA_API_TOKEN

# Or create .env file
cat > .env <<EOF
JIRA_EMAIL=your.email@company.com
JIRA_API_TOKEN=your_token_here
EOF
```

**Option 2: .netrc file**
```bash
# Create ~/.netrc (or ~/_netrc on Windows)
cat > ~/.netrc <<EOF
machine yourcompany.atlassian.net
login your.email@company.com
password your_token_here
EOF

# Set restrictive permissions
chmod 600 ~/.netrc
```

**Tip:** Environment variables take precedence over .netrc, so if both are set, the environment variables will be used.

### Connection Errors

**Error:** `Failed to connect to Jira: ...`

**Solution:** Check that `base_url` in `mouc_config.yaml` is correct and you have network access to Jira.

```bash
# Test with curl
curl -u your.email@company.com:your_token https://yourcompany.atlassian.net/rest/api/3/myself
```

### Field Not Found

**Warning:** `Field 'Story Points' not found in issue`

**Solution:** Either:
1. Add the field to your Jira issues
2. Update `mouc_config.yaml` to use the correct field name
3. Set `defaults.skip_missing_fields: true` to ignore missing fields

### Status Not Mapped

Jira status doesn't update Mouc status.

**Solution:** Add the status to `status_map` in `mouc_config.yaml`:

```yaml
status:
  status_map:
    "Done": "done"
    "Complete": "done"     # Add your custom statuses
    "Finished": "done"
```

### Assignee Not Mapped

Jira assignee email appears in Mouc instead of resource name.

**Solution:** Add the mapping to your resources section using `jira_username`:

```yaml
resources:
  - name: nperson
    jira_username: "new.person@company.com"
```

Alternatively, if `strip_email_domain: true` is set in your Jira config, ensure the resource name matches the part before the `@`:

```yaml
resources:
  - name: new.person  # Will auto-map new.person@company.com

jira:
  strip_email_domain: true
```

## Best Practices

### 1. Start with Dry Runs

Always use `--dry-run` first to preview changes before applying.

```bash
mouc jira sync feature_map.yaml --dry-run
```

### 2. Use Structured Q&A for Complex Projects

For projects with many conflicts, use the questions file workflow:

```bash
mouc jira sync feature_map.yaml  # Generate questions (both YAML and CSV)
# Edit jira_conflicts.yaml (for version control) or jira_conflicts.csv (for spreadsheets)
mouc jira sync feature_map.yaml --answers jira_conflicts.yaml --apply
# OR
mouc jira sync feature_map.yaml --answers jira_conflicts.csv --apply
```

### 3. Set Appropriate Conflict Resolution

Choose `conflict_resolution` based on your source of truth:

- **Jira is source of truth** → Use `"jira_wins"` for dates and status
- **Mouc is source of truth** → Use `"mouc_wins"` for effort estimates
- **Need review** → Use `"ask"` for resources and critical fields

### 4. Version Control Your Configs

Commit `mouc_config.yaml` to git so your team shares the same mappings.

```bash
git add mouc_config.yaml
git commit -m "Add Jira sync configuration"
```

### 5. Keep Resource Mappings Updated

When new team members join, add them to the resources section:

```yaml
resources:
  - name: nhire
    jira_username: "new.hire@company.com"
```

Or enable `strip_email_domain` if resource names match email prefixes:

```yaml
resources:
  - name: nhire  # Auto-maps to nhire@company.com

jira:
  strip_email_domain: true
```

### 6. Use Ignored Users for Automation Accounts

Configure ignored users to prevent automation accounts from affecting resource assignment:

```yaml
jira:
  ignored_jira_users:
    - "jira-automation@company.com"
    - "bot@company.com"
    - "system@company.com"
```

This allows you to manually assign resources in Mouc even when automated systems manage the Jira tickets.

### 7. Regular Syncs

Set up a regular sync cadence (e.g., weekly) to keep Mouc updated:

```bash
# Weekly sync
mouc jira sync feature_map.yaml --answers weekly_answers.yaml --apply
```

## Limitations

### Current Limitations

1. **Read-only sync** - Mouc cannot update Jira issues
2. **First Jira link only** - Multiple Jira links per entity not yet supported
3. **Manual conflict resolution** - No automatic merge strategies
4. **Limited field support** - Only start_date, end_date, effort, status, resources

### Future Enhancements

Planned features:

- Bidirectional sync (write back to Jira)
- Multiple Jira tickets per entity
- Custom field mappings via expressions
- Automatic conflict resolution strategies
- Support for Jira sprints and epics
- Bulk operations across multiple feature maps

## See Also

- [Gantt Chart Documentation](gantt.md) - Using synced dates for scheduling
- [Resource Management](resources.md) - Using synced assignees for resource planning
- [Styling](styling.md) - Customizing graph and documentation output
