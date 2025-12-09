"""Pre-processor factory and exports."""

from typing import Any

from ..config import PreProcessorType
from .backward_pass import BackwardPassPreProcessor


def create_preprocessor(
    preprocessor_type: PreProcessorType,
    config: dict[str, Any] | None = None,
) -> BackwardPassPreProcessor | None:
    """Create a pre-processor instance based on type.

    Args:
        preprocessor_type: Type of pre-processor to create
        config: Optional config dict to pass to preprocessor

    Returns:
        PreProcessor instance or None if type is NONE
    """
    if preprocessor_type == PreProcessorType.NONE:
        return None

    if preprocessor_type == PreProcessorType.BACKWARD_PASS:
        return BackwardPassPreProcessor(config=config)

    msg = f"Unknown preprocessor type: {preprocessor_type}"
    raise ValueError(msg)


__all__ = ["BackwardPassPreProcessor", "create_preprocessor"]
