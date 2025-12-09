"""Configuration classes for the scheduling system."""

from enum import Enum

from pydantic import BaseModel


class AlgorithmType(str, Enum):
    """Available scheduling algorithms."""

    PARALLEL_SGS = "parallel_sgs"
    BOUNDED_ROLLOUT = "bounded_rollout"
    # Future algorithms:
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


class RolloutConfig(BaseModel):
    """Configuration for bounded rollout algorithm."""

    # Priority threshold: only trigger rollout for tasks below this priority
    priority_threshold: int = 70
    # Minimum priority difference to consider rollout worthwhile
    min_priority_gap: int = 20
    # CR threshold: only trigger rollout for tasks with CR above this (relaxed tasks)
    cr_relaxed_threshold: float = 5.0
    # Minimum CR gap: upcoming task must have CR at least this much lower (more urgent)
    min_cr_urgency_gap: float = 3.0


class SchedulingConfig(BaseModel):
    """Configuration for task prioritization and algorithm selection."""

    # Prioritization strategy
    strategy: str = "weighted"  # "priority_first" | "cr_first" | "weighted"
    cr_weight: float = 10.0
    priority_weight: float = 1.0

    # Default values for tasks without explicit priority/deadline
    default_priority: int = 50  # Priority for tasks without explicit priority (0-100)
    default_cr_multiplier: float = 2.0  # Multiplier for computing default CR (max_cr * multiplier)
    default_cr_floor: float = 10.0  # Minimum CR for tasks without deadlines

    # Algorithm and pre-processor selection
    algorithm: AlgorithmConfig = AlgorithmConfig()
    preprocessor: PreProcessorConfig = PreProcessorConfig()

    # Bounded rollout configuration
    rollout: RolloutConfig = RolloutConfig()
