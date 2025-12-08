"""Configuration classes for the scheduling system."""

from enum import Enum

from pydantic import BaseModel


class AlgorithmType(str, Enum):
    """Available scheduling algorithms."""

    PARALLEL_SGS = "parallel_sgs"
    # Future algorithms:
    # BOUNDED_ROLLOUT = "bounded_rollout"
    # OR_TOOLS = "or_tools"
    # TABU_SEARCH = "tabu_search"


class PreProcessorType(str, Enum):
    """Available pre-processors."""

    BACKWARD_PASS = "backward_pass"
    NONE = "none"


class AlgorithmConfig(BaseModel):
    """Configuration for algorithm selection."""

    type: AlgorithmType = AlgorithmType.PARALLEL_SGS


class PreProcessorConfig(BaseModel):
    """Configuration for pre-processor selection."""

    type: PreProcessorType = PreProcessorType.BACKWARD_PASS


class SchedulingConfig(BaseModel):
    """Configuration for task prioritization and algorithm selection."""

    # Prioritization strategy
    strategy: str = "weighted"  # "priority_first" | "cr_first" | "weighted"
    cr_weight: float = 10.0
    priority_weight: float = 1.0
    default_cr: float | str = "median"

    # Algorithm and pre-processor selection
    algorithm: AlgorithmConfig = AlgorithmConfig()
    preprocessor: PreProcessorConfig = PreProcessorConfig()
