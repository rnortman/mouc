# Mouc Configuration

Mouc uses a single unified configuration file (`mouc_config.yaml`) that contains both resource definitions and Jira integration settings.

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration File Location](#configuration-file-location)
- [File Structure](#file-structure)
- [Resources Section](#resources-section)
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

The unified config file has two main sections:

```yaml
# REQUIRED: Resource definitions
resources:
  - name: alice
    jira_username: alice@example.com
    dns_periods: []

groups:
  team_a: [alice, bob]

default_resource: "*"

# OPTIONAL: Jira integration settings
jira:
  base_url: "https://example.atlassian.net"
  strip_email_domain: false

field_mappings:
  # ... Jira field mappings

defaults:
  # ... Jira sync defaults
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
```

## See Also

- [Resources Documentation](resources.md) - Detailed resource scheduling behavior
- [Jira Documentation](jira.md) - Detailed Jira sync features
- [Gantt Charts](gantt.md) - Gantt chart generation with resources