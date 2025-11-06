"""CSV report generation for Jira sync conflicts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from mouc.jira_sync import FieldConflict, SyncResult


class ReportGenerator:
    """Generates CSV reports for Jira sync results and conflicts."""

    def generate_conflict_report(
        self, conflicts: list[FieldConflict], output_path: Path | str
    ) -> None:
        """Generate CSV report of conflicts.

        Args:
            conflicts: List of field conflicts
            output_path: Path to output CSV file
        """
        output_path = Path(output_path)

        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow(
                [
                    "Entity ID",
                    "Field",
                    "Mouc Value",
                    "Jira Value",
                    "Ticket ID",
                    "Recommended Action",
                    "Resolution",
                ]
            )

            for conflict in conflicts:
                writer.writerow(
                    [
                        conflict.entity_id,
                        conflict.field,
                        self._format_value(conflict.mouc_value),
                        self._format_value(conflict.jira_value),
                        conflict.ticket_id,
                        self._recommend_action(conflict),
                        "",
                    ]
                )

    def generate_sync_report(self, results: list[SyncResult], output_path: Path | str) -> None:
        """Generate comprehensive CSV report of all sync results.

        Args:
            results: List of sync results
            output_path: Path to output CSV file
        """
        output_path = Path(output_path)

        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow(
                [
                    "Entity ID",
                    "Ticket ID",
                    "Status",
                    "Field",
                    "New Value",
                    "Conflict",
                    "Error",
                ]
            )

            for result in results:
                if result.errors:
                    for error in result.errors:
                        writer.writerow(
                            [
                                result.entity_id,
                                result.ticket_id,
                                "ERROR",
                                "",
                                "",
                                "",
                                error,
                            ]
                        )
                    continue

                if result.updated_fields:
                    for field, value in result.updated_fields.items():
                        writer.writerow(
                            [
                                result.entity_id,
                                result.ticket_id,
                                "AUTO_UPDATE",
                                field,
                                self._format_value(value),
                                "No",
                                "",
                            ]
                        )

                if result.conflicts:
                    for conflict in result.conflicts:
                        writer.writerow(
                            [
                                result.entity_id,
                                result.ticket_id,
                                "CONFLICT",
                                conflict.field,
                                f"Mouc: {self._format_value(conflict.mouc_value)}, "
                                f"Jira: {self._format_value(conflict.jira_value)}",
                                "Yes",
                                "",
                            ]
                        )

                if not result.updated_fields and not result.conflicts and not result.errors:
                    writer.writerow(
                        [
                            result.entity_id,
                            result.ticket_id,
                            "NO_CHANGE",
                            "",
                            "",
                            "No",
                            "",
                        ]
                    )

    def _format_value(self, value: Any) -> str:
        """Format a value for CSV output.

        Args:
            value: Value to format

        Returns:
            Formatted string representation
        """
        if value is None:
            return "(empty)"
        if isinstance(value, list):
            value_list: list[Any] = value  # type: ignore[reportUnknownVariableType]
            return ", ".join(str(v) for v in value_list)
        return str(value)

    def _recommend_action(self, conflict: FieldConflict) -> str:
        """Recommend an action for a conflict.

        Args:
            conflict: Field conflict

        Returns:
            Recommended action string
        """
        if conflict.field in ("start_date", "end_date", "status"):
            return "Use Jira (more authoritative for dates/status)"
        if conflict.field == "effort":
            return "Review both (effort may be estimated differently)"
        if conflict.field == "resources":
            return "Use Jira (reflects current assignment)"
        return "Review both"
