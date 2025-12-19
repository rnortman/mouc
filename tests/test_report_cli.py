"""Tests for report CLI commands."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from mouc.cli import app
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.report_cli import _calculate_effort_rows  # pyright: ignore[reportPrivateUsage]
from mouc.scheduler.core import ScheduleAnnotations, SchedulingResult
from mouc.scheduler.lock import ScheduleLock, TaskLock, write_lock_file

runner = CliRunner()


@pytest.fixture
def sample_yaml(tmp_path: Path) -> Path:
    """Create a sample YAML file with entities."""
    yaml_content = {
        "capabilities": {
            "cap-1": {
                "name": "Feature A",
                "description": "First feature",
                "meta": {"effort": "2w"},
            },
            "cap-2": {
                "name": "Feature B",
                "description": "Second feature",
                "meta": {"effort": "4w"},
            },
            "cap-3": {
                "name": "Feature C",
                "description": "Third feature",
                "meta": {"effort": "1w"},
            },
        }
    }
    yaml_path = tmp_path / "roadmap.yaml"
    with yaml_path.open("w") as f:
        yaml.dump(yaml_content, f)
    return yaml_path


@pytest.fixture
def sample_lock_file(tmp_path: Path) -> Path:
    """Create a sample lock file with scheduled dates."""
    # cap-1: Jan 1-14 (2 weeks, fully in Q1)
    # cap-2: Jan 15 - Feb 12 (4 weeks, fully in Q1)
    # cap-3: Dec 28 - Jan 4 (1 week, spans year boundary, half in Q1)
    result = SchedulingResult(
        scheduled_tasks=[],
        annotations={
            "cap-1": ScheduleAnnotations(
                estimated_start=date(2025, 1, 1),
                estimated_end=date(2025, 1, 15),  # 14 days
                computed_deadline=None,
                computed_priority=50,
                deadline_violated=False,
                resource_assignments=[("alice", 1.0)],
                resources_were_computed=False,
                was_fixed=False,
            ),
            "cap-2": ScheduleAnnotations(
                estimated_start=date(2025, 1, 15),
                estimated_end=date(2025, 2, 12),  # 28 days (4 weeks)
                computed_deadline=None,
                computed_priority=50,
                deadline_violated=False,
                resource_assignments=[("bob", 1.0)],
                resources_were_computed=False,
                was_fixed=False,
            ),
            "cap-3": ScheduleAnnotations(
                estimated_start=date(2024, 12, 28),
                estimated_end=date(2025, 1, 4),  # 7 days, spans year boundary
                computed_deadline=None,
                computed_priority=50,
                deadline_violated=False,
                resource_assignments=[("charlie", 1.0)],
                resources_were_computed=False,
                was_fixed=False,
            ),
        },
        warnings=[],
    )

    lock_path = tmp_path / "schedule.lock.yaml"
    write_lock_file(lock_path, result)
    return lock_path


class TestEffortReportCommand:
    """Tests for mouc report effort command."""

    def test_effort_report_with_timeframe(
        self, tmp_path: Path, sample_yaml: Path, sample_lock_file: Path
    ):
        """Test effort report using timeframe string."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(sample_lock_file),
                "--timeframe",
                "2025q1",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert output_csv.exists()

        # Read CSV and verify
        lines = output_csv.read_text().strip().split("\n")
        assert len(lines) == 4  # header + 3 tasks

        # Check header
        assert lines[0] == "task_id,task_name,effort_weeks"

    def test_effort_report_with_dates(
        self, tmp_path: Path, sample_yaml: Path, sample_lock_file: Path
    ):
        """Test effort report using explicit start/end dates."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(sample_lock_file),
                "--start",
                "2025-01-01",
                "--end",
                "2025-03-31",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert output_csv.exists()

    def test_effort_report_proportional_calculation(
        self, tmp_path: Path, sample_yaml: Path, sample_lock_file: Path
    ):
        """Test proportional effort calculation for task spanning boundary."""
        output_csv = tmp_path / "effort.csv"

        # cap-3 spans Dec 28 - Jan 4 (7 days)
        # Q1 starts Jan 1, so 3 days overlap (Jan 1-3)
        # effort = 1w = 7 calendar days, proportion = 3/7
        # effort_in_range = 7 * 3/7 = 3 calendar days
        # effort_weeks = 3 / 7 = 0.43 weeks
        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(sample_lock_file),
                "--timeframe",
                "2025q1",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 0

        # Parse CSV and find cap-3's effort
        lines = output_csv.read_text().strip().split("\n")
        cap3_line = [line for line in lines if "cap-3" in line][0]
        effort_weeks = float(cap3_line.split(",")[2])

        # 3 days overlap / 7 days total = 0.43 weeks
        assert 0.4 <= effort_weeks <= 0.5

    def test_effort_report_task_outside_range(self, tmp_path: Path):
        """Test that tasks outside the range are excluded."""
        # Create YAML with one entity
        yaml_content = {
            "capabilities": {
                "cap-outside": {
                    "name": "Outside Range",
                    "description": "Task outside range",
                    "meta": {"effort": "2w"},
                }
            }
        }
        yaml_path = tmp_path / "roadmap.yaml"
        with yaml_path.open("w") as f:
            yaml.dump(yaml_content, f)

        # Create lock file with task in Q4 2024 (outside Q1 2025)
        result = SchedulingResult(
            scheduled_tasks=[],
            annotations={
                "cap-outside": ScheduleAnnotations(
                    estimated_start=date(2024, 10, 1),
                    estimated_end=date(2024, 10, 15),
                    computed_deadline=None,
                    computed_priority=50,
                    deadline_violated=False,
                    resource_assignments=[("alice", 1.0)],
                    resources_were_computed=False,
                    was_fixed=False,
                ),
            },
            warnings=[],
        )
        lock_path = tmp_path / "schedule.lock.yaml"
        write_lock_file(lock_path, result)

        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(yaml_path),
                str(lock_path),
                "--timeframe",
                "2025q1",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 0

        # CSV should only have header, no data rows
        lines = output_csv.read_text().strip().split("\n")
        assert len(lines) == 1  # header only

    def test_effort_report_missing_lock_file(self, tmp_path: Path, sample_yaml: Path):
        """Test error when lock file doesn't exist."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(tmp_path / "nonexistent.lock.yaml"),
                "--timeframe",
                "2025q1",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 1
        assert "Lock file not found" in result.output

    def test_effort_report_missing_yaml_file(self, tmp_path: Path, sample_lock_file: Path):
        """Test error when YAML file doesn't exist."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(tmp_path / "nonexistent.yaml"),
                str(sample_lock_file),
                "--timeframe",
                "2025q1",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 1
        assert "YAML file not found" in result.output

    def test_effort_report_invalid_timeframe(
        self, tmp_path: Path, sample_yaml: Path, sample_lock_file: Path
    ):
        """Test error for invalid timeframe format."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(sample_lock_file),
                "--timeframe",
                "invalid",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 1
        assert "Invalid timeframe format" in result.output

    def test_effort_report_conflicting_options(
        self, tmp_path: Path, sample_yaml: Path, sample_lock_file: Path
    ):
        """Test error when both --timeframe and --start/--end are specified."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(sample_lock_file),
                "--timeframe",
                "2025q1",
                "--start",
                "2025-01-01",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 1
        assert "Cannot specify both" in result.output

    def test_effort_report_missing_time_range(
        self, tmp_path: Path, sample_yaml: Path, sample_lock_file: Path
    ):
        """Test error when neither --timeframe nor --start/--end is specified."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(sample_lock_file),
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 1
        assert "Must specify either --timeframe" in result.output

    def test_effort_report_partial_date_range(
        self, tmp_path: Path, sample_yaml: Path, sample_lock_file: Path
    ):
        """Test error when only --start is specified without --end."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(sample_lock_file),
                "--start",
                "2025-01-01",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 1
        # The validation catches this as missing both timeframe and complete date range
        assert "Must specify either --timeframe or both --start and --end" in result.output


class TestEffortReportPhaseCombining:
    """Tests for workflow phase combining in effort reports."""

    def test_phases_combined_by_default(self, tmp_path: Path):
        """Test that workflow phases are combined by default."""
        # Create entities with phase_of set (simulating workflow expansion)
        entities = [
            Entity(
                type="capability",
                id="auth",
                name="Authentication",
                description="Auth implementation",
                meta={"effort": "2w"},
                phase_of=None,  # Parent entity
            ),
            Entity(
                type="capability",
                id="auth_design",
                name="Authentication Design",
                description="Auth design phase",
                meta={"effort": "1w"},
                phase_of=("auth", "design"),  # Phase entity
            ),
            Entity(
                type="capability",
                id="standalone",
                name="Standalone Feature",
                description="No workflow",
                meta={"effort": "3w"},
                phase_of=None,  # Standalone (no phases)
            ),
        ]

        feature_map = FeatureMap(
            metadata=FeatureMapMetadata(),
            entities=entities,
        )

        schedule_lock = ScheduleLock(
            version=2,
            locks={
                "auth": TaskLock(
                    start_date=date(2025, 1, 15),
                    end_date=date(2025, 1, 29),
                    resources=[("alice", 1.0)],
                    was_fixed=False,
                    resources_were_computed=False,
                ),
                "auth_design": TaskLock(
                    start_date=date(2025, 1, 1),
                    end_date=date(2025, 1, 8),
                    resources=[("alice", 1.0)],
                    was_fixed=False,
                    resources_were_computed=False,
                ),
                "standalone": TaskLock(
                    start_date=date(2025, 2, 1),
                    end_date=date(2025, 2, 22),
                    resources=[("bob", 1.0)],
                    was_fixed=False,
                    resources_were_computed=False,
                ),
            },
        )

        # Default: combine_phases=True
        rows = _calculate_effort_rows(
            feature_map, schedule_lock, date(2025, 1, 1), date(2025, 3, 31), combine_phases=True
        )

        # Should have 2 rows: auth (combined) + standalone
        assert len(rows) == 2

        # Find auth row - should have combined effort (1w + 2w = 3w)
        auth_row = next(r for r in rows if r[0] == "auth")
        assert auth_row[2] == 3.0

        # Find standalone row - unaffected (3w)
        standalone_row = next(r for r in rows if r[0] == "standalone")
        assert standalone_row[2] == 3.0

    def test_phases_separate_with_flag(self, tmp_path: Path):
        """Test that combine_phases=False shows phases separately."""
        entities = [
            Entity(
                type="capability",
                id="auth",
                name="Authentication",
                description="Auth implementation",
                meta={"effort": "2w"},
                phase_of=None,
            ),
            Entity(
                type="capability",
                id="auth_design",
                name="Authentication Design",
                description="Auth design phase",
                meta={"effort": "1w"},
                phase_of=("auth", "design"),
            ),
            Entity(
                type="capability",
                id="standalone",
                name="Standalone Feature",
                description="No workflow",
                meta={"effort": "3w"},
                phase_of=None,
            ),
        ]

        feature_map = FeatureMap(
            metadata=FeatureMapMetadata(),
            entities=entities,
        )

        schedule_lock = ScheduleLock(
            version=2,
            locks={
                "auth": TaskLock(
                    start_date=date(2025, 1, 15),
                    end_date=date(2025, 1, 29),
                    resources=[("alice", 1.0)],
                    was_fixed=False,
                    resources_were_computed=False,
                ),
                "auth_design": TaskLock(
                    start_date=date(2025, 1, 1),
                    end_date=date(2025, 1, 8),
                    resources=[("alice", 1.0)],
                    was_fixed=False,
                    resources_were_computed=False,
                ),
                "standalone": TaskLock(
                    start_date=date(2025, 2, 1),
                    end_date=date(2025, 2, 22),
                    resources=[("bob", 1.0)],
                    was_fixed=False,
                    resources_were_computed=False,
                ),
            },
        )

        # combine_phases=False
        rows = _calculate_effort_rows(
            feature_map, schedule_lock, date(2025, 1, 1), date(2025, 3, 31), combine_phases=False
        )

        # Should have 3 rows: auth, auth_design, standalone
        assert len(rows) == 3
        row_ids = {r[0] for r in rows}
        assert row_ids == {"auth", "auth_design", "standalone"}

    def test_combined_phases_proportional_effort(self, tmp_path: Path):
        """Test proportional effort calculation with combined phases."""
        entities = [
            Entity(
                type="capability",
                id="auth",
                name="Authentication",
                description="Auth implementation",
                meta={"effort": "2w"},
                phase_of=None,
            ),
            Entity(
                type="capability",
                id="auth_design",
                name="Authentication Design",
                description="Auth design phase",
                meta={"effort": "1w"},
                phase_of=("auth", "design"),
            ),
        ]

        feature_map = FeatureMap(
            metadata=FeatureMapMetadata(),
            entities=entities,
        )

        schedule_lock = ScheduleLock(
            version=2,
            locks={
                "auth": TaskLock(
                    start_date=date(2025, 1, 15),
                    end_date=date(2025, 1, 29),  # 14 days, fully in January
                    resources=[("alice", 1.0)],
                    was_fixed=False,
                    resources_were_computed=False,
                ),
                "auth_design": TaskLock(
                    start_date=date(2025, 1, 1),
                    end_date=date(2025, 1, 8),  # 7 days, fully in January
                    resources=[("alice", 1.0)],
                    was_fixed=False,
                    resources_were_computed=False,
                ),
            },
        )

        # January only
        rows = _calculate_effort_rows(
            feature_map, schedule_lock, date(2025, 1, 1), date(2025, 2, 1), combine_phases=True
        )

        # Should have 1 combined row
        assert len(rows) == 1
        assert rows[0][0] == "auth"
        # Both tasks fully in January: 1w + 2w = 3w
        assert rows[0][2] == 3.0

    def test_cli_no_combine_phases_flag(
        self, tmp_path: Path, sample_yaml: Path, sample_lock_file: Path
    ):
        """Test that --no-combine-phases CLI flag works."""
        output_csv = tmp_path / "effort.csv"

        result = runner.invoke(
            app,
            [
                "report",
                "effort",
                str(sample_yaml),
                str(sample_lock_file),
                "--timeframe",
                "2025q1",
                "--no-combine-phases",
                "-o",
                str(output_csv),
            ],
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert output_csv.exists()
