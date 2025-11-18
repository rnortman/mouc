"""Tests for the doc CLI command."""

from pathlib import Path

from typer.testing import CliRunner

from mouc.cli import app

runner = CliRunner()


class TestDocCommand:
    """Test the doc CLI command."""

    def test_doc_basic_output(self) -> None:
        """Test basic doc generation."""
        result = runner.invoke(app, ["doc", "examples/feature_map.yaml"])

        assert result.exit_code == 0
        assert "# Feature Map" in result.stdout
        assert "Lock-Free Queue Implementation" in result.stdout

    def test_doc_with_schedule_flag(self, tmp_path: Path) -> None:
        """Test doc generation with --schedule flag populates annotations."""
        # Create a minimal test feature map
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Test Task
    description: A test task
    meta:
      effort: 1w
      resources: [alice]
""")

        result = runner.invoke(app, ["doc", str(test_file), "--schedule"])

        assert result.exit_code == 0
        assert "# Feature Map" in result.stdout
        assert "Test Task" in result.stdout

    def test_doc_with_schedule_and_current_date(self, tmp_path: Path) -> None:
        """Test doc generation with --schedule and --current-date."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Test Task
    description: A test task
    meta:
      effort: 1w
      resources: [alice]
""")

        result = runner.invoke(
            app, ["doc", str(test_file), "--schedule", "--current-date", "2025-03-01"]
        )

        assert result.exit_code == 0
        assert "Test Task" in result.stdout

    def test_doc_schedule_with_invalid_date(self, tmp_path: Path) -> None:
        """Test doc --schedule with invalid date format."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Test Task
    description: A test task
""")

        result = runner.invoke(
            app, ["doc", str(test_file), "--schedule", "--current-date", "03/01/2025"]
        )

        assert result.exit_code == 1
        assert "Invalid date format" in result.output

    def test_doc_output_to_file(self, tmp_path: Path) -> None:
        """Test doc output to file."""
        output_file = tmp_path / "doc.md"
        result = runner.invoke(
            app, ["doc", "examples/feature_map.yaml", "--output", str(output_file)]
        )

        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "# Feature Map" in content
        assert "Lock-Free Queue Implementation" in content

    def test_doc_schedule_with_styling_function(self, tmp_path: Path) -> None:
        """Test that schedule annotations work with metadata styling functions."""
        # Create test feature map
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Test Task
    description: A test task
    meta:
      effort: 5d
      resources: [alice]
""")

        # Create styling module that displays schedule annotations
        style_file = tmp_path / "style.py"
        style_file.write_text("""from mouc.styling import style_metadata

@style_metadata()
def inject_schedule_dates(entity, context, metadata):
    schedule = entity.annotations.get('schedule')
    if not schedule or schedule.was_fixed:
        return metadata

    result = metadata.copy()
    if schedule.estimated_start:
        result['Estimated Start'] = str(schedule.estimated_start)
    if schedule.estimated_end:
        result['Estimated End'] = str(schedule.estimated_end)
    return result
""")

        # Run doc with --schedule and --style-file
        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-01",
                "--style-file",
                str(style_file),
            ],
        )

        assert result.exit_code == 0
        # Should contain estimated dates from scheduler
        assert "Estimated Start" in result.stdout
        assert "Estimated End" in result.stdout
        # Dates should be in January 2025 (based on current-date and 5d effort)
        assert "2025-01" in result.stdout

    def test_timeline_infer_from_schedule_weekly(self, tmp_path: Path) -> None:
        """Test timeline inference from scheduler with weekly granularity."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Task One
    description: First task
    meta:
      effort: 5d
      resources: [alice]
  task-2:
    name: Task Two
    description: Second task
    depends_on: [task-1]
    meta:
      effort: 5d
      resources: [alice]
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_timeline:
    infer_from_schedule: true
    inferred_granularity: weekly
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",  # Monday of week 2
            ],
        )

        assert result.exit_code == 0
        # Tasks should be grouped by week
        assert "2025w" in result.stdout

    def test_timeline_infer_from_schedule_monthly(self, tmp_path: Path) -> None:
        """Test timeline inference from scheduler with monthly granularity."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Task One
    description: First task
    meta:
      effort: 5d
      resources: [alice]
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_timeline:
    infer_from_schedule: true
    inferred_granularity: monthly
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",
            ],
        )

        assert result.exit_code == 0
        # Task should be grouped by month
        assert "2025-01" in result.stdout

    def test_timeline_infer_from_schedule_quarterly(self, tmp_path: Path) -> None:
        """Test timeline inference from scheduler with quarterly granularity."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Task One
    description: First task
    meta:
      effort: 5d
      resources: [alice]
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_timeline:
    infer_from_schedule: true
    inferred_granularity: quarterly
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",
            ],
        )

        assert result.exit_code == 0
        # Task should be grouped by quarter
        assert "2025q1" in result.stdout

    def test_timeline_manual_timeframe_precedence(self, tmp_path: Path) -> None:
        """Test that manual timeframe takes precedence over inferred."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Task One
    description: First task
    meta:
      effort: 5d
      resources: [alice]
      timeframe: "2025q4"
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_timeline:
    infer_from_schedule: true
    inferred_granularity: weekly
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",  # Would infer to week 2
            ],
        )

        assert result.exit_code == 0
        # Should use manual timeframe Q4, not inferred week
        assert "2025q4" in result.stdout
        assert "2025w" not in result.stdout

    def test_timeline_infer_requires_granularity(self, tmp_path: Path) -> None:
        """Test that enabling infer without granularity fails fast."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Task One
    description: First task
    meta:
      effort: 5d
      resources: [alice]
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_timeline:
    infer_from_schedule: true
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",
            ],
        )

        assert result.exit_code != 0
        # Error message is in output (stdout or stderr combined by default runner)
        output = result.stdout + str(result.exception) if result.exception else result.stdout
        assert "inferred_granularity must be specified" in output

    def test_timeline_sort_unscheduled_by_completion(self, tmp_path: Path) -> None:
        """Test sorting unscheduled section by completion date."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-c:
    name: Task C
    description: Third task
    meta:
      effort: 15d
      resources: [alice]
  task-a:
    name: Task A
    description: First task
    meta:
      effort: 5d
      resources: [alice]
  task-b:
    name: Task B
    description: Second task
    meta:
      effort: 10d
      resources: [alice]
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_timeline:
    sort_unscheduled_by_completion: true
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",
            ],
        )

        assert result.exit_code == 0
        # Tasks should appear in completion order (A, B, C) not alphabetically
        output = result.stdout
        pos_a = output.find("Task A")
        pos_b = output.find("Task B")
        pos_c = output.find("Task C")
        assert pos_a < pos_b < pos_c

    def test_timeline_infer_invalid_granularity(self, tmp_path: Path) -> None:
        """Test that invalid granularity fails fast."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Task One
    description: First task
    meta:
      effort: 5d
      resources: [alice]
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_timeline:
    infer_from_schedule: true
    inferred_granularity: daily
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",
            ],
        )

        assert result.exit_code != 0
        # Error message is in output (stdout or stderr combined by default runner)
        output = result.stdout + str(result.exception) if result.exception else result.stdout
        assert "Invalid" in output and "granularity" in output

    def test_body_organization_infer_timeframes(self, tmp_path: Path) -> None:
        """Test body organization uses inferred timeframes."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Task One
    description: First task
    meta:
      effort: 5d
      resources: [alice]
  task-2:
    name: Task Two
    description: Second task
    depends_on: [task-1]
    meta:
      effort: 5d
      resources: [alice]
      timeframe: 2025q1
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  organization:
    primary: by_timeframe
    timeline:
      infer_from_schedule: true
      inferred_granularity: quarterly
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",
            ],
        )

        assert result.exit_code == 0
        # Both tasks should appear under 2025q1 heading in body
        assert "## 2025q1" in result.stdout
        # Manual timeframe (task-2) and inferred timeframe (task-1) both under 2025q1
        assert "### Task One" in result.stdout
        assert "### Task Two" in result.stdout

    def test_body_organization_separate_confirmed_inferred(self, tmp_path: Path) -> None:
        """Test body organization separates confirmed from inferred timeframes."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  task-1:
    name: Task One
    description: Inferred task
    meta:
      effort: 5d
      resources: [alice]
  task-2:
    name: Task Two
    description: Manual task
    depends_on: [task-1]
    meta:
      effort: 5d
      resources: [alice]
      timeframe: 2025q1
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_sections: []
  organization:
    primary: by_timeframe
    separate_confirmed_inferred: true
    timeline:
      infer_from_schedule: true
      inferred_granularity: quarterly
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",
            ],
        )

        assert result.exit_code == 0
        # Should have separate sections for confirmed and inferred
        assert "## 2025q1 (confirmed)" in result.stdout
        assert "## 2025q1 (inferred)" in result.stdout
        # Task Two should be under confirmed, Task One under inferred
        output_lines = result.stdout.split("\n")
        confirmed_idx = next(
            i for i, line in enumerate(output_lines) if "## 2025q1 (confirmed)" in line
        )
        inferred_idx = next(
            i for i, line in enumerate(output_lines) if "## 2025q1 (inferred)" in line
        )
        task_one_idx = next(i for i, line in enumerate(output_lines) if "### Task One" in line)
        task_two_idx = next(i for i, line in enumerate(output_lines) if "### Task Two" in line)
        # Task Two (manual) should come before Task One (inferred) in the output
        assert task_two_idx < task_one_idx
        assert confirmed_idx < task_two_idx < inferred_idx < task_one_idx

    def test_body_organization_with_type_secondary_and_confirmed_inferred(
        self, tmp_path: Path
    ) -> None:
        """Test 3-level nesting: timeframe -> confirmed/inferred -> type."""
        test_file = tmp_path / "test.yaml"
        test_file.write_text("""metadata:
  version: '1.0'

capabilities:
  cap-1:
    name: Capability One
    description: Inferred capability
    meta:
      effort: 5d
      resources: [alice]

user_stories:
  us-1:
    name: User Story One
    description: Manual user story
    requires: [cap-1]
    meta:
      timeframe: 2025q1
""")

        config_file = tmp_path / "mouc_config.yaml"
        config_file.write_text("""resources:
  - name: alice
    capacity: 1.0

markdown:
  toc_sections: []
  organization:
    primary: by_timeframe
    secondary: by_type
    separate_confirmed_inferred: true
    timeline:
      infer_from_schedule: true
      inferred_granularity: quarterly
""")

        result = runner.invoke(
            app,
            [
                "doc",
                str(test_file),
                "--schedule",
                "--current-date",
                "2025-01-06",
            ],
        )

        assert result.exit_code == 0
        # Should have 2-level nesting with flattened confirmed/inferred sections
        assert "## 2025q1 (confirmed)" in result.stdout  # h2 - timeframe + source
        assert "## 2025q1 (inferred)" in result.stdout  # h2 - timeframe + source
        assert "### Capabilities" in result.stdout  # h3 - type under inferred
        assert "### User Stories" in result.stdout  # h3 - type under confirmed
        assert "#### Capability One" in result.stdout  # h4 - entity
        assert "#### User Story One" in result.stdout  # h4 - entity
