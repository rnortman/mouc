"""Standard library of workflow factories for Mouc.

These workflows are bundled with mouc but must be explicitly enabled via config:

    workflows:
      stdlib: true

Each workflow expands a single entity into multiple phase entities while
preserving the original entity ID as a milestone/summary entity.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from mouc.models import Dependency, Entity

# List of workflow names exported by stdlib
STDLIB_WORKFLOWS = [
    "design_impl",
    "impl_pr",
    "full",
    "phased_rollout",
]


def _merge_meta(
    parent_meta: dict[str, Any],
    override_meta: dict[str, Any] | None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge metadata: defaults < parent < override."""
    result = deepcopy(defaults or {})
    result.update(deepcopy(parent_meta))
    if override_meta:
        result.update(deepcopy(override_meta))
    return result


def _get_phase_override(
    phase_overrides: dict[str, Any] | None,
    phase_key: str,
) -> dict[str, Any]:
    """Get override dict for a phase, or empty dict if not specified."""
    if phase_overrides is None:
        return {}
    return phase_overrides.get(phase_key, {})


def _create_phase_entity(  # noqa: PLR0913 - many optional params for flexibility
    parent: Entity,
    phase_key: str,
    phase_overrides: dict[str, Any] | None,
    defaults: dict[str, Any] | None = None,
    name_suffix: str | None = None,
    extra_tags: list[str] | None = None,
) -> Entity:
    """Create a phase entity from parent with overrides applied."""
    override = _get_phase_override(phase_overrides, phase_key)

    # Merge metadata
    merged_meta = _merge_meta(parent.meta, override.get("meta"), defaults)

    # Build name
    name = override.get("name", f"{parent.name} - {name_suffix or phase_key.title()}")

    # Build tags: parent tags + phase tag + override tags + extra tags
    tags = list(parent.tags)
    tags.append(f"phase:{phase_key}")
    tags.extend(override.get("tags", []))
    if extra_tags:
        tags.extend(extra_tags)

    return Entity(
        type=parent.type,
        id=f"{parent.id}_{phase_key}",
        name=name,
        description=override.get("description", parent.description),
        requires=set(),  # Will be set by workflow
        enables=set(),  # Will be set by workflow
        links=override.get("links", []),
        tags=tags,
        meta=merged_meta,
        phase_of=(parent.id, phase_key),  # Track parent for Jira sync write-back
    )


def _create_milestone_entity(
    parent: Entity,
    requires_phase_id: str,
) -> Entity:
    """Create a milestone entity with 0d effort that requires a phase."""
    meta = deepcopy(parent.meta)
    meta["effort"] = "0d"

    return Entity(
        type=parent.type,
        id=parent.id,  # Same ID as parent
        name=parent.name,
        description=parent.description,
        requires={Dependency(entity_id=requires_phase_id)},
        enables=parent.enables,  # Inherit parent's enables
        links=parent.links,
        tags=[*parent.tags, "phase:milestone"],
        meta=meta,
    )


def design_impl(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into: design -> [signoff lag] -> impl -> milestone.

    Default values (can be overridden in config or per-entity phases):
    - design_effort: "3d"
    - signoff_lag: "1w"

    Phase keys: design, impl
    """
    signoff_lag = defaults.get("signoff_lag", "1w")

    # Check for phase-level lag override
    if phase_overrides:
        impl_override = phase_overrides.get("impl", {})
        impl_meta = impl_override.get("meta", {})
        if "lag" in impl_meta:
            signoff_lag = impl_meta["lag"]

    # Create design phase
    design = _create_phase_entity(
        parent=entity,
        phase_key="design",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("design_effort", "3d")},
        name_suffix="Design",
    )
    design.requires = entity.requires  # Inherit parent's requires

    # Create impl phase
    impl = _create_phase_entity(
        parent=entity,
        phase_key="impl",
        phase_overrides=phase_overrides,
        name_suffix="Implementation",
    )
    impl.requires = {Dependency.parse(f"{design.id} + {signoff_lag}")}

    # Create milestone (same ID as parent)
    milestone = _create_milestone_entity(entity, impl.id)

    return [design, impl, milestone]


def impl_pr(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into: impl -> [review lag] -> pr -> milestone.

    Default values (can be overridden in config or per-entity phases):
    - pr_effort: "2d"
    - review_lag: "3d"

    Phase keys: impl, pr
    """
    review_lag = defaults.get("review_lag", "3d")

    # Check for phase-level lag override
    if phase_overrides:
        pr_override = phase_overrides.get("pr", {})
        pr_meta = pr_override.get("meta", {})
        if "lag" in pr_meta:
            review_lag = pr_meta["lag"]

    # Create impl phase
    impl = _create_phase_entity(
        parent=entity,
        phase_key="impl",
        phase_overrides=phase_overrides,
        name_suffix="Implementation",
    )
    impl.requires = entity.requires  # Inherit parent's requires

    # Create PR phase
    pr = _create_phase_entity(
        parent=entity,
        phase_key="pr",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("pr_effort", "2d")},
        name_suffix="PR Review",
    )
    pr.requires = {Dependency.parse(f"{impl.id} + {review_lag}")}

    # Create milestone
    milestone = _create_milestone_entity(entity, pr.id)

    return [impl, pr, milestone]


def full(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into: design -> signoff -> impl -> review -> pr -> milestone.

    Default values (can be overridden in config or per-entity phases):
    - design_effort: "3d"
    - signoff_lag: "1w"
    - pr_effort: "2d"
    - review_lag: "3d"

    Phase keys: design, impl, pr
    """
    signoff_lag = defaults.get("signoff_lag", "1w")
    review_lag = defaults.get("review_lag", "3d")

    # Check for phase-level lag overrides
    if phase_overrides:
        impl_override = phase_overrides.get("impl", {})
        impl_meta = impl_override.get("meta", {})
        if "lag" in impl_meta:
            signoff_lag = impl_meta["lag"]

        pr_override = phase_overrides.get("pr", {})
        pr_meta = pr_override.get("meta", {})
        if "lag" in pr_meta:
            review_lag = pr_meta["lag"]

    # Create design phase
    design = _create_phase_entity(
        parent=entity,
        phase_key="design",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("design_effort", "3d")},
        name_suffix="Design",
    )
    design.requires = entity.requires  # Inherit parent's requires

    # Create impl phase
    impl = _create_phase_entity(
        parent=entity,
        phase_key="impl",
        phase_overrides=phase_overrides,
        name_suffix="Implementation",
    )
    impl.requires = {Dependency.parse(f"{design.id} + {signoff_lag}")}

    # Create PR phase
    pr = _create_phase_entity(
        parent=entity,
        phase_key="pr",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("pr_effort", "2d")},
        name_suffix="PR Review",
    )
    pr.requires = {Dependency.parse(f"{impl.id} + {review_lag}")}

    # Create milestone
    milestone = _create_milestone_entity(entity, pr.id)

    return [design, impl, pr, milestone]


def phased_rollout(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into: impl -> canary -> [bake] -> rollout -> milestone.

    Default values (can be overridden in config or per-entity phases):
    - canary_effort: "1d"
    - bake_time: "1w"
    - rollout_effort: "1d"

    Phase keys: impl, canary, rollout
    """
    bake_time = defaults.get("bake_time", "1w")

    # Check for phase-level lag override
    if phase_overrides:
        rollout_override = phase_overrides.get("rollout", {})
        rollout_meta = rollout_override.get("meta", {})
        if "lag" in rollout_meta:
            bake_time = rollout_meta["lag"]

    # Create impl phase
    impl = _create_phase_entity(
        parent=entity,
        phase_key="impl",
        phase_overrides=phase_overrides,
        name_suffix="Implementation",
    )
    impl.requires = entity.requires  # Inherit parent's requires

    # Create canary phase
    canary = _create_phase_entity(
        parent=entity,
        phase_key="canary",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("canary_effort", "1d")},
        name_suffix="Canary Deploy",
    )
    canary.requires = {Dependency(entity_id=impl.id)}

    # Create rollout phase
    rollout = _create_phase_entity(
        parent=entity,
        phase_key="rollout",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("rollout_effort", "1d")},
        name_suffix="Full Rollout",
    )
    rollout.requires = {Dependency.parse(f"{canary.id} + {bake_time}")}

    # Create milestone
    milestone = _create_milestone_entity(entity, rollout.id)

    return [impl, canary, rollout, milestone]
