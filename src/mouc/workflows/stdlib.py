"""Standard library of workflow factories for Mouc.

These workflows are bundled with mouc but must be explicitly enabled via config:

    workflows:
      stdlib: true

Each workflow expands a single entity by adding phase entities. The parent
entity is preserved as the main work task (typically implementation).
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

    # Merge metadata, but exclude phase-specific fields from parent
    # (effort and resources should come from defaults/overrides, not parent)
    parent_meta_filtered = {
        k: v for k, v in parent.meta.items() if k not in ("effort", "resources")
    }
    merged_meta = _merge_meta(parent_meta_filtered, override.get("meta"), defaults)

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


def design_impl(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into: design (floats) -> [signoff lag] -> parent (impl).

    The design phase floats freely (no requires). The parent entity becomes
    the implementation phase, requiring design + signoff_lag in addition to
    its original requires.

    Default values (can be overridden in config or per-entity phases):
    - design_effort: "3d"
    - signoff_lag: "1w"

    Phase keys: design
    """
    signoff_lag = defaults.get("signoff_lag", "1w")

    # Check for phase-level lag override on parent (impl)
    if phase_overrides:
        impl_override = phase_overrides.get("impl", {})
        impl_meta = impl_override.get("meta", {})
        if "lag" in impl_meta:
            signoff_lag = impl_meta["lag"]

    # Create design phase (floats - no requires)
    design = _create_phase_entity(
        parent=entity,
        phase_key="design",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("design_effort", "3d")},
        name_suffix="Design",
    )
    # design.requires stays empty - it floats

    # Parent entity becomes impl, add design dependency to its existing requires
    parent = deepcopy(entity)
    parent.requires = entity.requires | {Dependency.parse(f"{design.id} + {signoff_lag}")}

    return [design, parent]


def impl_pr(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into: parent (impl) -> [review lag] -> pr.

    The parent entity is the implementation phase. A PR phase is added
    that requires the parent + review_lag.

    Default values (can be overridden in config or per-entity phases):
    - pr_effort: "2d"
    - review_lag: "3d"

    Phase keys: pr
    """
    review_lag = defaults.get("review_lag", "3d")

    # Check for phase-level lag override
    if phase_overrides:
        pr_override = phase_overrides.get("pr", {})
        pr_meta = pr_override.get("meta", {})
        if "lag" in pr_meta:
            review_lag = pr_meta["lag"]

    # Parent entity stays as impl (unchanged)
    parent = deepcopy(entity)

    # Create PR phase that requires parent
    pr = _create_phase_entity(
        parent=entity,
        phase_key="pr",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("pr_effort", "2d")},
        name_suffix="PR Review",
    )
    pr.requires = {Dependency.parse(f"{entity.id} + {review_lag}")}
    pr.enables = entity.enables  # PR phase takes over parent's enables

    # Parent no longer enables downstream - PR does
    parent.enables = set()

    return [parent, pr]


def full(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into: design (floats) -> [signoff] -> parent (impl) -> [review] -> pr.

    The design phase floats freely. The parent entity becomes the implementation
    phase, requiring design + signoff_lag AND its original requires. The PR phase
    requires the parent + review_lag and takes over the parent's enables.

    Default values (can be overridden in config or per-entity phases):
    - design_effort: "3d"
    - signoff_lag: "1w"
    - pr_effort: "2d"
    - review_lag: "3d"

    Phase keys: design, pr
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

    # Create design phase (floats - no requires)
    design = _create_phase_entity(
        parent=entity,
        phase_key="design",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("design_effort", "3d")},
        name_suffix="Design",
    )
    # design.requires stays empty - it floats

    # Parent entity becomes impl, add design dependency to its existing requires
    parent = deepcopy(entity)
    parent.requires = entity.requires | {Dependency.parse(f"{design.id} + {signoff_lag}")}
    parent.enables = set()  # PR takes over enables

    # Create PR phase that requires parent
    pr = _create_phase_entity(
        parent=entity,
        phase_key="pr",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("pr_effort", "2d")},
        name_suffix="PR Review",
    )
    pr.requires = {Dependency.parse(f"{entity.id} + {review_lag}")}
    pr.enables = entity.enables  # PR phase takes over parent's enables

    return [design, parent, pr]


def phased_rollout(
    entity: Entity,
    defaults: dict[str, Any],
    phase_overrides: dict[str, Any] | None,
) -> list[Entity]:
    """Expand entity into: parent (impl) -> canary -> [bake] -> rollout.

    The parent entity is the implementation phase. Canary and rollout phases
    are added after it. The rollout phase takes over the parent's enables.

    Default values (can be overridden in config or per-entity phases):
    - canary_effort: "1d"
    - bake_time: "1w"
    - rollout_effort: "1d"

    Phase keys: canary, rollout
    """
    bake_time = defaults.get("bake_time", "1w")

    # Check for phase-level lag override
    if phase_overrides:
        rollout_override = phase_overrides.get("rollout", {})
        rollout_meta = rollout_override.get("meta", {})
        if "lag" in rollout_meta:
            bake_time = rollout_meta["lag"]

    # Parent entity stays as impl
    parent = deepcopy(entity)
    parent.enables = set()  # Rollout takes over enables

    # Create canary phase that requires parent
    canary = _create_phase_entity(
        parent=entity,
        phase_key="canary",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("canary_effort", "1d")},
        name_suffix="Canary Deploy",
    )
    canary.requires = {Dependency(entity_id=entity.id)}

    # Create rollout phase
    rollout = _create_phase_entity(
        parent=entity,
        phase_key="rollout",
        phase_overrides=phase_overrides,
        defaults={"effort": defaults.get("rollout_effort", "1d")},
        name_suffix="Full Rollout",
    )
    rollout.requires = {Dependency.parse(f"{canary.id} + {bake_time}")}
    rollout.enables = entity.enables  # Rollout takes over parent's enables

    return [parent, canary, rollout]
