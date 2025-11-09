"""Global application context and state management."""

from __future__ import annotations

from pathlib import Path


class _Context:
    """Application context for managing global state."""

    def __init__(self) -> None:
        self.verbosity_level: int = 0
        self.config_path: Path | None = None


# Singleton instance
_context = _Context()


def get_verbosity() -> int:
    """Get the current verbosity level."""
    return _context.verbosity_level


def set_verbosity(level: int) -> None:
    """Set the current verbosity level."""
    _context.verbosity_level = level


def get_config_path() -> Path | None:
    """Get the global config path."""
    return _context.config_path


def set_config_path(path: Path | None) -> None:
    """Set the global config path."""
    _context.config_path = path
