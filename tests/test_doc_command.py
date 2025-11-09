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
