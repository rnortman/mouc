"""Logging configuration for Mouc with custom verbosity levels."""

from __future__ import annotations

import logging
import sys
from typing import Any, TextIO

# Define custom levels between standard logging levels
CHANGES_LEVEL = 25  # Between INFO (20) and WARNING (30) - for verbosity level 1
CHECKS_LEVEL = 15  # Between DEBUG (10) and INFO (20) - for verbosity level 2

logging.addLevelName(CHANGES_LEVEL, "CHANGES")
logging.addLevelName(CHECKS_LEVEL, "CHECKS")

# Verbosity level constants for external use
VERBOSITY_SILENT = 0  # Only errors
VERBOSITY_CHANGES = 1  # Show changes/assignments
VERBOSITY_CHECKS = 2  # Show all checks
VERBOSITY_DEBUG = 3  # Full debug output


class MoucLogger(logging.Logger):
    """Custom logger with semantic verbosity methods.

    Provides methods that correspond to verbosity levels:
    - changes(): verbosity level 1 - show changes/assignments
    - checks(): verbosity level 2 - show task consideration and checks
    - debug(): verbosity level 3 - full algorithm details
    """

    def changes(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log changes (verbosity level 1)."""
        if self.isEnabledFor(CHANGES_LEVEL):
            self._log(CHANGES_LEVEL, msg, args, **kwargs)

    def checks(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log checks (verbosity level 2)."""
        if self.isEnabledFor(CHECKS_LEVEL):
            self._log(CHECKS_LEVEL, msg, args, **kwargs)


def get_logger() -> MoucLogger:
    """Get the mouc logger instance (singleton).

    Returns the same logger instance on every call. Use setup_logger()
    to configure it before first use.

    Returns:
        The mouc logger singleton instance
    """
    logging.setLoggerClass(MoucLogger)
    logger = logging.getLogger("mouc")
    assert isinstance(logger, MoucLogger)
    return logger


def setup_logger(verbosity: int, stream: TextIO | None = None) -> None:
    """Configure the mouc logger with verbosity level.

    Can be called multiple times to reconfigure the logger.

    Args:
        verbosity: 0=silent (errors only), 1=changes, 2=checks, 3=debug
        stream: Optional output stream (defaults to sys.stderr, useful for testing)
    """
    logger = get_logger()

    # Clear existing handlers
    logger.handlers.clear()

    # Map verbosity to logging levels
    level_map = {
        0: logging.ERROR,  # Silent - only actual errors
        1: CHANGES_LEVEL,  # Show changes and assignments
        2: CHECKS_LEVEL,  # Show task consideration and checks
        3: logging.DEBUG,  # Full debug output
    }
    logger.setLevel(level_map.get(verbosity, logging.ERROR))

    # Use provided stream or default to stderr
    output_stream = stream if stream is not None else sys.stderr

    # Handler with clean formatting (no level prefix)
    handler = logging.StreamHandler(output_stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


def reset_logger() -> None:
    """Reset the logger to clean state.

    Useful for testing to ensure clean state between tests.
    """
    logger = get_logger()
    logger.handlers.clear()
    logger.setLevel(logging.ERROR)


def is_silent() -> bool:
    """Check if logger is in silent mode (verbosity == 0).

    Returns:
        True if logger is in silent mode (only errors)
    """
    return get_logger().level >= logging.ERROR


def changes_enabled() -> bool:
    """Check if changes-level logging is enabled (verbosity >= 1).

    Returns:
        True if logger will output changes messages
    """
    return get_logger().isEnabledFor(CHANGES_LEVEL)


def checks_enabled() -> bool:
    """Check if checks-level logging is enabled (verbosity >= 2).

    Returns:
        True if logger will output checks messages
    """
    return get_logger().isEnabledFor(CHECKS_LEVEL)


def debug_enabled() -> bool:
    """Check if debug-level logging is enabled (verbosity >= 3).

    Returns:
        True if logger will output debug messages
    """
    return get_logger().isEnabledFor(logging.DEBUG)
