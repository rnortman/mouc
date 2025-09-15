"""Custom exceptions for Mouc."""


class MoucError(Exception):
    """Base exception for all Mouc errors."""

    pass


class ValidationError(MoucError):
    """Raised when validation fails."""

    pass


class CircularDependencyError(ValidationError):
    """Raised when a circular dependency is detected."""

    pass


class MissingReferenceError(ValidationError):
    """Raised when a referenced ID does not exist."""

    pass


class ParseError(MoucError):
    """Raised when YAML parsing fails."""

    pass
