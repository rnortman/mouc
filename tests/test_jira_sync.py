"""Tests for Jira sync logic."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest

from mouc.jira_client import JiraIssueData
from mouc.jira_config import (
    FieldMapping,
    FieldMappings,
    JiraConfig,
    JiraConnection,
)
from mouc.jira_sync import FieldExtractor


class TestFieldExtractor:
    """Tests for FieldExtractor."""

    @pytest.fixture
    def config(self) -> JiraConfig:
        """Create test config."""
        return JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(
                    explicit_field="startdate",
                    transition_to_status="In Progress",
                ),
                end_date=FieldMapping(
                    explicit_field="duedate",
                    transition_to_status="Done",
                ),
                effort=FieldMapping(
                    jira_field="customfield_10001",
                    conversion="1sp=1d",
                    unit="sp",
                ),
                status=FieldMapping(
                    status_map={
                        "Done": "done",
                        "In Progress": "in_progress",
                    }
                ),
                resources=FieldMapping(
                    assignee_map={
                        "john@example.com": "jdoe",
                        "jane@example.com": "jsmith",
                    },
                    unassigned_value="*",
                ),
            ),
        )

    @pytest.fixture
    def mock_client(self) -> Mock:
        """Create mock Jira client."""
        client = Mock()

        # Mock get_custom_field_value to return field values directly from the fields dict
        def mock_get_custom_field(issue_data: JiraIssueData, field_name: str) -> Any:
            # For tests, just look up the field name directly
            return issue_data.fields.get(field_name)

        client.get_custom_field_value = mock_get_custom_field
        return client

    @pytest.fixture
    def extractor(self, config: JiraConfig, mock_client: Mock) -> FieldExtractor:
        """Create test extractor."""
        return FieldExtractor(config, mock_client)

    def test_extract_start_date_from_explicit_field(self, extractor: FieldExtractor) -> None:
        """Test extracting start date from explicit field."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"startdate": "2025-01-15"},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 15)

    def test_extract_start_date_from_transition(self, extractor: FieldExtractor) -> None:
        """Test extracting start date from status transition."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={},
            status_transitions={"In Progress": datetime(2025, 1, 10, 9, 0, 0, tzinfo=timezone.utc)},
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 10)

    def test_extract_start_date_explicit_takes_precedence(self, extractor: FieldExtractor) -> None:
        """Test that explicit field takes precedence over transition."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"startdate": "2025-01-15"},
            status_transitions={"In Progress": datetime(2025, 1, 10, 9, 0, 0, tzinfo=timezone.utc)},
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 15)  # Explicit field wins

    def test_extract_effort_with_conversion(self, extractor: FieldExtractor) -> None:
        """Test extracting effort with conversion."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"customfield_10001": 5},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_effort(issue_data)
        assert result == "5d"  # 5 story points = 5 days with 1sp=1d

    def test_extract_status_with_mapping(self, extractor: FieldExtractor) -> None:
        """Test extracting status with mapping."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="Done",
            fields={},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_status(issue_data)
        assert result == "done"

    def test_extract_status_unmapped(self, extractor: FieldExtractor) -> None:
        """Test extracting unmapped status returns None."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="Backlog",
            fields={},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_status(issue_data)
        assert result is None

    def test_extract_resources_with_mapping(self, extractor: FieldExtractor) -> None:
        """Test extracting resources with assignee mapping."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={},
            status_transitions={},
            assignee_email="john@example.com",
        )

        result = extractor.extract_resources(issue_data)
        assert result == ["jdoe"]

    def test_extract_resources_unassigned(self, extractor: FieldExtractor) -> None:
        """Test extracting resources for unassigned issue."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_resources(issue_data)
        assert result == ["*"]

    def test_extract_resources_unmapped_assignee(self, extractor: FieldExtractor) -> None:
        """Test extracting resources for unmapped assignee uses email."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={},
            status_transitions={},
            assignee_email="unknown@example.com",
        )

        result = extractor.extract_resources(issue_data)
        assert result == ["unknown@example.com"]

    def test_convert_effort_complex(self, extractor: FieldExtractor, mock_client: Mock) -> None:
        """Test effort conversion with complex rule."""
        # 2sp=1w means 2 story points = 1 week
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                effort=FieldMapping(
                    jira_field="customfield_10001",
                    conversion="2sp=1w",
                    unit="sp",
                ),
            ),
        )
        extractor = FieldExtractor(config, mock_client)

        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"customfield_10001": 8},  # 8 story points
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_effort(issue_data)
        assert result == "4w"  # 8 sp / 2 = 4 weeks
