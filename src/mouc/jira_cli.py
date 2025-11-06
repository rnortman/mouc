"""Jira CLI commands."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from . import cli
from .jira_client import JiraAuthError, JiraClient, JiraError
from .jira_config import load_jira_config
from .jira_interactive import InteractiveResolver
from .jira_report import ReportGenerator
from .jira_sync import FieldConflict, JiraSynchronizer
from .models import Entity, Link
from .parser import FeatureMapParser

# Create Jira sub-app
jira_app = typer.Typer(help="Jira integration commands")


@jira_app.command("validate")
def jira_validate(
    config: Annotated[Path, typer.Option("--config", "-c", help="Path to jira_config.yaml")] = Path(
        "jira_config.yaml"
    ),
) -> None:
    """Validate Jira configuration and test connection."""
    from .exceptions import MoucError

    try:
        # Load config
        typer.echo(f"Loading config from {config}...")
        jira_config = load_jira_config(config)
        typer.echo(f"✓ Config loaded: {jira_config.jira.base_url}")

        # Create client
        typer.echo("Testing Jira connection...")
        client = JiraClient(jira_config.jira.base_url)

        # Validate connection
        client.validate_connection()
        typer.echo("✓ Connected to Jira successfully")
        typer.echo(f"✓ Authenticated as: {client.email}")

    except JiraAuthError as e:
        typer.echo(f"Authentication error: {e}", err=True)
        typer.echo(
            "\nMake sure JIRA_EMAIL and JIRA_API_TOKEN environment variables are set.",
            err=True,
        )
        raise typer.Exit(1) from None
    except JiraError as e:
        typer.echo(f"Jira error: {e}", err=True)
        raise typer.Exit(1) from None
    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        import traceback

        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


@jira_app.command("fetch")
def jira_fetch(
    ticket: Annotated[str, typer.Argument(help="Jira ticket ID (e.g., PROJ-123)")],
    config: Annotated[Path, typer.Option("--config", "-c", help="Path to jira_config.yaml")] = Path(
        "jira_config.yaml"
    ),
) -> None:
    """Fetch and display data for a single Jira ticket."""
    from .exceptions import MoucError

    try:
        # Load config
        jira_config = load_jira_config(config)

        # Create client
        client = JiraClient(jira_config.jira.base_url)

        # Fetch issue
        typer.echo(f"Fetching {ticket}...")
        issue_data = client.fetch_issue(ticket)

        # Display results
        typer.echo(f"\n{'=' * 60}")
        typer.echo(f"Key: {issue_data.key}")
        typer.echo(f"Summary: {issue_data.summary}")
        typer.echo(f"Status: {issue_data.status}")
        typer.echo(f"Assignee: {issue_data.assignee_email or 'Unassigned'}")

        if issue_data.status_transitions:
            typer.echo("\nStatus Transitions:")
            for status, timestamp in sorted(
                issue_data.status_transitions.items(), key=lambda x: x[1]
            ):
                typer.echo(f"  {status}: {timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        typer.echo(f"{'=' * 60}\n")

    except JiraAuthError as e:
        typer.echo(f"Authentication error: {e}", err=True)
        raise typer.Exit(1) from None
    except JiraError as e:
        typer.echo(f"Jira error: {e}", err=True)
        raise typer.Exit(1) from None
    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        import traceback

        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


@jira_app.command("list")
def jira_list(
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
) -> None:
    """List all entities with Jira links."""
    from .exceptions import MoucError

    try:
        # Parse the feature map
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        # Find entities with jira links
        entities_with_jira: list[tuple[str, Entity, list[Link]]] = []
        for entity in feature_map.entities:
            jira_links: list[Link] = [link for link in entity.parsed_links if link.type == "jira"]
            if jira_links:
                entities_with_jira.append((entity.id, entity, jira_links))

        if not entities_with_jira:
            typer.echo("No entities with Jira links found.")
            return

        typer.echo(f"Found {len(entities_with_jira)} entities with Jira links:\n")
        for entity_id, entity, jira_links in entities_with_jira:
            typer.echo(f"{entity_id} ({entity.type}):")
            typer.echo(f"  Name: {entity.name}")
            for link in jira_links:
                ticket_id = link.label or link.raw.split(":")[-1].strip()
                typer.echo(f"  Jira: {ticket_id}")
            typer.echo()

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        import traceback

        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


@jira_app.command("sync")
def jira_sync(
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    config: Annotated[Path, typer.Option("--config", "-c", help="Path to jira_config.yaml")] = Path(
        "jira_config.yaml"
    ),
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Prompt for conflicts interactively")
    ] = False,
    report: Annotated[
        Path | None, typer.Option("--report", "-r", help="Generate conflict report CSV")
    ] = None,
    answers: Annotated[
        Path | None, typer.Option("--answers", "-a", help="Path to YAML file with conflict answers")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would change without modifying")
    ] = False,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply changes to feature_map.yaml")
    ] = False,
) -> None:
    """Sync Mouc entities with Jira issues."""
    from .exceptions import MoucError

    try:
        # Validate arguments
        if sum([interactive, bool(report), bool(answers)]) > 1:
            typer.echo(
                "Error: Cannot use more than one of --interactive, --report, --answers", err=True
            )
            raise typer.Exit(1) from None

        if apply and dry_run:
            typer.echo("Error: Cannot use both --apply and --dry-run", err=True)
            raise typer.Exit(1) from None

        # Get verbosity level from global state
        verbosity = cli.get_verbosity()

        # Auto-enable verbosity for dry-run if not already set
        if dry_run and verbosity == 0:
            verbosity = 1

        # Load config and feature map
        if verbosity == 0:
            typer.echo(f"Loading config from {config}...")
        jira_config = load_jira_config(config)

        if verbosity == 0:
            typer.echo(f"Loading feature map from {file}...")
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        # Create client and synchronizer
        if verbosity == 0:
            typer.echo(f"Connecting to Jira at {jira_config.jira.base_url}...")
        client = JiraClient(jira_config.jira.base_url)
        synchronizer = JiraSynchronizer(jira_config, feature_map, client, verbosity=verbosity)

        # Sync all entities
        if verbosity == 0:
            typer.echo("Syncing entities with Jira...")
        results = synchronizer.sync_all_entities()

        # Count results
        total_entities = len(results)
        entities_with_updates = len([r for r in results if r.updated_fields])
        entities_with_conflicts = len([r for r in results if r.conflicts])
        entities_with_errors = len([r for r in results if r.errors])

        # Always show summary
        typer.echo("\nSync completed:")
        typer.echo(f"  Total entities: {total_entities}")
        typer.echo(f"  Entities with automatic updates: {entities_with_updates}")
        typer.echo(f"  Entities with conflicts: {entities_with_conflicts}")
        typer.echo(f"  Entities with errors: {entities_with_errors}\n")

        # Show errors (always)
        for result in results:
            if result.errors:
                typer.echo(f"Error syncing {result.entity_id}:", err=True)
                for error in result.errors:
                    typer.echo(f"  {error}", err=True)

        all_conflicts: list[FieldConflict] = []
        for result in results:
            all_conflicts.extend(result.conflicts)

        conflict_resolutions: dict[str, dict[str, Any]] = {}
        if all_conflicts:
            if interactive:
                resolver = InteractiveResolver()
                conflict_resolutions = resolver.resolve_conflicts(all_conflicts)
            elif answers:
                typer.echo(f"Loading conflict answers from {answers}...")
                conflict_resolutions = _load_conflict_answers(answers, all_conflicts)
            elif report:
                generator = ReportGenerator()
                generator.generate_conflict_report(all_conflicts, report)
                typer.echo(f"Conflict report written to {report}")
                typer.echo("Review the report and re-run with --apply once resolved.")
                return
            else:
                questions_yaml = Path("jira_conflicts.yaml")
                questions_csv = Path("jira_conflicts.csv")
                _generate_questions_file(all_conflicts, questions_yaml)
                _generate_questions_csv(all_conflicts, questions_csv)
                typer.echo(
                    f"\nFound {len(all_conflicts)} conflicts that require resolution.",
                    err=True,
                )
                typer.echo("Questions files generated:", err=True)
                typer.echo(f"  YAML: {questions_yaml}", err=True)
                typer.echo(f"  CSV:  {questions_csv}", err=True)
                typer.echo(
                    "\nFill in the 'choice' column (jira/mouc/skip), "
                    "then re-run with --answers <file> --apply",
                    err=True,
                )
                typer.echo("(Accepts either YAML or CSV format)", err=True)
                raise typer.Exit(1) from None

        if apply and not dry_run:
            if verbosity >= 1:
                typer.echo("\nApplying changes to feature map...")

            for result in results:
                if result.updated_fields:
                    entity = feature_map.get_entity_by_id(result.entity_id)
                    if entity:
                        for field, value in result.updated_fields.items():
                            entity.meta[field] = value
                        if verbosity >= 1:
                            typer.echo(
                                f"  Updated {result.entity_id}: {', '.join(result.updated_fields.keys())}"
                            )

            for entity_id, field_updates in conflict_resolutions.items():
                entity = feature_map.get_entity_by_id(entity_id)
                if entity:
                    for field, value in field_updates.items():
                        entity.meta[field] = value
                    if verbosity >= 1:
                        typer.echo(f"  Updated {entity_id}: {', '.join(field_updates.keys())}")

            _write_feature_map(file, feature_map)
            typer.echo(f"\n✓ Changes written to {file}")

        elif dry_run:
            if verbosity >= 1:
                typer.echo("\nDry run - no changes made. Changes that would be applied:")
                for result in results:
                    if result.updated_fields:
                        typer.echo(f"  {result.entity_id}:")
                        for field, value in result.updated_fields.items():
                            typer.echo(f"    {field}: {value}")

    except JiraAuthError as e:
        typer.echo(f"Authentication error: {e}", err=True)
        raise typer.Exit(1) from None
    except JiraError as e:
        typer.echo(f"Jira error: {e}", err=True)
        raise typer.Exit(1) from None
    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        import traceback

        typer.echo(f"Unexpected error: {e}", err=True)
        traceback.print_exc()
        raise typer.Exit(1) from None


def _write_feature_map(file_path: Path, feature_map: Any) -> None:
    """Write feature map back to YAML file.

    Args:
        file_path: Path to feature map file
        feature_map: FeatureMap object to write
    """
    with file_path.open() as f:
        data = yaml.safe_load(f)

    if "entities" in data:
        for entity in feature_map.entities:
            if entity.id in data["entities"]:
                data["entities"][entity.id]["meta"] = entity.meta

    with file_path.open("w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def _generate_questions_file(conflicts: list[FieldConflict], output_path: Path) -> None:
    """Generate YAML file with conflict questions.

    Args:
        conflicts: List of field conflicts
        output_path: Path to write questions file
    """
    questions: list[dict[str, Any]] = []
    for i, conflict in enumerate(conflicts, 1):
        questions.append(
            {
                "conflict_id": i,
                "entity_id": conflict.entity_id,
                "field": conflict.field,
                "mouc_value": str(conflict.mouc_value),
                "jira_value": str(conflict.jira_value),
                "ticket_id": conflict.ticket_id,
                "choice": "",
            }
        )

    with output_path.open("w") as f:
        yaml.safe_dump(
            {
                "conflicts": questions,
                "instructions": "Fill in 'choice' field for each conflict with: jira, mouc, or skip",
            },
            f,
            default_flow_style=False,
            sort_keys=False,
        )


def _generate_questions_csv(conflicts: list[FieldConflict], output_path: Path) -> None:
    """Generate CSV file with conflict questions.

    Args:
        conflicts: List of field conflicts
        output_path: Path to write questions CSV
    """
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow(
            [
                "conflict_id",
                "entity_id",
                "field",
                "mouc_value",
                "jira_value",
                "ticket_id",
                "choice",
            ]
        )

        for i, conflict in enumerate(conflicts, 1):
            writer.writerow(
                [
                    i,
                    conflict.entity_id,
                    conflict.field,
                    str(conflict.mouc_value),
                    str(conflict.jira_value),
                    conflict.ticket_id,
                    "",
                ]
            )


def _load_conflict_answers(
    answers_path: Path, conflicts: list[FieldConflict]
) -> dict[str, dict[str, Any]]:
    """Load conflict answers from YAML or CSV file.

    Args:
        answers_path: Path to answers file (YAML or CSV)
        conflicts: List of all conflicts

    Returns:
        Dict mapping entity_id to field updates

    Raises:
        typer.Exit: If answers file is invalid
    """
    # Detect file format by extension
    if answers_path.suffix.lower() == ".csv":
        return _load_conflict_answers_csv(answers_path, conflicts)
    return _load_conflict_answers_yaml(answers_path, conflicts)


def _load_conflict_answers_yaml(
    answers_path: Path, conflicts: list[FieldConflict]
) -> dict[str, dict[str, Any]]:
    """Load conflict answers from YAML file.

    Args:
        answers_path: Path to YAML answers file
        conflicts: List of all conflicts

    Returns:
        Dict mapping entity_id to field updates

    Raises:
        typer.Exit: If answers file is invalid
    """
    with answers_path.open() as f:
        data = yaml.safe_load(f)

    if "conflicts" not in data:
        typer.echo("Error: Invalid answers file format", err=True)
        raise typer.Exit(1) from None

    resolutions: dict[str, dict[str, Any]] = {}

    for answer in data["conflicts"]:
        choice = answer.get("choice", "").lower().strip()
        if not choice or choice == "skip":
            continue

        entity_id = answer["entity_id"]
        field = answer["field"]

        conflict = next(
            (c for c in conflicts if c.entity_id == entity_id and c.field == field), None
        )
        if not conflict:
            continue

        if choice == "jira":
            chosen_value = conflict.jira_value
        elif choice == "mouc":
            chosen_value = conflict.mouc_value
        else:
            typer.echo(
                f"Warning: Invalid choice '{choice}' for {entity_id}.{field}, skipping",
                err=True,
            )
            continue

        if entity_id not in resolutions:
            resolutions[entity_id] = {}
        resolutions[entity_id][field] = chosen_value

    return resolutions


def _load_conflict_answers_csv(
    answers_path: Path, conflicts: list[FieldConflict]
) -> dict[str, dict[str, Any]]:
    """Load conflict answers from CSV file.

    Args:
        answers_path: Path to CSV answers file
        conflicts: List of all conflicts

    Returns:
        Dict mapping entity_id to field updates

    Raises:
        typer.Exit: If answers file is invalid
    """
    resolutions: dict[str, dict[str, Any]] = {}

    with answers_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            choice = row.get("choice", "").lower().strip()
            if not choice or choice == "skip":
                continue

            entity_id = row["entity_id"]
            field = row["field"]

            conflict = next(
                (c for c in conflicts if c.entity_id == entity_id and c.field == field), None
            )
            if not conflict:
                continue

            if choice == "jira":
                chosen_value = conflict.jira_value
            elif choice == "mouc":
                chosen_value = conflict.mouc_value
            else:
                typer.echo(
                    f"Warning: Invalid choice '{choice}' for {entity_id}.{field}, skipping",
                    err=True,
                )
                continue

            if entity_id not in resolutions:
                resolutions[entity_id] = {}
            resolutions[entity_id][field] = chosen_value

    return resolutions
