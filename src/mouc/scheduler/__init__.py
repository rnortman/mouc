"""Scheduler package - resource-constrained project scheduling.

This package provides a pluggable scheduling system with:
- Configurable algorithms (Parallel SGS, future: bounded rollout, constraint solvers)
- Configurable pre-processors (backward pass for deadline/priority propagation)
- High-level SchedulingService for entity-based scheduling

Main entry points:
- SchedulingService: High-level service for scheduling FeatureMap entities
- SchedulerInputValidator: Convert entities to Tasks
- ParallelScheduler: Low-level Parallel SGS algorithm

Configuration:
- SchedulingConfig: Main configuration (strategy, algorithm, preprocessor)
- AlgorithmConfig: Algorithm selection
- PreProcessorConfig: Pre-processor selection
"""

# Core dataclasses
# Algorithms
from .algorithms import BoundedRolloutScheduler, ParallelScheduler, create_algorithm

# Configuration
from .config import (
    AlgorithmConfig,
    AlgorithmType,
    ImplementationType,
    PreProcessorConfig,
    PreProcessorType,
    RolloutConfig,
    SchedulingConfig,
    TimeframeConstraintMode,
)
from .core import (
    AlgorithmResult,
    PreProcessResult,
    ScheduleAnnotations,
    ScheduledTask,
    SchedulingResult,
    Task,
)

# Pre-processors
from .preprocessors import BackwardPassPreProcessor, create_preprocessor

# Protocols
from .protocols import PreProcessor, SchedulingAlgorithm

# Resource scheduling utilities
from .resources import ResourceSchedule

# High-level service
from .service import SchedulingService

# Timeframe parsing
from .timeframes import parse_timeframe

# Input validation
from .validator import SchedulerInputValidator

__all__ = [
    # Core dataclasses
    "Task",
    "ScheduledTask",
    "ScheduleAnnotations",
    "SchedulingResult",
    "AlgorithmResult",
    "PreProcessResult",
    # Configuration
    "SchedulingConfig",
    "AlgorithmConfig",
    "AlgorithmType",
    "ImplementationType",
    "PreProcessorConfig",
    "PreProcessorType",
    "RolloutConfig",
    "TimeframeConstraintMode",
    # Protocols
    "PreProcessor",
    "SchedulingAlgorithm",
    # High-level service
    "SchedulingService",
    # Input validation
    "SchedulerInputValidator",
    # Resource utilities
    "ResourceSchedule",
    # Timeframe parsing
    "parse_timeframe",
    # Algorithms
    "ParallelScheduler",
    "BoundedRolloutScheduler",
    "create_algorithm",
    # Pre-processors
    "BackwardPassPreProcessor",
    "create_preprocessor",
]
