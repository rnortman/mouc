"""Interactive conflict resolution for Jira sync."""

from __future__ import annotations

from typing import Any

import typer

from mouc.jira_sync import FieldConflict


class InteractiveResolver:
    """Handles interactive conflict resolution via terminal prompts."""

    def resolve_conflicts(self, conflicts: list[FieldConflict]) -> dict[str, dict[str, Any]]:
        """Prompt user to resolve conflicts interactively.

        Args:
            conflicts: List of field conflicts to resolve

        Returns:
            Dict mapping entity_id to dict of field -> chosen value
        """
        if not conflicts:
            return {}

        typer.echo("\n" + "=" * 70)
        typer.echo(f"Found {len(conflicts)} conflicts that require your input:")
        typer.echo("=" * 70 + "\n")

        resolutions: dict[str, dict[str, Any]] = {}

        for i, conflict in enumerate(conflicts, 1):
            typer.echo(f"Conflict {i}/{len(conflicts)}:")
            typer.echo(f"  Entity: {conflict.entity_id}")
            typer.echo(f"  Field: {conflict.field}")
            typer.echo(f"  Jira ticket: {conflict.ticket_id}")
            typer.echo(f"  Mouc value: {self._format_value(conflict.mouc_value)}")
            typer.echo(f"  Jira value: {self._format_value(conflict.jira_value)}")
            typer.echo()

            choice = self._prompt_choice()

            if choice == "j":
                chosen_value = conflict.jira_value
                typer.echo(f"  → Using Jira value: {self._format_value(chosen_value)}\n")
            elif choice == "m":
                chosen_value = conflict.mouc_value
                typer.echo(f"  → Keeping Mouc value: {self._format_value(chosen_value)}\n")
            elif choice == "s":
                typer.echo("  → Skipping this conflict\n")
                continue
            else:
                typer.echo("  → Skipping due to invalid input\n")
                continue

            if conflict.entity_id not in resolutions:
                resolutions[conflict.entity_id] = {}
            resolutions[conflict.entity_id][conflict.field] = chosen_value

        typer.echo("=" * 70)
        typer.echo(f"Resolved {sum(len(fields) for fields in resolutions.values())} conflicts")
        typer.echo("=" * 70 + "\n")

        return resolutions

    def _prompt_choice(self) -> str:
        """Prompt user to choose between Jira, Mouc, or skip.

        Returns:
            Choice: 'j' for Jira, 'm' for Mouc, 's' for skip
        """
        while True:
            choice = (
                typer.prompt(
                    "  Which value do you want to use? (j=Jira, m=Mouc, s=skip)",
                    default="j",
                )
                .lower()
                .strip()
            )

            if choice in ("j", "m", "s"):
                return choice

            typer.echo("  Invalid choice. Please enter 'j', 'm', or 's'.")

    def _format_value(self, value: Any) -> str:
        """Format a value for display.

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
