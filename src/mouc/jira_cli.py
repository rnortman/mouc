"""Jira CLI commands."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from ruamel.yaml import YAML

from . import context
from .jira_client import JiraAuthError, JiraClient, JiraError
from .jira_interactive import InteractiveResolver
from .jira_report import ReportGenerator
from .jira_sync import FieldConflict, JiraSynchronizer
from .models import Entity, Link
from .parser import FeatureMapParser

# Create Jira sub-app
jira_app = typer.Typer(help="Jira integration commands")


def _load_jira_config_from_path(config_path: Path) -> Any:
    """Load Jira config from unified config file.

    Args:
        config_path: Path to mouc_config.yaml file

    Returns:
        JiraConfig object

    Raises:
        FileNotFoundError: If config doesn't exist
        ValueError: If config doesn't contain Jira settings
    """
    from .unified_config import load_unified_config

    unified = load_unified_config(config_path)
    if unified.jira is None:
        raise ValueError(f"Config file {config_path} doesn't contain 'jira' section")
    return unified.jira


@jira_app.command("validate")
def jira_validate(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file (default: mouc_config.yaml)",
        ),
    ] = None,
) -> None:
    """Validate Jira configuration and test connection."""
    from .exceptions import MoucError

    try:
        # Determine config path
        if config is None:
            global_config = context.get_config_path()
            if global_config:
                config = global_config
            elif Path("mouc_config.yaml").exists():
                config = Path("mouc_config.yaml")
            else:
                typer.echo("Error: No config file found (expected mouc_config.yaml)", err=True)
                raise typer.Exit(1) from None

        # Load config
        typer.echo(f"Loading config from {config}...")
        jira_config = _load_jira_config_from_path(config)
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
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file (default: mouc_config.yaml)",
        ),
    ] = None,
) -> None:
    """Fetch and display data for a single Jira ticket."""
    import json

    from .exceptions import MoucError

    try:
        # Get verbosity level
        verbosity = context.get_verbosity()

        # Determine config path
        if config is None:
            global_config = context.get_config_path()
            if global_config:
                config = global_config
            elif Path("mouc_config.yaml").exists():
                config = Path("mouc_config.yaml")
            else:
                typer.echo("Error: No config file found (expected mouc_config.yaml)", err=True)
                raise typer.Exit(1) from None

        # Load config
        jira_config = _load_jira_config_from_path(config)

        # Create client
        client = JiraClient(jira_config.jira.base_url)

        # Fetch issue
        if verbosity == 0:
            typer.echo(f"Fetching {ticket}...")
        issue_data = client.fetch_issue(ticket)

        # Display results based on verbosity
        if verbosity >= 3:
            # Level 3: Dump raw Jira API response
            typer.echo(f"\n{'=' * 60}")
            typer.echo(f"RAW JIRA API RESPONSE for {ticket}")
            typer.echo(f"{'=' * 60}\n")

            # Fetch raw issue data again with changelog
            raw_issue = client.client.issue(ticket, expand="changelog")  # type: ignore[reportUnknownMemberType]
            typer.echo(json.dumps(raw_issue, indent=2))  # type: ignore[reportUnknownMemberType]

            typer.echo(f"\n{'=' * 60}")
            typer.echo("FIELD DEFINITIONS")
            typer.echo(f"{'=' * 60}\n")

            # Show field mappings
            field_map = client.get_field_mappings()
            typer.echo(json.dumps(field_map, indent=2))

        elif verbosity >= 1:
            # Level 1+: Show status transitions and parsed data
            typer.echo(f"\n{'=' * 60}")
            typer.echo(f"JIRA ISSUE: {issue_data.key}")
            typer.echo(f"{'=' * 60}")
            typer.echo(f"Summary: {issue_data.summary}")
            typer.echo(f"Status: {issue_data.status}")
            typer.echo(f"Assignee: {issue_data.assignee_email or 'Unassigned'}")

            if issue_data.status_transitions:
                typer.echo("\nStatus Transition History:")
                for status, timestamp in sorted(
                    issue_data.status_transitions.items(), key=lambda x: x[1]
                ):
                    typer.echo(f"  {status}: {timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            else:
                typer.echo("\nNo status transitions found in changelog")

            # Show all fields at level 2+
            if verbosity >= 2:
                typer.echo("\nAll Fields:")
                for field_name, value in sorted(issue_data.fields.items()):
                    if value is not None:
                        # Truncate long values
                        value_str = str(value)
                        if len(value_str) > 100:
                            value_str = value_str[:100] + "..."
                        typer.echo(f"  {field_name}: {value_str}")

            typer.echo(f"{'=' * 60}\n")
        else:
            # Level 0: Basic output (original format)
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


def _update_meta_in_place(yaml_entity: Any, new_meta: dict[str, Any]) -> None:
    """Update meta dict in-place to preserve YAML formatting.

    Args:
        yaml_entity: The entity dict from ruamel.yaml (contains formatting info)
        new_meta: The new meta dict to apply
    """
    # If new_meta is empty, don't add or modify meta field
    if not new_meta:
        return

    # If the yaml entity doesn't have a meta field, create it
    if "meta" not in yaml_entity:
        yaml_entity["meta"] = new_meta
        return

    # Update existing meta in-place to preserve formatting
    existing_meta = yaml_entity["meta"]

    # If existing meta is None or empty, replace it
    if existing_meta is None or not existing_meta:
        yaml_entity["meta"] = new_meta
        return

    # Clear keys that are in existing but not in new
    keys_to_remove = [k for k in existing_meta if k not in new_meta]
    for key in keys_to_remove:
        del existing_meta[key]

    # Update/add keys from new_meta - only if value actually changed
    for key, value in new_meta.items():
        # Only update if the value is different to preserve formatting
        if key not in existing_meta or existing_meta[key] != value:
            existing_meta[key] = value


@jira_app.command("sync")
def jira_sync(
    file: Annotated[Path, typer.Argument(help="Path to the feature map YAML file")] = Path(
        "feature_map.yaml"
    ),
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to config file (default: mouc_config.yaml)",
        ),
    ] = None,
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
        verbosity = context.get_verbosity()

        # Auto-enable verbosity for dry-run if not already set
        if dry_run and verbosity == 0:
            verbosity = 1

        # Determine config path
        if config is None:
            global_config = context.get_config_path()
            if global_config:
                config = global_config
            elif Path("mouc_config.yaml").exists():
                config = Path("mouc_config.yaml")
            else:
                typer.echo("Error: No config file found (expected mouc_config.yaml)", err=True)
                raise typer.Exit(1) from None

        # Load config and feature map
        if verbosity == 0:
            typer.echo(f"Loading config from {config}...")

        # Load unified config to get both Jira and Resource configs
        from .unified_config import load_unified_config

        unified_config = None
        resource_config = None
        try:
            unified_config = load_unified_config(config)
            jira_config = unified_config.jira
            resource_config = unified_config.resources
            if jira_config is None:
                raise ValueError(f"Config file {config} doesn't contain 'jira' section")
        except (ValueError, KeyError):
            # Fall back to standalone jira config
            jira_config = _load_jira_config_from_path(config)

        if verbosity == 0:
            typer.echo(f"Loading feature map from {file}...")
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        # Create client and synchronizer
        if verbosity == 0:
            typer.echo(f"Connecting to Jira at {jira_config.jira.base_url}...")
        client = JiraClient(jira_config.jira.base_url)
        synchronizer = JiraSynchronizer(
            jira_config, feature_map, client, verbosity=verbosity, resource_config=resource_config
        )

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
                    jira_sync = entity.get_jira_sync_metadata()
                    for field, value in field_updates.items():
                        entity.meta[field] = value
                        # Save the resolution choice for future syncs
                        # Determine the choice based on the value selected
                        for result in results:
                            if result.entity_id == entity_id:
                                for conflict in result.conflicts:
                                    if conflict.field == field:
                                        if value == conflict.jira_value:
                                            jira_sync.resolution_choices[field] = "jira"
                                        elif value == conflict.mouc_value:
                                            jira_sync.resolution_choices[field] = "mouc"
                                        break
                                break
                    entity.set_jira_sync_metadata(jira_sync)
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
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = False  # type: ignore[assignment]
    # Don't set default_flow_style - let ruamel.yaml preserve original formatting

    with file_path.open() as f:
        data: Any = yaml_rt.load(f)  # type: ignore[no-untyped-call]

    # Build list of all possible sections in the file (new and old format can coexist)
    available_sections = {}
    if "entities" in data:
        available_sections["entities"] = data["entities"]
    if "capabilities" in data:
        available_sections["capabilities"] = data["capabilities"]
    if "user_stories" in data:
        available_sections["user_stories"] = data["user_stories"]
    if "outcomes" in data:
        available_sections["outcomes"] = data["outcomes"]

    if not available_sections:
        raise ValueError(
            f"No entity sections found in {file_path}. "
            "Expected 'entities' or legacy keys 'capabilities', 'user_stories', 'outcomes'"
        )

    # Map entity types to their legacy section names
    type_to_legacy_section = {
        "capability": "capabilities",
        "user_story": "user_stories",
        "outcome": "outcomes",
    }

    entities_updated = 0
    entities_not_found: list[str] = []

    for entity in feature_map.entities:
        found = False

        # First, try the unified 'entities' section
        if "entities" in available_sections and entity.id in available_sections["entities"]:
            _update_meta_in_place(available_sections["entities"][entity.id], entity.meta)
            entities_updated += 1
            found = True
        else:
            # Fall back to legacy section based on entity type
            legacy_section = type_to_legacy_section.get(entity.type)
            if (
                legacy_section
                and legacy_section in available_sections
                and entity.id in available_sections[legacy_section]
            ):
                _update_meta_in_place(available_sections[legacy_section][entity.id], entity.meta)
                entities_updated += 1
                found = True

        if not found:
            entities_not_found.append(entity.id)

    if entities_not_found:
        typer.echo(
            f"Warning: {len(entities_not_found)} entities not found in YAML: "
            f"{', '.join(entities_not_found[:5])}"
            + (f" and {len(entities_not_found) - 5} more" if len(entities_not_found) > 5 else ""),
            err=True,
        )

    with file_path.open("w") as f:
        yaml_rt.dump(data, f)  # type: ignore[no-untyped-call]


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

        if "entity_id" not in answer or "field" not in answer:
            typer.echo(
                f"Error: Answer missing required 'entity_id' or 'field' key: {answer}",
                err=True,
            )
            raise typer.Exit(1) from None

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

            if "entity_id" not in row or "field" not in row:
                typer.echo(
                    f"Error: CSV row missing required 'entity_id' or 'field' column: {row}",
                    err=True,
                )
                raise typer.Exit(1) from None

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


@jira_app.command("ignore-field")
def jira_ignore_field(
    entity_id: Annotated[str, typer.Argument(help="Entity ID")],
    field_name: Annotated[str, typer.Argument(help="Field name to ignore")],
    file: Annotated[
        Path,
        typer.Option("--file", "-f", help="Feature map file"),
    ] = Path("feature_map.yaml"),
) -> None:
    """Mark a field to be completely ignored during Jira sync for an entity.

    This will add the field to the entity's jira_sync.ignore_fields list,
    preventing any future Jira updates to that field.
    """
    from .exceptions import MoucError

    try:
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        entity = feature_map.get_entity_by_id(entity_id)
        if not entity:
            typer.echo(f"Error: Entity '{entity_id}' not found", err=True)
            raise typer.Exit(1) from None

        jira_sync = entity.get_jira_sync_metadata()

        if field_name in jira_sync.ignore_fields:
            typer.echo(f"Field '{field_name}' is already in ignore_fields for {entity_id}")
            return

        jira_sync.ignore_fields.append(field_name)
        entity.set_jira_sync_metadata(jira_sync)

        _write_feature_map(file, feature_map)
        typer.echo(f"✓ Added '{field_name}' to ignore_fields for {entity_id} in {file}")

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@jira_app.command("ignore-value")
def jira_ignore_value(
    entity_id: Annotated[str, typer.Argument(help="Entity ID")],
    field_name: Annotated[str, typer.Argument(help="Field name")],
    value: Annotated[str, typer.Argument(help="Value to ignore (as string)")],
    file: Annotated[
        Path,
        typer.Option("--file", "-f", help="Feature map file"),
    ] = Path("feature_map.yaml"),
) -> None:
    """Mark a specific field value to be ignored during Jira sync.

    This will add the value to the entity's jira_sync.ignore_values list
    for the specified field. When Jira sync encounters this value, it will
    be skipped.

    Example:
        mouc jira ignore-value my_feature start_date 2024-12-01
    """
    from .exceptions import MoucError

    try:
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        entity = feature_map.get_entity_by_id(entity_id)
        if not entity:
            typer.echo(f"Error: Entity '{entity_id}' not found", err=True)
            raise typer.Exit(1) from None

        jira_sync = entity.get_jira_sync_metadata()

        if field_name not in jira_sync.ignore_values:
            jira_sync.ignore_values[field_name] = []

        if value in jira_sync.ignore_values[field_name]:
            typer.echo(f"Value '{value}' is already in ignore_values for {entity_id}.{field_name}")
            return

        jira_sync.ignore_values[field_name].append(value)
        entity.set_jira_sync_metadata(jira_sync)

        _write_feature_map(file, feature_map)
        typer.echo(
            f"✓ Added value '{value}' to ignore_values for {entity_id}.{field_name} in {file}"
        )

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@jira_app.command("show-overrides")
def jira_show_overrides(
    entity_id: Annotated[str | None, typer.Argument(help="Entity ID (optional)")] = None,
    file: Annotated[
        Path,
        typer.Option("--file", "-f", help="Feature map file"),
    ] = Path("feature_map.yaml"),
) -> None:
    """Show Jira sync overrides for entities.

    If entity_id is provided, shows overrides for that entity only.
    Otherwise, shows overrides for all entities.
    """
    from .exceptions import MoucError

    try:
        parser = FeatureMapParser()
        feature_map = parser.parse_file(file)

        entities_to_show: list[Entity] = []
        if entity_id:
            entity = feature_map.get_entity_by_id(entity_id)
            if not entity:
                typer.echo(f"Error: Entity '{entity_id}' not found", err=True)
                raise typer.Exit(1) from None
            entities_to_show = [entity]
        else:
            entities_to_show = feature_map.entities

        found_any = False
        for entity in entities_to_show:
            jira_sync = entity.get_jira_sync_metadata()

            # Check if there are any overrides
            has_overrides = (
                jira_sync.ignore_fields or jira_sync.ignore_values or jira_sync.resolution_choices
            )

            if not has_overrides:
                continue

            found_any = True
            typer.echo(f"\n{entity.id}:")

            if jira_sync.ignore_fields:
                typer.echo("  ignore_fields:")
                for field in jira_sync.ignore_fields:
                    typer.echo(f"    - {field}")

            if jira_sync.ignore_values:
                typer.echo("  ignore_values:")
                for field, values in jira_sync.ignore_values.items():
                    typer.echo(f"    {field}:")
                    for value in values:
                        typer.echo(f"      - {value}")

            if jira_sync.resolution_choices:
                typer.echo("  resolution_choices:")
                for field, choice in jira_sync.resolution_choices.items():
                    typer.echo(f"    {field}: {choice}")

        if not found_any:
            if entity_id:
                typer.echo(f"No Jira sync overrides found for {entity_id}")
            else:
                typer.echo("No Jira sync overrides found in any entity")

    except MoucError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
