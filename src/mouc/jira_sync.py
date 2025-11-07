"""Jira sync orchestration and field extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import typer

from mouc.exceptions import MoucError
from mouc.jira_client import JiraClient, JiraError, JiraIssueData
from mouc.jira_config import ConflictResolution, JiraConfig
from mouc.models import Entity, FeatureMap, Link


class JiraSyncError(MoucError):
    """Jira sync error."""


@dataclass(frozen=True)
class FieldConflict:
    """Represents a conflict between Mouc and Jira data."""

    entity_id: str
    field: str
    mouc_value: Any
    jira_value: Any
    ticket_id: str
    resolution: ConflictResolution


@dataclass(frozen=True)
class SyncResult:
    """Result of syncing a single entity with Jira."""

    entity_id: str
    ticket_id: str
    updated_fields: dict[str, Any]  # Fields that will be updated
    conflicts: list[FieldConflict]  # Conflicts requiring user input
    errors: list[str]  # Non-fatal errors during sync


class FieldExtractor:
    """Extracts field values from Jira issue data based on configuration."""

    def __init__(
        self,
        config: JiraConfig,
        client: JiraClient,
        resource_config: Any = None,
        verbosity: int = 0,
    ):
        """Initialize field extractor.

        Args:
            config: Jira configuration
            client: Jira client for resolving field names
            resource_config: Optional ResourceConfig for resource mapping
            verbosity: Verbosity level for debug output
        """
        self.config = config
        self.client = client
        self.resource_config = resource_config
        self.verbosity = verbosity

    def extract_start_date(self, issue_data: JiraIssueData) -> date | None:
        """Extract start_date from issue data.

        Args:
            issue_data: Fetched Jira issue data

        Returns:
            Extracted start date or None
        """
        mapping = self.config.field_mappings.start_date
        if not mapping:
            if self.verbosity >= 3:
                typer.echo("      [DEBUG] start_date: no mapping configured")
            return None

        if mapping.explicit_field:
            value = self._get_date_field(issue_data, mapping.explicit_field)
            if value:
                if self.verbosity >= 3:
                    typer.echo(
                        f"      [DEBUG] start_date: from field '{mapping.explicit_field}' = {value}"
                    )
                return value

        if mapping.transition_to_status:
            transition_date = issue_data.status_transitions.get(mapping.transition_to_status)
            if transition_date:
                result = transition_date.date()
                if self.verbosity >= 3:
                    typer.echo(
                        f"      [DEBUG] start_date: from transition to '{mapping.transition_to_status}' = {result}"
                    )
                return result

        if self.verbosity >= 3:
            typer.echo("      [DEBUG] start_date: no value found")
        return None

    def extract_end_date(self, issue_data: JiraIssueData) -> date | None:
        """Extract end_date from issue data.

        Args:
            issue_data: Fetched Jira issue data

        Returns:
            Extracted end date or None
        """
        mapping = self.config.field_mappings.end_date
        if not mapping:
            if self.verbosity >= 3:
                typer.echo("      [DEBUG] end_date: no mapping configured")
            return None

        if mapping.explicit_field:
            value = self._get_date_field(issue_data, mapping.explicit_field)
            if value:
                if self.verbosity >= 3:
                    typer.echo(
                        f"      [DEBUG] end_date: from field '{mapping.explicit_field}' = {value}"
                    )
                return value

        if mapping.transition_to_status:
            transition_date = issue_data.status_transitions.get(mapping.transition_to_status)
            if transition_date:
                result = transition_date.date()
                if self.verbosity >= 3:
                    typer.echo(
                        f"      [DEBUG] end_date: from transition to '{mapping.transition_to_status}' = {result}"
                    )
                return result

        if self.verbosity >= 3:
            typer.echo("      [DEBUG] end_date: no value found")
        return None

    def extract_effort(self, issue_data: JiraIssueData) -> str | None:
        """Extract effort from issue data using human-readable field names.

        Args:
            issue_data: Fetched Jira issue data

        Returns:
            Effort string in Mouc format (e.g., "2w", "3d") or None
        """
        mapping = self.config.field_mappings.effort
        if not mapping or not mapping.jira_field:
            if self.verbosity >= 3:
                typer.echo("      [DEBUG] effort: no mapping configured")
            return None

        # Use the client to resolve the field name (e.g., "Story Points")
        value = self.client.get_custom_field_value(issue_data, mapping.jira_field)
        if value is None:
            if self.verbosity >= 3:
                typer.echo(f"      [DEBUG] effort: field '{mapping.jira_field}' not found or null")
            return None

        if self.verbosity >= 3:
            typer.echo(f"      [DEBUG] effort: from field '{mapping.jira_field}' = {value}")

        if mapping.conversion:
            result = self._convert_effort(value, mapping.conversion, mapping.unit)
            if self.verbosity >= 3:
                typer.echo(
                    f"      [DEBUG] effort: converted using '{mapping.conversion}' → {result}"
                )
            return result

        if isinstance(value, str):
            return value

        if mapping.unit and isinstance(value, (int, float)):
            return f"{value}{mapping.unit}"

        return str(value)

    def extract_status(self, issue_data: JiraIssueData) -> str | None:
        """Extract status from issue data.

        Args:
            issue_data: Fetched Jira issue data

        Returns:
            Mapped status value or None
        """
        mapping = self.config.field_mappings.status
        if not mapping or not mapping.status_map:
            if self.verbosity >= 3:
                typer.echo("      [DEBUG] status: no mapping configured")
            return None

        jira_status = issue_data.status
        result = mapping.status_map.get(jira_status)
        if self.verbosity >= 3:
            if result:
                typer.echo(f"      [DEBUG] status: Jira status '{jira_status}' → '{result}'")
            else:
                typer.echo(
                    f"      [DEBUG] status: Jira status '{jira_status}' not in map, returning None"
                )
        return result

    def extract_resources(self, issue_data: JiraIssueData) -> list[str] | None:
        """Extract resources (assignee) from issue data.

        Uses the new unified resource mapping logic with priority:
        1. Explicit jira_username in resource definitions
        2. Auto-stripped domain (if enabled and matches a resource)
        3. Full email as fallback

        Args:
            issue_data: Fetched Jira issue data

        Returns:
            List of resource names or None (None means "don't update this field")
        """
        mapping = self.config.field_mappings.resources
        if not mapping:
            if self.verbosity >= 3:
                typer.echo("      [DEBUG] resources: no mapping configured")
            return None

        # Use the new unified mapping logic
        from mouc.unified_config import map_jira_user_to_resource

        if self.verbosity >= 3:
            if issue_data.assignee_email:
                typer.echo(f"      [DEBUG] resources: assignee = '{issue_data.assignee_email}'")
            else:
                typer.echo("      [DEBUG] resources: unassigned (will not update field)")

        result = map_jira_user_to_resource(
            issue_data.assignee_email,
            self.resource_config,
            self.config,
        )

        if self.verbosity >= 3:
            if result:
                typer.echo(f"      [DEBUG] resources: mapped to {result}")
            else:
                typer.echo("      [DEBUG] resources: ignored/unassigned (will not update field)")

        return result

    def _get_date_field(self, issue_data: JiraIssueData, field_name: str) -> date | None:
        """Get and parse a date field from issue data using human-readable field names.

        Args:
            issue_data: Fetched Jira issue data
            field_name: Display name of the date field (e.g., "Start date", "Due Date")

        Returns:
            Parsed date or None
        """
        # Use the client to resolve the field name (handles custom fields)
        value = self.client.get_custom_field_value(issue_data, field_name)
        if value:
            return self._parse_date(value)

        return None

    def _parse_date(self, value: Any) -> date | None:
        """Parse various date formats from Jira.

        Args:
            value: Date value from Jira (string or datetime)

        Returns:
            Parsed date or None
        """
        if isinstance(value, date):
            return value

        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, str):
            try:
                if "T" in value:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return dt.date()
                return date.fromisoformat(value)
            except ValueError:
                pass

        return None

    def _convert_effort(self, value: Any, conversion: str, unit: str | None) -> str | None:
        """Convert effort value using conversion rule.

        Args:
            value: Raw value from Jira
            conversion: Conversion rule (e.g., "1sp=1d", "2sp=1w")
            unit: Unit of the Jira value

        Returns:
            Converted effort string in Mouc format
        """
        if not isinstance(value, (int, float)):
            return None

        match = re.match(r"(\d+(?:\.\d+)?)sp=(\d+(?:\.\d+)?)([dwm])", conversion)
        if not match:
            return None

        input_units = float(match.group(1))
        output_units = float(match.group(2))
        time_unit = match.group(3)

        converted = (value / input_units) * output_units
        formatted = f"{converted:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}{time_unit}"


def validate_field_value(field: str, value: Any, entity: Entity) -> tuple[bool, str | None]:
    """Validate a field value from Jira.

    Args:
        field: Field name
        value: Value to validate
        entity: Entity being synced (for context like other field values)

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if value is None:
        return True, None

    # Validate dates
    if field in ("start_date", "end_date"):
        if not isinstance(value, (date, datetime)):
            return False, f"{field} must be a date, got {type(value).__name__}"

        # Check date consistency
        if field == "start_date":
            end_date = entity.meta.get("end_date")
            if end_date and isinstance(end_date, (date, datetime)):
                end_date_val = end_date.date() if isinstance(end_date, datetime) else end_date
                start_date_val = value.date() if isinstance(value, datetime) else value
                if start_date_val > end_date_val:
                    return (
                        False,
                        f"start_date ({start_date_val}) is after end_date ({end_date_val})",
                    )
        elif field == "end_date":
            start_date = entity.meta.get("start_date")
            if start_date and isinstance(start_date, (date, datetime)):
                start_date_val = (
                    start_date.date() if isinstance(start_date, datetime) else start_date
                )
                end_date_val = value.date() if isinstance(value, datetime) else value
                if end_date_val < start_date_val:
                    return (
                        False,
                        f"end_date ({end_date_val}) is before start_date ({start_date_val})",
                    )

    # Validate effort
    if field == "effort" and isinstance(value, str):
        # Parse effort string to ensure it's positive
        effort_match = re.match(r"^(\d+(?:\.\d+)?)(d|w|m)$", value)
        if not effort_match:
            return False, f"effort has invalid format: {value}"
        effort_num = float(effort_match.group(1))
        if effort_num <= 0:
            return False, f"effort must be positive, got {effort_num}"

    # Validate status
    if field == "status" and not isinstance(value, str):
        return False, f"status must be a string, got {type(value).__name__}"

    # Validate resources
    if field == "resources" and not isinstance(value, list):
        return False, f"resources must be a list, got {type(value).__name__}"

    return True, None


class JiraSynchronizer:
    """Orchestrates syncing between Mouc and Jira."""

    def __init__(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        client: JiraClient,
        verbosity: int = 0,
        resource_config: Any = None,
    ):
        """Initialize synchronizer.

        Args:
            config: Jira configuration
            feature_map: Mouc feature map
            client: Jira API client
            verbosity: Verbosity level (0=silent, 1=changes only, 2=all checks)
            resource_config: Optional ResourceConfig for resource mapping
        """
        self.config = config
        self.feature_map = feature_map
        self.client = client
        self.extractor = FieldExtractor(config, client, resource_config, verbosity)
        self.verbosity = verbosity

    def sync_all_entities(self) -> list[SyncResult]:
        """Sync all entities that have Jira links.

        Returns:
            List of sync results for all entities
        """
        results: list[SyncResult] = []
        for entity in self.feature_map.entities:
            jira_links = [link for link in entity.parsed_links if link.type == "jira"]
            if not jira_links:
                continue

            ticket_id = self._extract_ticket_id(jira_links[0])
            if not ticket_id:
                continue

            try:
                result = self.sync_entity(entity.id, entity, ticket_id)
                results.append(result)
            except JiraError as e:
                results.append(
                    SyncResult(
                        entity_id=entity.id,
                        ticket_id=ticket_id,
                        updated_fields={},
                        conflicts=[],
                        errors=[f"Failed to fetch issue: {e}"],
                    )
                )

        return results

    def sync_entity(self, entity_id: str, entity: Entity, ticket_id: str) -> SyncResult:
        """Sync a single entity with its Jira ticket.

        Args:
            entity_id: Entity identifier
            entity: Entity object
            ticket_id: Jira ticket ID

        Returns:
            Sync result with updated fields and conflicts

        Raises:
            JiraError: If issue fetch fails
        """
        if self.verbosity >= 2:
            typer.echo(f"Checking {entity_id} ({ticket_id})...")

        issue_data = self.client.fetch_issue(ticket_id)

        updated_fields: dict[str, Any] = {}
        conflicts: list[FieldConflict] = []

        self._sync_field(
            "start_date",
            entity,
            entity_id,
            ticket_id,
            self.extractor.extract_start_date(issue_data),
            updated_fields,
            conflicts,
        )

        self._sync_field(
            "end_date",
            entity,
            entity_id,
            ticket_id,
            self.extractor.extract_end_date(issue_data),
            updated_fields,
            conflicts,
        )

        self._sync_field(
            "effort",
            entity,
            entity_id,
            ticket_id,
            self.extractor.extract_effort(issue_data),
            updated_fields,
            conflicts,
        )

        self._sync_field(
            "status",
            entity,
            entity_id,
            ticket_id,
            self.extractor.extract_status(issue_data),
            updated_fields,
            conflicts,
        )

        self._sync_field(
            "resources",
            entity,
            entity_id,
            ticket_id,
            self.extractor.extract_resources(issue_data),
            updated_fields,
            conflicts,
        )

        # Show changes at verbosity level 1+
        if self.verbosity >= 1 and (updated_fields or conflicts):
            if updated_fields:
                typer.echo(f"  {entity_id}:")
                for field, new_value in updated_fields.items():
                    old_value = entity.meta.get(field)
                    if old_value is None:
                        typer.echo(f"    {field}: (none) → {new_value}")
                    else:
                        typer.echo(f"    {field}: {old_value} → {new_value}")
            if conflicts:
                typer.echo(f"  {entity_id} (conflicts):")
                for conflict in conflicts:
                    typer.echo(
                        f"    {conflict.field}: mouc={conflict.mouc_value} | jira={conflict.jira_value}"
                    )

        return SyncResult(
            entity_id=entity_id,
            ticket_id=ticket_id,
            updated_fields=updated_fields,
            conflicts=conflicts,
            errors=[],
        )

    def _sync_field(
        self,
        field: str,
        entity: Entity,
        entity_id: str,
        ticket_id: str,
        jira_value: Any,
        updated_fields: dict[str, Any],
        conflicts: list[FieldConflict],
    ) -> None:
        """Sync a single field, detecting conflicts.

        Args:
            field: Field name
            entity: Entity object
            entity_id: Entity identifier
            ticket_id: Jira ticket ID
            jira_value: Extracted value from Jira
            updated_fields: Dict to accumulate updates
            conflicts: List to accumulate conflicts
        """
        if jira_value is None:
            return

        # Get jira_sync metadata
        jira_sync = entity.get_jira_sync_metadata()

        # Check if field is ignored entirely
        if field in jira_sync.ignore_fields:
            if self.verbosity >= 2:
                typer.echo(f"    [IGNORED] {field} (field is in ignore_fields)")
            return

        # Check if this specific value should be ignored
        if field in jira_sync.ignore_values:
            ignored_values = jira_sync.ignore_values[field]
            for ignored_value in ignored_values:
                if self._values_equal(jira_value, ignored_value):
                    if self.verbosity >= 2:
                        typer.echo(
                            f"    [IGNORED] {field}={jira_value} (value is in ignore_values)"
                        )
                    return

        # Validate the Jira value
        is_valid, error_msg = validate_field_value(field, jira_value, entity)
        if not is_valid:
            if self.verbosity >= 1:
                typer.echo(f"    [INVALID] {field}={jira_value}: {error_msg}")
            # Create conflict for invalid data
            mouc_value = entity.meta.get(field)
            conflicts.append(
                FieldConflict(
                    entity_id=entity_id,
                    field=field,
                    mouc_value=mouc_value,
                    jira_value=f"INVALID: {jira_value} ({error_msg})",
                    ticket_id=ticket_id,
                    resolution=ConflictResolution.ASK,
                )
            )
            return

        mouc_value = entity.meta.get(field)

        # If mouc has no value, apply Jira value
        if mouc_value is None:
            updated_fields[field] = jira_value
            return

        # If values are equal, no sync needed
        if self._values_equal(mouc_value, jira_value):
            return

        # Check if user previously made a resolution choice for this field
        if field in jira_sync.resolution_choices:
            remembered_choice = jira_sync.resolution_choices[field]
            if self.verbosity >= 2:
                typer.echo(f"    [REMEMBERED] {field}: using previous choice '{remembered_choice}'")
            if remembered_choice == "jira":
                updated_fields[field] = jira_value
            elif remembered_choice == "mouc":
                pass  # Keep mouc value
            # If choice was "skip", we do nothing (same as mouc)
            return

        # Otherwise, use configured conflict resolution
        resolution = self.config.get_conflict_resolution(field)

        if resolution == ConflictResolution.JIRA_WINS:
            updated_fields[field] = jira_value
        elif resolution == ConflictResolution.MOUC_WINS:
            pass
        elif resolution == ConflictResolution.ASK:
            conflicts.append(
                FieldConflict(
                    entity_id=entity_id,
                    field=field,
                    mouc_value=mouc_value,
                    jira_value=jira_value,
                    ticket_id=ticket_id,
                    resolution=resolution,
                )
            )

    def _values_equal(self, value1: Any, value2: Any) -> bool:
        """Compare two values for equality, handling different types.

        Args:
            value1: First value
            value2: Second value

        Returns:
            True if values are considered equal
        """
        if isinstance(value1, (date, datetime)) and isinstance(value2, (date, datetime)):
            d1 = value1.date() if isinstance(value1, datetime) else value1
            d2 = value2.date() if isinstance(value2, datetime) else value2
            return d1 == d2

        if isinstance(value1, (date, datetime)):
            value1 = value1.isoformat() if isinstance(value1, datetime) else str(value1)
        if isinstance(value2, (date, datetime)):
            value2 = value2.isoformat() if isinstance(value2, datetime) else str(value2)

        return value1 == value2

    def _extract_ticket_id(self, link: Link) -> str | None:
        """Extract Jira ticket ID from a link.

        Args:
            link: Jira link object

        Returns:
            Ticket ID or None
        """
        if link.label:
            return link.label.strip()

        if ":" in link.raw:
            return link.raw.split(":")[-1].strip()

        return link.raw.strip()
