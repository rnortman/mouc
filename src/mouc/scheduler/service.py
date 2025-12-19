"""High-level scheduling service."""

from datetime import date
from typing import TYPE_CHECKING

from .algorithms import create_algorithm
from .config import AlgorithmType, PreProcessorType, SchedulingConfig
from .core import ScheduleAnnotations, SchedulingResult
from .preprocessors import create_preprocessor
from .validator import SchedulerInputValidator

if TYPE_CHECKING:
    from mouc.models import FeatureMap
    from mouc.resources import DNSPeriod, ResourceConfig

    from .lock import ScheduleLock


class SchedulingService:
    """High-level service for scheduling entities and creating annotations.

    This service coordinates:
    - SchedulerInputValidator (entity-to-task conversion)
    - PreProcessor (backward pass for deadline/priority propagation)
    - SchedulingAlgorithm (forward scheduling)

    To provide a complete scheduling solution with annotations.
    """

    def __init__(  # noqa: PLR0913 - needs multiple optional config params
        self,
        feature_map: "FeatureMap",
        current_date: date | None = None,
        resource_config: "ResourceConfig | None" = None,
        config: SchedulingConfig | None = None,
        global_dns_periods: "list[DNSPeriod] | None" = None,
        schedule_lock: "ScheduleLock | None" = None,
    ):
        """Initialize scheduling service.

        Args:
            feature_map: Feature map to schedule
            current_date: Current date for scheduling (defaults to today)
            resource_config: Optional resource configuration
            config: Optional scheduling configuration for prioritization strategy
            global_dns_periods: Optional global DNS periods that apply to all resources
            schedule_lock: Optional lock file with fixed dates/resources from previous run
        """
        self.feature_map = feature_map
        self.current_date = current_date or date.today()  # noqa: DTZ011
        self.resource_config = resource_config
        self.config = config or SchedulingConfig()
        self.global_dns_periods = global_dns_periods or []
        self.schedule_lock = schedule_lock
        self.validator = SchedulerInputValidator(resource_config, self.config)

    def _resolve_preprocessor_type(self) -> PreProcessorType:
        """Resolve auto preprocessor type based on algorithm."""
        preprocessor_type = self.config.preprocessor.type
        if preprocessor_type == PreProcessorType.AUTO:
            # CP-SAT is a global optimizer that doesn't need backward pass
            if self.config.algorithm.type == AlgorithmType.CP_SAT:
                return PreProcessorType.NONE
            return PreProcessorType.BACKWARD_PASS
        return preprocessor_type

    def schedule(self) -> SchedulingResult:  # noqa: PLR0912, PLR0915 - complex scheduling logic
        """Schedule all entities and create annotations.

        Returns:
            SchedulingResult with tasks, annotations, and warnings
        """
        # Extract tasks from feature map
        tasks, done_without_dates, resources_computed_map = self.validator.extract_tasks(
            self.feature_map
        )

        # Apply schedule locks to fix dates and resources
        if self.schedule_lock:
            for task in tasks:
                if task.id in self.schedule_lock.locks:
                    lock = self.schedule_lock.locks[task.id]
                    task.start_on = lock.start_date
                    task.end_on = lock.end_date
                    task.resources = lock.resources
                    task.resource_spec = None  # Disable auto-assignment for locked tasks

        # Run pre-processor if configured
        preprocess_result = None
        preprocessor_type = self._resolve_preprocessor_type()
        preprocessor_config = {"default_priority": self.config.default_priority}
        preprocessor = create_preprocessor(preprocessor_type, preprocessor_config)
        if preprocessor:
            preprocess_result = preprocessor.process(tasks, done_without_dates)

        # Create and run the scheduling algorithm
        algorithm = create_algorithm(
            self.config.algorithm.type,
            tasks,
            self.current_date,
            resource_config=self.resource_config,
            completed_task_ids=done_without_dates,
            config=self.config,
            global_dns_periods=self.global_dns_periods,
            preprocess_result=preprocess_result,
        )

        try:
            algorithm_result = algorithm.schedule()
            scheduled_tasks = algorithm_result.scheduled_tasks

            # Get computed values from algorithm (may be from preprocess)
            computed_deadlines = algorithm.get_computed_deadlines()
            computed_priorities = algorithm.get_computed_priorities()
        except ValueError as e:
            # Scheduling failed
            return SchedulingResult(
                scheduled_tasks=[],
                annotations={},
                warnings=[f"Scheduling failed: {e}"],
            )

        # Create annotations for each entity
        annotations: dict[str, ScheduleAnnotations] = {}
        scheduled_by_id = {task.task_id: task for task in scheduled_tasks}
        task_by_id = {task.id: task for task in tasks}

        for entity in self.feature_map.entities:
            entity_id = entity.id

            # Skip entities done without dates
            if entity_id in done_without_dates:
                continue

            # Get task info
            task = task_by_id.get(entity_id)
            if not task:
                continue

            scheduled = scheduled_by_id.get(entity_id)
            if not scheduled:
                continue

            # Determine annotation values - use lock file values if available
            if self.schedule_lock and entity_id in self.schedule_lock.locks:
                lock = self.schedule_lock.locks[entity_id]
                was_fixed = lock.was_fixed
                resources_were_computed = lock.resources_were_computed
            else:
                was_fixed = task.start_on is not None or task.end_on is not None
                resources_were_computed = resources_computed_map.get(entity_id, False)

            computed_deadline = computed_deadlines.get(entity_id)
            computed_priority = computed_priorities.get(entity_id)

            deadline_violated = False
            if computed_deadline and scheduled.end_date > computed_deadline:
                deadline_violated = True

            resource_assignments = [(r, 1.0) for r in scheduled.resources]

            annotations[entity_id] = ScheduleAnnotations(
                estimated_start=scheduled.start_date,
                estimated_end=scheduled.end_date,
                computed_deadline=computed_deadline,
                computed_priority=computed_priority,
                deadline_violated=deadline_violated,
                resource_assignments=resource_assignments,
                resources_were_computed=resources_were_computed,
                was_fixed=was_fixed,
            )

        # Generate warnings
        warnings: list[str] = []
        for entity_id in done_without_dates:
            warnings.append(
                f"Task '{entity_id}' marked done without dates - excluded from schedule"
            )

        for entity_id, annot in annotations.items():
            if annot.deadline_violated and annot.computed_deadline and annot.estimated_end:
                days_late = (annot.estimated_end - annot.computed_deadline).days
                warnings.append(
                    f"Entity '{entity_id}' finishes {days_late} days after required date "
                    f"({annot.estimated_end} vs {annot.computed_deadline})"
                )

        return SchedulingResult(
            scheduled_tasks=scheduled_tasks,
            annotations=annotations,
            warnings=warnings,
        )

    def populate_feature_map_annotations(self) -> None:
        """Run scheduling and populate entity.annotations['schedule'] in feature map."""
        result = self.schedule()
        for entity in self.feature_map.entities:
            if entity.id in result.annotations:
                entity.annotations["schedule"] = result.annotations[entity.id]
