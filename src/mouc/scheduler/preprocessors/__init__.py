"""Pre-processor factory and exports."""

from ..config import PreProcessorType
from .backward_pass import BackwardPassPreProcessor


def create_preprocessor(preprocessor_type: PreProcessorType) -> BackwardPassPreProcessor | None:
    """Create a pre-processor instance based on type.

    Args:
        preprocessor_type: Type of pre-processor to create

    Returns:
        PreProcessor instance or None if type is NONE
    """
    if preprocessor_type == PreProcessorType.NONE:
        return None

    if preprocessor_type == PreProcessorType.BACKWARD_PASS:
        return BackwardPassPreProcessor()

    msg = f"Unknown preprocessor type: {preprocessor_type}"
    raise ValueError(msg)


__all__ = ["BackwardPassPreProcessor", "create_preprocessor"]
