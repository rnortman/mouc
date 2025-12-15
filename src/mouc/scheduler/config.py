"""Configuration classes for the scheduling system."""

from enum import Enum

from pydantic import BaseModel


class TimeframeConstraintMode(str, Enum):
    """How timeframe metadata creates scheduling constraints."""

    BOTH = "both"  # Sets both start_after and end_before
    START = "start"  # Only sets start_after
    END = "end"  # Only sets end_before
    NONE = "none"  # No constraints from timeframe


class AlgorithmType(str, Enum):
    """Available scheduling algorithms."""

    PARALLEL_SGS = "parallel_sgs"
    BOUNDED_ROLLOUT = "bounded_rollout"
    CP_SAT = "cpsat"


class PreProcessorType(str, Enum):
    """Available pre-processors."""

    AUTO = "auto"  # backward_pass for greedy algorithms, none for cpsat
    BACKWARD_PASS = "backward_pass"
    NONE = "none"


class AlgorithmConfig(BaseModel):
    """Configuration for algorithm selection."""

    type: AlgorithmType = AlgorithmType.PARALLEL_SGS


class PreProcessorConfig(BaseModel):
    """Configuration for pre-processor selection."""

    type: PreProcessorType = PreProcessorType.AUTO


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
    # Maximum rollout horizon in days (limits simulation depth for performance)
    max_horizon_days: int | None = 30


class CPSATConfig(BaseModel):
    """Configuration for CP-SAT optimal scheduler."""

    time_limit_seconds: float | None = 30.0  # None = no limit (run until optimal)
    tardiness_weight: float = 100.0  # Penalty for deadline violations
    priority_weight: float = 1.0  # Weight for priority-based completion time
    earliness_weight: float = 0.0  # Reward for slack before deadlines (0 = disabled)
    random_seed: int = 42
    use_greedy_hints: bool = True  # Run greedy scheduler to seed CP-SAT with hints
    warn_on_incomplete_hints: bool = True  # Warn if greedy hints are incomplete/rejected
    log_solver_progress: bool = False  # Log solver progress at debug verbosity


class SchedulingConfig(BaseModel):
    """Configuration for task prioritization and algorithm selection."""

    # Timeframe constraint behavior
    auto_constraint_from_timeframe: TimeframeConstraintMode = TimeframeConstraintMode.BOTH

    # Prioritization strategy
    strategy: str = "weighted"  # "priority_first" | "cr_first" | "weighted" | "atc"
    cr_weight: float = 10.0
    priority_weight: float = 1.0

    # Default values for tasks without explicit priority/deadline
    default_priority: int = 50  # Priority for tasks without explicit priority (0-100)
    default_cr_multiplier: float = 2.0  # Multiplier for computing default CR (max_cr * multiplier)
    default_cr_floor: float = 10.0  # Minimum CR for tasks without deadlines

    # ATC (Apparent Tardiness Cost) strategy parameters
    atc_k: float = 2.0  # Lookahead parameter (1.5-3.0 typical)
    atc_default_urgency_multiplier: float = 1.0  # Multiplier for default urgency
    atc_default_urgency_floor: float = 0.3  # Minimum urgency for no-deadline tasks

    # Algorithm and pre-processor selection
    algorithm: AlgorithmConfig = AlgorithmConfig()
    preprocessor: PreProcessorConfig = PreProcessorConfig()

    # Bounded rollout configuration
    rollout: RolloutConfig = RolloutConfig()

    # CP-SAT configuration
    cpsat: CPSATConfig = CPSATConfig()
