"""Tests for CLI commands."""

# pyright: reportUnusedFunction=false

import csv
from collections.abc import Sequence
from pathlib import Path

from typer.testing import CliRunner

from mouc import styling
from mouc.cli import app
from mouc.styling import Entity as EntityProtocol
from mouc.styling import StylingContext

runner = CliRunner()


class TestGanttCommand:
    """Test the gantt CLI command."""

    def test_gantt_basic_output(self, tmp_path: Path) -> None:
        """Test basic gantt chart generation."""
        # Use the example feature map
        result = runner.invoke(app, ["gantt", "examples/feature_map.yaml"])

        assert result.exit_code == 0
        assert "gantt" in result.stdout
        assert "title Project Schedule" in result.stdout
        assert "dateFormat YYYY-MM-DD" in result.stdout
        # Default is no grouping (no sections)
        assert "section" not in result.stdout
        assert "Lock-Free Queue Implementation" in result.stdout

    def test_gantt_with_start_date(self, tmp_path: Path) -> None:
        """Test gantt chart with custom start date and current date."""
        result = runner.invoke(
            app,
            [
                "gantt",
                "examples/feature_map.yaml",
                "--start-date",
                "2025-02-01",
                "--current-date",
                "2025-02-01",
            ],
        )

        assert result.exit_code == 0
        assert "2025-02-01" in result.stdout

    def test_gantt_with_custom_title(self, tmp_path: Path) -> None:
        """Test gantt chart with custom title."""
        result = runner.invoke(
            app, ["gantt", "examples/feature_map.yaml", "--title", "My Custom Schedule"]
        )

        assert result.exit_code == 0
        assert "title My Custom Schedule" in result.stdout

    def test_gantt_output_to_file(self, tmp_path: Path) -> None:
        """Test gantt chart output to markdown file."""
        output_file = tmp_path / "gantt.md"
        result = runner.invoke(
            app, ["gantt", "examples/feature_map.yaml", "--output", str(output_file)]
        )

        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        # Should be wrapped in markdown code fence
        assert content.startswith("```mermaid\n")
        assert content.endswith("```\n")
        assert "gantt" in content
        assert "Lock-Free Queue Implementation" in content

    def test_gantt_output_to_non_markdown_file(self, tmp_path: Path) -> None:
        """Test gantt chart output to non-markdown file (no code fence)."""
        output_file = tmp_path / "gantt.mmd"
        result = runner.invoke(
            app, ["gantt", "examples/feature_map.yaml", "--output", str(output_file)]
        )

        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        # Should NOT be wrapped in code fence for non-.md files
        assert "gantt\n" in content
        assert not content.startswith("```mermaid")
        assert "Lock-Free Queue Implementation" in content

    def test_gantt_invalid_date_format(self, tmp_path: Path) -> None:
        """Test gantt chart with invalid date format."""
        result = runner.invoke(
            app, ["gantt", "examples/feature_map.yaml", "--start-date", "02/01/2025"]
        )

        assert result.exit_code == 1
        assert "Invalid date format" in result.output

    def test_gantt_nonexistent_file(self, tmp_path: Path) -> None:
        """Test gantt chart with nonexistent file."""
        result = runner.invoke(app, ["gantt", "nonexistent.yaml"])

        assert result.exit_code == 1
        assert result.exception is not None
        assert "File not found" in str(result.exception)

    def test_gantt_warnings_displayed(self, tmp_path: Path) -> None:
        """Test that deadline warnings are displayed."""
        result = runner.invoke(app, ["gantt", "examples/feature_map.yaml"])

        # Should have warnings since deadlines are in the past relative to default start date
        # (The example has deadlines in 2025 and we'll start from today)
        assert result.exit_code == 0
        # Warnings go to stderr, check output which combines stdout and stderr
        assert "Warning" in result.output or "after required date" in result.output

    def test_gantt_sort_by_start(self, tmp_path: Path) -> None:
        """Test gantt chart with sort-by parameter."""
        result = runner.invoke(
            app,
            [
                "gantt",
                "examples/feature_map.yaml",
                "--start-date",
                "2025-02-01",
                "--current-date",
                "2025-02-01",
                "--sort-by",
                "start",
            ],
        )

        assert result.exit_code == 0
        # Should have tasks sorted by start date (no specific order to verify, just check it runs)
        assert "Lock-Free Queue Implementation" in result.stdout

    def test_gantt_invalid_sort_by(self, tmp_path: Path) -> None:
        """Test gantt chart with invalid sort-by value."""
        result = runner.invoke(app, ["gantt", "examples/feature_map.yaml", "--sort-by", "invalid"])

        assert result.exit_code == 1
        assert "Invalid sort-by value" in result.output


class TestScheduleCommand:
    """Test the schedule CLI command."""

    def test_schedule_output_csv(self, tmp_path: Path) -> None:
        """Test schedule command with --output-csv."""
        output_file = tmp_path / "schedule.csv"
        result = runner.invoke(
            app,
            [
                "schedule",
                "examples/feature_map.yaml",
                "--current-date",
                "2025-01-01",
                "--output-csv",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        lines = content.strip().split("\n")

        # Check header
        assert lines[0] == "task_id,task_name,priority,deadline,completion_date"

        # Check we have data rows
        assert len(lines) > 1

        # Check a known entity is in the output
        assert "lock_free_queue" in content or "Lock-Free Queue" in content

    def test_schedule_csv_has_correct_columns(self, tmp_path: Path) -> None:
        """Test schedule CSV contains expected column values."""
        output_file = tmp_path / "schedule.csv"
        result = runner.invoke(
            app,
            [
                "schedule",
                "examples/feature_map.yaml",
                "--current-date",
                "2025-01-01",
                "--output-csv",
                str(output_file),
            ],
        )

        assert result.exit_code == 0

        with output_file.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) > 0

        # Each row should have all expected columns
        for row in rows:
            assert "task_id" in row
            assert "task_name" in row
            assert "priority" in row
            assert "deadline" in row
            assert "completion_date" in row

            # task_id should not be empty
            assert row["task_id"]

    def test_schedule_csv_respects_filters(self, tmp_path: Path) -> None:
        """Test that CSV output respects @filter_entity(formats=['csv']) filters."""
        styling.clear_registrations()

        # Register a filter that only keeps entities with id containing "queue"
        @styling.filter_entity(formats=["csv"])
        def filter_queue_only(
            entities: Sequence[EntityProtocol], _context: StylingContext
        ) -> list[EntityProtocol]:
            return [e for e in entities if "queue" in e.id.lower()]

        output_file = tmp_path / "schedule.csv"
        result = runner.invoke(
            app,
            [
                "schedule",
                "examples/feature_map.yaml",
                "--current-date",
                "2025-01-01",
                "--output-csv",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        with output_file.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # All rows should have "queue" in task_id (due to filter)
        assert len(rows) > 0
        for row in rows:
            assert "queue" in row["task_id"].lower()

        styling.clear_registrations()


class TestCompareCommand:
    """Test the compare CLI command."""

    def test_compare_basic(self, tmp_path: Path) -> None:
        """Test basic compare command with baseline and scenario."""
        # Create baseline CSV
        baseline = tmp_path / "baseline.csv"
        baseline.write_text(
            "task_id,task_name,priority,deadline,completion_date\n"
            "task1,Task One,50,,2025-01-10\n"
            "task2,Task Two,80,2025-02-01,2025-01-15\n"
        )

        # Create scenario CSV (task1 delayed, task2 earlier)
        scenario = tmp_path / "faster.csv"
        scenario.write_text(
            "task_id,task_name,priority,deadline,completion_date\n"
            "task1,Task One,50,,2025-01-15\n"
            "task2,Task Two,80,2025-02-01,2025-01-10\n"
        )

        output = tmp_path / "comparison.csv"
        result = runner.invoke(
            app, ["compare", str(baseline), str(scenario), "--output", str(output)]
        )

        assert result.exit_code == 0
        assert output.exists()

        with output.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = {row["task_id"]: row for row in reader}

        # Check header includes scenario columns
        assert "completion_baseline" in rows["task1"]
        assert "completion_faster" in rows["task1"]
        assert "delta_faster" in rows["task1"]

        # task1: 2025-01-10 -> 2025-01-15 = +5 days
        assert rows["task1"]["delta_faster"] == "5"

        # task2: 2025-01-15 -> 2025-01-10 = -5 days
        assert rows["task2"]["delta_faster"] == "-5"

    def test_compare_multiple_scenarios(self, tmp_path: Path) -> None:
        """Test compare with multiple scenario files."""
        baseline = tmp_path / "baseline.csv"
        baseline.write_text(
            "task_id,task_name,priority,deadline,completion_date\ntask1,Task One,50,,2025-01-10\n"
        )

        scenario1 = tmp_path / "scenario_a.csv"
        scenario1.write_text(
            "task_id,task_name,priority,deadline,completion_date\ntask1,Task One,50,,2025-01-12\n"
        )

        scenario2 = tmp_path / "scenario_b.csv"
        scenario2.write_text(
            "task_id,task_name,priority,deadline,completion_date\ntask1,Task One,50,,2025-01-08\n"
        )

        output = tmp_path / "comparison.csv"
        result = runner.invoke(
            app,
            [
                "compare",
                str(baseline),
                str(scenario1),
                str(scenario2),
                "--output",
                str(output),
            ],
        )

        assert result.exit_code == 0

        with output.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]

        # Check both scenario columns present
        assert "completion_scenario_a" in row
        assert "delta_scenario_a" in row
        assert "completion_scenario_b" in row
        assert "delta_scenario_b" in row

        assert row["delta_scenario_a"] == "2"  # +2 days
        assert row["delta_scenario_b"] == "-2"  # -2 days

    def test_compare_missing_task_in_scenario(self, tmp_path: Path) -> None:
        """Test compare handles task in baseline but not in scenario."""
        baseline = tmp_path / "baseline.csv"
        baseline.write_text(
            "task_id,task_name,priority,deadline,completion_date\n"
            "task1,Task One,50,,2025-01-10\n"
            "task2,Task Two,80,,2025-01-15\n"
        )

        scenario = tmp_path / "partial.csv"
        scenario.write_text(
            "task_id,task_name,priority,deadline,completion_date\ntask1,Task One,50,,2025-01-12\n"
        )

        output = tmp_path / "comparison.csv"
        result = runner.invoke(
            app, ["compare", str(baseline), str(scenario), "--output", str(output)]
        )

        assert result.exit_code == 0

        with output.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = {row["task_id"]: row for row in reader}

        # task2 should have blank scenario completion and delta
        assert rows["task2"]["completion_partial"] == ""
        assert rows["task2"]["delta_partial"] == ""

    def test_compare_stdout(self, tmp_path: Path) -> None:
        """Test compare outputs to stdout by default."""
        baseline = tmp_path / "baseline.csv"
        baseline.write_text(
            "task_id,task_name,priority,deadline,completion_date\ntask1,Task One,50,,2025-01-10\n"
        )

        scenario = tmp_path / "scenario.csv"
        scenario.write_text(
            "task_id,task_name,priority,deadline,completion_date\ntask1,Task One,50,,2025-01-12\n"
        )

        result = runner.invoke(app, ["compare", str(baseline), str(scenario)])

        assert result.exit_code == 0
        assert "task_id,task_name,priority,deadline,completion_baseline" in result.stdout
        assert "task1" in result.stdout
