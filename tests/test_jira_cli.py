"""Tests for Jira CLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from mouc.cli import app
from mouc.jira_client import JiraIssueData

runner = CliRunner()


class TestJiraFetchCommand:
    """Test the jira fetch CLI command."""

    @pytest.fixture
    def mock_jira_client(self) -> Mock:
        """Create a mock Jira client."""
        mock_client = Mock()
        mock_client.email = "test@example.com"

        # Mock fetch_issue to return test data
        mock_client.fetch_issue.return_value = JiraIssueData(
            key="TEST-123",
            summary="Test issue summary",
            status="In Progress",
            fields={
                "summary": "Test issue summary",
                "status": {"name": "In Progress"},
                "assignee": {"emailAddress": "assignee@example.com"},
                "customfield_10001": "5",
                "created": "2025-01-01T10:00:00.000+0000",
            },
            status_transitions={
                "To Do": datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                "In Progress": datetime(2025, 1, 5, 14, 30, 0, tzinfo=timezone.utc),
            },
            assignee_email="assignee@example.com",
        )

        # Mock the underlying jira client - atlassian.Jira.issue() returns a dict
        mock_client.client.issue.return_value = {
            "key": "TEST-123",
            "fields": {
                "summary": "Test issue summary",
                "status": {"name": "In Progress"},
            },
            "changelog": {
                "histories": [
                    {
                        "created": "2025-01-05T14:30:00.000+0000",
                        "items": [
                            {
                                "field": "status",
                                "fromString": "To Do",
                                "toString": "In Progress",
                            }
                        ],
                    }
                ]
            },
        }

        # Mock field name map
        mock_client._get_field_name_map.return_value = {
            "Story Points": "customfield_10001",
            "Epic Link": "customfield_10002",
        }

        return mock_client

    @pytest.fixture
    def mock_config_file(self, tmp_path: Path) -> Path:
        """Create a mock jira config file."""
        config_file = tmp_path / "jira_config.yaml"
        config_file.write_text("""
jira:
  base_url: https://example.atlassian.net

field_mappings:
  start_date:
    transition_to_status: "In Progress"
""")
        return config_file

    def test_jira_fetch_verbosity_0_basic_output(
        self, mock_jira_client: Mock, mock_config_file: Path
    ) -> None:
        """Test jira fetch with verbosity 0 (default)."""
        with patch("mouc.jira_cli.JiraClient", return_value=mock_jira_client):
            result = runner.invoke(
                app, ["jira", "fetch", "TEST-123", "--config", str(mock_config_file)]
            )

        assert result.exit_code == 0
        assert "TEST-123" in result.stdout
        assert "Test issue summary" in result.stdout
        assert "In Progress" in result.stdout
        assert "Status Transitions:" in result.stdout
        # Should not show raw JSON at level 0
        assert "RAW JIRA API RESPONSE" not in result.stdout

    def test_jira_fetch_verbosity_1_enhanced_output(
        self, mock_jira_client: Mock, mock_config_file: Path
    ) -> None:
        """Test jira fetch with verbosity 1."""
        with patch("mouc.jira_cli.JiraClient", return_value=mock_jira_client):
            result = runner.invoke(
                app, ["-v", "1", "jira", "fetch", "TEST-123", "--config", str(mock_config_file)]
            )

        assert result.exit_code == 0
        assert "JIRA ISSUE: TEST-123" in result.stdout
        assert "Status Transition History:" in result.stdout
        assert "To Do:" in result.stdout
        assert "In Progress:" in result.stdout
        # Should not show all fields at level 1
        assert "All Fields:" not in result.stdout
        # Should not show raw JSON at level 1
        assert "RAW JIRA API RESPONSE" not in result.stdout

    def test_jira_fetch_verbosity_2_all_fields(
        self, mock_jira_client: Mock, mock_config_file: Path
    ) -> None:
        """Test jira fetch with verbosity 2 shows all fields."""
        with patch("mouc.jira_cli.JiraClient", return_value=mock_jira_client):
            result = runner.invoke(
                app, ["-v", "2", "jira", "fetch", "TEST-123", "--config", str(mock_config_file)]
            )

        assert result.exit_code == 0
        assert "JIRA ISSUE: TEST-123" in result.stdout
        assert "All Fields:" in result.stdout
        assert "customfield_10001:" in result.stdout
        # Should not show raw JSON at level 2
        assert "RAW JIRA API RESPONSE" not in result.stdout

    def test_jira_fetch_verbosity_3_raw_dump(
        self, mock_jira_client: Mock, mock_config_file: Path
    ) -> None:
        """Test jira fetch with verbosity 3 dumps raw API response."""
        with patch("mouc.jira_cli.JiraClient", return_value=mock_jira_client):
            result = runner.invoke(
                app, ["-v", "3", "jira", "fetch", "TEST-123", "--config", str(mock_config_file)]
            )

        assert result.exit_code == 0
        assert "RAW JIRA API RESPONSE for TEST-123" in result.stdout
        assert "FIELD DEFINITIONS (cached)" in result.stdout
        # Should contain JSON
        assert '"key": "TEST-123"' in result.stdout
        assert '"changelog"' in result.stdout
        assert '"customfield_10001"' in result.stdout

    def test_jira_fetch_no_transitions(
        self, mock_jira_client: Mock, mock_config_file: Path
    ) -> None:
        """Test jira fetch when issue has no status transitions."""
        # Modify mock to have no transitions
        mock_jira_client.fetch_issue.return_value = JiraIssueData(
            key="TEST-456",
            summary="Test issue",
            status="To Do",
            fields={"summary": "Test issue"},
            status_transitions={},
            assignee_email=None,
        )

        with patch("mouc.jira_cli.JiraClient", return_value=mock_jira_client):
            result = runner.invoke(
                app,
                ["-v", "1", "jira", "fetch", "TEST-456", "--config", str(mock_config_file)],
            )

        assert result.exit_code == 0
        assert "No status transitions found in changelog" in result.stdout
