"""Global application context and state management."""

from __future__ import annotations

from pathlib import Path

# Global state
_verbosity_level: int = 0
_config_path: Path | None = None


def get_verbosity() -> int:
    """Get the current verbosity level."""
    return _verbosity_level


def set_verbosity(level: int) -> None:
    """Set the current verbosity level."""
    global _verbosity_level
    _verbosity_level = level


def get_config_path() -> Path | None:
    """Get the global config path."""
    return _config_path


def set_config_path(path: Path | None) -> None:
    """Set the global config path."""
    global _config_path
    _config_path = path
