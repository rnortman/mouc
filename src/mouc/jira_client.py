"""Jira API client wrapper."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from atlassian import Jira
from dotenv import load_dotenv

from mouc.exceptions import MoucError

# Load environment variables from .env file
load_dotenv()


class JiraError(MoucError):
    """Jira-specific error."""


class JiraAuthError(JiraError):
    """Jira authentication error."""


@dataclass(frozen=True)
class JiraIssueData:
    """Data extracted from a Jira issue."""

    key: str
    summary: str
    status: str
    fields: dict[str, Any]
    status_transitions: dict[str, datetime]  # status_name -> transition_date
    assignee_email: str | None


class JiraClient:
    """Wrapper around Jira API for fetching issue data."""

    def __init__(self, base_url: str, email: str | None = None, api_token: str | None = None):
        """Initialize Jira client.

        Args:
            base_url: Jira instance base URL
            email: User email for authentication
            api_token: API token

        Raises:
            JiraAuthError: If credentials are missing
        """
        self.base_url = base_url.rstrip("/")
        self.email = email or os.getenv("JIRA_EMAIL")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN")
        self._field_name_to_id: dict[str, str] | None = None

        if not self.email or not self.api_token:
            raise JiraAuthError(
                "Jira credentials not found. Set JIRA_EMAIL and JIRA_API_TOKEN environment variables."
            )

        try:
            self.client = Jira(
                url=self.base_url,
                username=self.email,
                password=self.api_token,
                cloud=True,
            )
        except Exception as e:
            raise JiraError(f"Failed to initialize Jira client: {e}") from e

    def validate_connection(self) -> bool:
        """Test connection to Jira.

        Returns:
            True if connection is successful

        Raises:
            JiraError: If connection fails
        """
        try:
            server_info: dict[str, Any] | None = cast(
                dict[str, Any] | None,
                self.client.get_server_info(),  # type: ignore[reportUnknownMemberType]
            )
            return server_info is not None
        except Exception as e:
            raise JiraError(f"Failed to connect to Jira: {e}") from e

    def fetch_issue(self, issue_key: str) -> JiraIssueData:
        """Fetch complete issue data including history.

        Args:
            issue_key: Jira issue key (e.g., "PROJ-123")

        Returns:
            JiraIssueData with extracted information

        Raises:
            JiraError: If issue fetch fails
        """
        try:
            issue_raw = self.client.issue(issue_key, expand="changelog")  # type: ignore[reportUnknownMemberType]
            issue = cast(dict[str, Any], issue_raw)  # type: ignore[reportUnknownVariableType]
        except Exception as e:
            raise JiraError(f"Failed to fetch issue {issue_key}: {e}") from e

        fields = cast(dict[str, Any], issue.get("fields", {}))
        status_obj = cast(dict[str, Any], fields.get("status", {}))
        status = cast(str, status_obj.get("name", "Unknown"))
        summary = cast(str, fields.get("summary", ""))

        assignee = fields.get("assignee")
        assignee_email: str | None = None
        if assignee:
            assignee_dict = cast(dict[str, Any], assignee)
            assignee_email = cast(str | None, assignee_dict.get("emailAddress"))

        status_transitions = self._extract_status_transitions(issue)

        return JiraIssueData(
            key=issue_key,
            summary=summary,
            status=status,
            fields=fields,
            status_transitions=status_transitions,
            assignee_email=assignee_email,
        )

    def _extract_status_transitions(self, issue: dict[str, Any]) -> dict[str, datetime]:
        """Extract status transition timestamps from changelog.

        Args:
            issue: Full issue dict with changelog expanded

        Returns:
            Dict mapping status names to first transition date to that status
        """
        transitions: dict[str, datetime] = {}
        changelog = issue.get("changelog", {})
        histories = changelog.get("histories", [])

        for history in histories:
            created = history.get("created")
            if not created:
                continue

            try:
                timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            for item in history.get("items", []):
                if item.get("field") == "status":
                    to_status = item.get("toString")
                    if to_status and to_status not in transitions:
                        transitions[to_status] = timestamp

        return transitions

    def _get_field_mappings(self) -> dict[str, str]:
        """Get mapping of field display names to field IDs.

        Fetches all fields from Jira and builds a mapping of display names to IDs.
        This is cached after the first call.

        Returns:
            Dictionary mapping field display names to field IDs
        """
        if self._field_name_to_id is not None:
            return self._field_name_to_id

        try:
            # Type ignore: atlassian-python-api lacks complete type stubs
            fields_raw = self.client.get_all_fields()  # type: ignore[reportUnknownMemberType]
            fields = cast(list[dict[str, Any]], fields_raw)  # type: ignore[reportUnknownVariableType]

            # Build mapping of name -> id
            mapping: dict[str, str] = {}
            for field in fields:
                name = cast(str, field.get("name", ""))
                field_id = cast(str, field.get("id", ""))
                if name and field_id:
                    mapping[name] = field_id

            self._field_name_to_id = mapping
            return mapping
        except Exception as e:
            raise JiraError(f"Failed to fetch field mappings: {e}") from e

    def get_custom_field_value(self, issue_data: JiraIssueData, field_name: str) -> Any:
        """Get value of a custom field by display name.

        Args:
            issue_data: Fetched issue data
            field_name: Display name of the custom field (e.g., "Start date", "Story Points")

        Returns:
            Field value or None if not found
        """
        fields = issue_data.fields

        # Try direct lookup first (for standard fields that use their name as the key)
        value = fields.get(field_name)
        if value is not None:
            return value

        # Try common variations
        normalized_name = field_name.lower().replace(" ", "")
        value = fields.get(normalized_name)
        if value is not None:
            return value

        # For custom fields, look up the field ID by name
        field_mappings = self._get_field_mappings()
        field_id = field_mappings.get(field_name)
        if field_id:
            return fields.get(field_id)

        return None

    def get_field_by_key(self, issue_data: JiraIssueData, field_key: str) -> Any:
        """Get field value by exact Jira field key.

        Args:
            issue_data: Fetched issue data
            field_key: Exact Jira field key (e.g., "customfield_10001" or "dueDate")

        Returns:
            Field value or None if not found
        """
        return issue_data.fields.get(field_key)
