"""Pytest configuration and fixtures for mouc tests."""

from mouc.models import Dependency


def deps(*entity_ids: str) -> set[Dependency]:
    """Create a set of Dependency objects from entity ID strings.

    This is a helper function for tests to easily create dependencies
    without having to import Dependency and construct objects manually.

    Example:
        Entity(..., requires=deps("cap1", "cap2"))
    """
    return {Dependency(entity_id=eid) for eid in entity_ids}


def dep_list(*entity_ids: str) -> list[Dependency]:
    """Create a list of Dependency objects from entity ID strings.

    This is a helper function for tests to easily create dependencies for Task objects.

    Example:
        Task(..., dependencies=dep_list("task_a", "task_b"))
    """
    return [Dependency(entity_id=eid) for eid in entity_ids]
