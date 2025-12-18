# Reporting

Mouc can generate reports from scheduled data to answer questions like "what work is planned for Q1?" or "how much effort is allocated to each task in a given timeframe?"

## Effort Report

The `mouc report effort` command generates a CSV report showing tasks and their effort within a specified time range.

### Prerequisites

Reports require a **lock file** from a previous scheduling run. This ensures consistent, reproducible reports without needing to re-run the scheduler:

```bash
# First, generate a schedule and save to lock file
mouc schedule roadmap.yaml --output-lock schedule.lock

# Then generate reports from the lock file
mouc report effort roadmap.yaml schedule.lock --timeframe 2025q1 -o q1_effort.csv
```

### Usage

```bash
# Report by timeframe (quarter, half, month, week, year)
mouc report effort roadmap.yaml schedule.lock --timeframe 2025q1 -o effort.csv
mouc report effort roadmap.yaml schedule.lock --timeframe 2025h1 -o effort.csv
mouc report effort roadmap.yaml schedule.lock --timeframe 2025-03 -o effort.csv
mouc report effort roadmap.yaml schedule.lock --timeframe 2025w12 -o effort.csv

# Report by explicit date range
mouc report effort roadmap.yaml schedule.lock --start 2025-01-01 --end 2025-03-31 -o effort.csv
```

### Workflow Phase Combining

By default, workflow phases are combined into single line items. For example, if an entity has a `design_impl` workflow that creates a design phase and implementation phase, the effort report will show a single row with the combined effort.

To see phases separately, use `--no-combine-phases`:

```bash
mouc report effort roadmap.yaml schedule.lock --timeframe 2025q1 -o effort.csv --no-combine-phases
```

### Output Format

The output is a CSV file with three columns:

```csv
task_id,task_name,effort_weeks
auth-login,User Authentication,3.0
dashboard,User Dashboard,4.0
mobile-app,Mobile App,2.5
```

### Proportional Effort Calculation

For tasks that span the time range boundary, effort is calculated **proportionally** based on how much of the task's scheduled duration falls within the range.

**Example:** A 6-week task scheduled from Jan 30 to Feb 20:
- January report: Shows ~0.3 weeks (only 2 days in January)
- February report: Shows ~5.7 weeks (remaining duration in February)

This gives an accurate picture of "how much work is happening in this period" rather than double-counting tasks that span multiple periods.

### Timeframe Formats

| Format | Example | Description |
|--------|---------|-------------|
| Quarter | `2025q1` | Q1 = Jan-Mar, Q2 = Apr-Jun, etc. |
| Half | `2025h1` | H1 = Jan-Jun, H2 = Jul-Dec |
| Month | `2025-03` | Single calendar month |
| Week | `2025w12` | ISO week number |
| Year | `2025` | Full calendar year |

### Tips

- **Consistent scheduling**: Use lock files to ensure reports are based on the same schedule. Re-running the scheduler might produce different dates.
- **Multiple reports**: Generate reports for different timeframes from the same lock file to compare effort allocation across periods.
- **Filtering**: Use style tags during scheduling to filter which entities are included in the lock file, then report on the filtered set.
