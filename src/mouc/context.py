"""Global application context and state management."""

from __future__ import annotations

from pathlib import Path


class _Context:
    """Application context for managing global state."""

    def __init__(self) -> None:
        self.config_path: Path | None = None


# Singleton instance
_context = _Context()


def get_config_path() -> Path | None:
    """Get the global config path."""
    return _context.config_path


def set_config_path(path: Path | None) -> None:
    """Set the global config path."""
    _context.config_path = path
