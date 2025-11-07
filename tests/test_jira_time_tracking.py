"""Tests for Jira time tracking field extraction."""

from typing import Any, cast

import pytest

from mouc.jira_client import JiraIssueData
from mouc.jira_config import FieldMapping, FieldMappings, JiraConfig, JiraConnection
from mouc.jira_sync import FieldExtractor


@pytest.fixture
def mock_issue_with_time_tracking() -> JiraIssueData:
    """Create a mock Jira issue with time tracking data."""
    return JiraIssueData(
        key="TEST-123",
        summary="Test issue",
        status="In Progress",
        fields={
            "timetracking": {
                "originalEstimate": "3w",
                "remainingEstimate": "2w 3d",
                "timeSpent": "2d",
                "originalEstimateSeconds": 432000,
                "remainingEstimateSeconds": 324000,
                "timeSpentSeconds": 57600,
            },
            "timeoriginalestimate": 432000,
            "timeestimate": 324000,
            "timespent": 57600,
        },
        status_transitions={},
        assignee_email=None,
    )


class MockJiraClient:
    """Mock JiraClient for testing."""

    def get_custom_field_value(self, issue_data: JiraIssueData, field_name: str) -> Any:
        """Mock implementation that mimics real client behavior."""
        fields = issue_data.fields

        # Special handling for time tracking fields (same as real implementation)
        if field_name in ("Original Estimate", "Remaining Estimate", "Time Spent"):
            timetracking = fields.get("timetracking")
            if timetracking and isinstance(timetracking, dict):
                timetracking_dict = cast(dict[str, Any], timetracking)
                if field_name == "Original Estimate":
                    return timetracking_dict.get("originalEstimate")
                if field_name == "Remaining Estimate":
                    return timetracking_dict.get("remainingEstimate")
                if field_name == "Time Spent":
                    return timetracking_dict.get("timeSpent")

        return fields.get(field_name)

    def get_field_mappings(self) -> dict[str, str]:
        """Mock field mappings."""
        return {}


def test_extract_original_estimate(mock_issue_with_time_tracking: JiraIssueData) -> None:
    """Test extracting Original Estimate field."""
    config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net"),
        field_mappings=FieldMappings(effort=FieldMapping(jira_field="Original Estimate")),
    )

    client = MockJiraClient()
    extractor = FieldExtractor(config, client, verbosity=0)  # type: ignore[arg-type]

    effort = extractor.extract_effort(mock_issue_with_time_tracking)

    assert effort == "3w"


def test_extract_remaining_estimate(mock_issue_with_time_tracking: JiraIssueData) -> None:
    """Test extracting Remaining Estimate field."""
    config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net"),
        field_mappings=FieldMappings(effort=FieldMapping(jira_field="Remaining Estimate")),
    )

    client = MockJiraClient()
    extractor = FieldExtractor(config, client, verbosity=0)  # type: ignore[arg-type]

    effort = extractor.extract_effort(mock_issue_with_time_tracking)

    assert effort == "2w 3d"


def test_extract_time_spent(mock_issue_with_time_tracking: JiraIssueData) -> None:
    """Test extracting Time Spent field."""
    config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net"),
        field_mappings=FieldMappings(effort=FieldMapping(jira_field="Time Spent")),
    )

    client = MockJiraClient()
    extractor = FieldExtractor(config, client, verbosity=0)  # type: ignore[arg-type]

    effort = extractor.extract_effort(mock_issue_with_time_tracking)

    assert effort == "2d"


def test_no_conversion_needed_for_time_tracking() -> None:
    """Test that time tracking fields don't need conversion."""
    config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net"),
        field_mappings=FieldMappings(
            effort=FieldMapping(
                jira_field="Original Estimate",
                # No conversion specified - should return raw value
            )
        ),
    )

    issue_data = JiraIssueData(
        key="TEST-456",
        summary="Test",
        status="To Do",
        fields={"timetracking": {"originalEstimate": "1w 2d"}},
        status_transitions={},
        assignee_email=None,
    )

    client = MockJiraClient()
    extractor = FieldExtractor(config, client, verbosity=0)  # type: ignore[arg-type]

    effort = extractor.extract_effort(issue_data)

    # Should return the human-readable format directly
    assert effort == "1w 2d"


def test_time_tracking_missing() -> None:
    """Test handling when time tracking data is missing."""
    config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net"),
        field_mappings=FieldMappings(effort=FieldMapping(jira_field="Original Estimate")),
    )

    issue_data = JiraIssueData(
        key="TEST-789",
        summary="Test",
        status="To Do",
        fields={},  # No timetracking field
        status_transitions={},
        assignee_email=None,
    )

    client = MockJiraClient()
    extractor = FieldExtractor(config, client, verbosity=0)  # type: ignore[arg-type]

    effort = extractor.extract_effort(issue_data)

    assert effort is None


def test_time_tracking_empty() -> None:
    """Test handling when time tracking exists but has no estimate."""
    config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net"),
        field_mappings=FieldMappings(effort=FieldMapping(jira_field="Original Estimate")),
    )

    issue_data = JiraIssueData(
        key="TEST-789",
        summary="Test",
        status="To Do",
        fields={
            "timetracking": {
                # originalEstimate not set
            }
        },
        status_transitions={},
        assignee_email=None,
    )

    client = MockJiraClient()
    extractor = FieldExtractor(config, client, verbosity=0)  # type: ignore[arg-type]

    effort = extractor.extract_effort(issue_data)

    assert effort is None
