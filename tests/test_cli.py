"""Tests for CLI commands."""

from pathlib import Path

from typer.testing import CliRunner

from mouc.cli import app

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
        assert "section Capability" in result.stdout
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
        assert "Error" in result.output

    def test_gantt_warnings_displayed(self, tmp_path: Path) -> None:
        """Test that deadline warnings are displayed."""
        result = runner.invoke(app, ["gantt", "examples/feature_map.yaml"])

        # Should have warnings since deadlines are in the past relative to default start date
        # (The example has deadlines in 2025 and we'll start from today)
        assert result.exit_code == 0
        # Warnings go to stderr, check output which combines stdout and stderr
        assert "Warning" in result.output or "after required date" in result.output

    def test_gantt_group_by_resource(self, tmp_path: Path) -> None:
        """Test gantt chart with resource-based grouping."""
        result = runner.invoke(
            app,
            [
                "gantt",
                "examples/feature_map.yaml",
                "--start-date",
                "2025-02-01",
                "--current-date",
                "2025-02-01",
                "--group-by",
                "resource",
            ],
        )

        assert result.exit_code == 0
        # Should have resource sections instead of type sections
        assert "section alice" in result.stdout or "section" in result.stdout
        # Should NOT have type sections
        assert "section Capability" not in result.stdout
        assert "section User Story" not in result.stdout

    def test_gantt_group_by_type(self, tmp_path: Path) -> None:
        """Test gantt chart with type-based grouping (explicit)."""
        result = runner.invoke(
            app,
            [
                "gantt",
                "examples/feature_map.yaml",
                "--start-date",
                "2025-02-01",
                "--current-date",
                "2025-02-01",
                "--group-by",
                "type",
            ],
        )

        assert result.exit_code == 0
        # Should have type sections
        assert "section Capability" in result.stdout or "section User Story" in result.stdout

    def test_gantt_invalid_group_by(self, tmp_path: Path) -> None:
        """Test gantt chart with invalid group-by value."""
        result = runner.invoke(app, ["gantt", "examples/feature_map.yaml", "--group-by", "invalid"])

        assert result.exit_code == 1
        assert "Invalid group-by value" in result.output
