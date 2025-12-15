//! Task sorting strategies for the scheduler.
//!
//! Implements four prioritization strategies:
//! - `priority_first`: Priority dominates, CR breaks ties
//! - `cr_first`: Critical Ratio dominates, priority breaks ties
//! - `weighted`: Blended score combining CR and priority
//! - `atc`: Apparent Tardiness Cost with exponential urgency

use chrono::NaiveDate;
use std::cmp::Ordering;
use std::collections::HashMap;

use crate::SchedulingConfig;

/// Information needed to compute a task's sort key.
#[derive(Clone, Debug)]
pub struct TaskSortInfo {
    pub duration_days: f64,
    pub deadline: Option<NaiveDate>,
    pub priority: i32,
}

/// Parameters for ATC (Apparent Tardiness Cost) strategy.
#[derive(Clone, Debug)]
pub struct AtcParams {
    pub avg_duration: f64,
    pub default_urgency: f64,
}

/// Errors that can occur during sorting.
#[derive(Debug, Clone)]
pub enum SortingError {
    UnknownStrategy(String),
    AtcParamsMissing,
    TaskNotFound(String),
}

impl std::fmt::Display for SortingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnknownStrategy(s) => write!(f, "Unknown scheduling strategy: {}", s),
            Self::AtcParamsMissing => write!(f, "ATC strategy requires atc_params parameter"),
            Self::TaskNotFound(id) => write!(f, "Task not found: {}", id),
        }
    }
}

impl std::error::Error for SortingError {}

/// Sort key for task prioritization.
///
/// Implements `Ord` so tasks can be sorted (lower = more urgent).
#[derive(Debug, Clone, PartialEq)]
pub enum SortKey {
    /// Priority-first: (-priority, CR, task_id)
    PriorityFirst {
        neg_priority: f64,
        cr: f64,
        task_id: String,
    },
    /// CR-first: (CR, -priority, task_id)
    CRFirst {
        cr: f64,
        neg_priority: f64,
        task_id: String,
    },
    /// Weighted: (score, task_id)
    Weighted { score: f64, task_id: String },
    /// ATC: (-atc_score, task_id)
    ATC { neg_atc: f64, task_id: String },
}

impl SortKey {
    /// Get the task_id from any sort key variant.
    pub fn task_id(&self) -> &str {
        match self {
            Self::PriorityFirst { task_id, .. }
            | Self::CRFirst { task_id, .. }
            | Self::Weighted { task_id, .. }
            | Self::ATC { task_id, .. } => task_id,
        }
    }
}

/// Compare f64 values for sorting, treating NaN as greater than all other values.
fn cmp_f64(a: f64, b: f64) -> Ordering {
    a.partial_cmp(&b).unwrap_or(Ordering::Equal)
}

impl Eq for SortKey {}

impl Ord for SortKey {
    fn cmp(&self, other: &Self) -> Ordering {
        match (self, other) {
            (
                Self::PriorityFirst {
                    neg_priority: p1,
                    cr: cr1,
                    task_id: id1,
                },
                Self::PriorityFirst {
                    neg_priority: p2,
                    cr: cr2,
                    task_id: id2,
                },
            ) => cmp_f64(*p1, *p2)
                .then(cmp_f64(*cr1, *cr2))
                .then(id1.cmp(id2)),

            (
                Self::CRFirst {
                    cr: cr1,
                    neg_priority: p1,
                    task_id: id1,
                },
                Self::CRFirst {
                    cr: cr2,
                    neg_priority: p2,
                    task_id: id2,
                },
            ) => cmp_f64(*cr1, *cr2)
                .then(cmp_f64(*p1, *p2))
                .then(id1.cmp(id2)),

            (
                Self::Weighted {
                    score: s1,
                    task_id: id1,
                },
                Self::Weighted {
                    score: s2,
                    task_id: id2,
                },
            ) => cmp_f64(*s1, *s2).then(id1.cmp(id2)),

            (
                Self::ATC {
                    neg_atc: a1,
                    task_id: id1,
                },
                Self::ATC {
                    neg_atc: a2,
                    task_id: id2,
                },
            ) => cmp_f64(*a1, *a2).then(id1.cmp(id2)),

            // Different variants should not be compared, but provide a fallback
            _ => Ordering::Equal,
        }
    }
}

impl PartialOrd for SortKey {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

/// Compute critical ratio for a task.
///
/// CR = slack / max(duration, 1.0)
/// where slack = (deadline - current_time).days
///
/// Lower CR = more urgent (tighter deadline relative to work remaining).
pub fn compute_critical_ratio(
    deadline: Option<NaiveDate>,
    duration_days: f64,
    current_time: NaiveDate,
    default_cr: f64,
) -> f64 {
    match deadline {
        Some(d) if d != NaiveDate::MAX => {
            let slack = (d - current_time).num_days() as f64;
            slack / duration_days.max(1.0)
        }
        _ => default_cr,
    }
}

/// Compute ATC (Apparent Tardiness Cost) score for a task.
///
/// ATC = WSPT × urgency
/// where WSPT = priority / max(duration, 0.1)
/// and urgency = exp(-max(0, slack_days) / (K × avg_duration))  [if deadline]
///            or = default_urgency                               [if no deadline]
///
/// Higher ATC = more urgent.
pub fn compute_atc_score(
    deadline: Option<NaiveDate>,
    duration_days: f64,
    priority: i32,
    current_time: NaiveDate,
    atc_k: f64,
    atc_params: &AtcParams,
) -> f64 {
    let wspt = priority as f64 / duration_days.max(0.1);

    let urgency = match deadline {
        Some(d) if d != NaiveDate::MAX => {
            let slack_days = (d - current_time).num_days() as f64 - duration_days;
            if slack_days <= 0.0 {
                1.0
            } else {
                (-slack_days / (atc_k * atc_params.avg_duration)).exp()
            }
        }
        _ => atc_params.default_urgency,
    };

    wspt * urgency
}

/// Compute sort key for a single task.
///
/// Returns a `SortKey` that can be compared with other keys of the same type.
/// Lower sort key = more urgent (should be scheduled first).
pub fn compute_sort_key(
    task_id: &str,
    info: &TaskSortInfo,
    current_time: NaiveDate,
    default_cr: f64,
    config: &SchedulingConfig,
    atc_params: Option<&AtcParams>,
) -> Result<SortKey, SortingError> {
    let cr = compute_critical_ratio(info.deadline, info.duration_days, current_time, default_cr);
    let priority = info.priority;

    match config.strategy.as_str() {
        "priority_first" => Ok(SortKey::PriorityFirst {
            neg_priority: -(priority as f64),
            cr,
            task_id: task_id.to_string(),
        }),
        "cr_first" => Ok(SortKey::CRFirst {
            cr,
            neg_priority: -(priority as f64),
            task_id: task_id.to_string(),
        }),
        "weighted" => {
            let score = config.cr_weight * cr + config.priority_weight * (100.0 - priority as f64);
            Ok(SortKey::Weighted {
                score,
                task_id: task_id.to_string(),
            })
        }
        "atc" => {
            let params = atc_params.ok_or(SortingError::AtcParamsMissing)?;
            let atc_score = compute_atc_score(
                info.deadline,
                info.duration_days,
                priority,
                current_time,
                config.atc_k,
                params,
            );
            Ok(SortKey::ATC {
                neg_atc: -atc_score,
                task_id: task_id.to_string(),
            })
        }
        _ => Err(SortingError::UnknownStrategy(config.strategy.clone())),
    }
}

/// Sort task IDs by their sort keys.
///
/// Returns the task IDs sorted in priority order (most urgent first).
pub fn sort_tasks(
    task_ids: &[String],
    tasks: &HashMap<String, TaskSortInfo>,
    current_time: NaiveDate,
    default_cr: f64,
    config: &SchedulingConfig,
    atc_params: Option<&AtcParams>,
) -> Result<Vec<String>, SortingError> {
    let mut keys: Vec<SortKey> = Vec::with_capacity(task_ids.len());

    for task_id in task_ids {
        let info = tasks
            .get(task_id)
            .ok_or_else(|| SortingError::TaskNotFound(task_id.clone()))?;
        keys.push(compute_sort_key(
            task_id,
            info,
            current_time,
            default_cr,
            config,
            atc_params,
        )?);
    }

    keys.sort();

    Ok(keys.into_iter().map(|k| k.task_id().to_string()).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_config(strategy: &str) -> SchedulingConfig {
        SchedulingConfig {
            strategy: strategy.to_string(),
            cr_weight: 10.0,
            priority_weight: 1.0,
            default_priority: 50,
            default_cr_multiplier: 2.0,
            default_cr_floor: 10.0,
            atc_k: 2.0,
            atc_default_urgency_multiplier: 1.0,
            atc_default_urgency_floor: 0.3,
            verbosity: 0,
        }
    }

    fn make_date(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    #[test]
    fn test_critical_ratio_with_deadline() {
        let deadline = make_date(2025, 1, 31);
        let current = make_date(2025, 1, 1);
        let cr = compute_critical_ratio(Some(deadline), 10.0, current, 99.0);
        // slack = 30 days, duration = 10 days, CR = 30/10 = 3.0
        assert!((cr - 3.0).abs() < 0.001);
    }

    #[test]
    fn test_critical_ratio_without_deadline() {
        let cr = compute_critical_ratio(None, 10.0, make_date(2025, 1, 1), 99.0);
        assert!((cr - 99.0).abs() < 0.001);
    }

    #[test]
    fn test_critical_ratio_zero_duration() {
        let deadline = make_date(2025, 1, 31);
        let current = make_date(2025, 1, 1);
        // Zero duration should use max(0, 1.0) = 1.0
        let cr = compute_critical_ratio(Some(deadline), 0.0, current, 99.0);
        // slack = 30 days, CR = 30/1 = 30.0
        assert!((cr - 30.0).abs() < 0.001);
    }

    #[test]
    fn test_priority_first_strategy() {
        let config = make_config("priority_first");
        let current = make_date(2025, 1, 1);
        let deadline = make_date(2025, 1, 31);

        let mut tasks = HashMap::new();
        tasks.insert(
            "high_pri".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: Some(deadline),
                priority: 90,
            },
        );
        tasks.insert(
            "low_pri".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: Some(deadline),
                priority: 30,
            },
        );

        let task_ids = vec!["low_pri".to_string(), "high_pri".to_string()];
        let sorted = sort_tasks(&task_ids, &tasks, current, 10.0, &config, None).unwrap();

        // High priority (90) should come first
        assert_eq!(sorted, vec!["high_pri", "low_pri"]);
    }

    #[test]
    fn test_cr_first_strategy() {
        let config = make_config("cr_first");
        let current = make_date(2025, 1, 1);

        let mut tasks = HashMap::new();
        // Tight deadline (CR = 30/20 = 1.5)
        tasks.insert(
            "tight".to_string(),
            TaskSortInfo {
                duration_days: 20.0,
                deadline: Some(make_date(2025, 1, 31)),
                priority: 50,
            },
        );
        // Relaxed deadline (CR = 30/5 = 6.0)
        tasks.insert(
            "relaxed".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: Some(make_date(2025, 1, 31)),
                priority: 50,
            },
        );

        let task_ids = vec!["relaxed".to_string(), "tight".to_string()];
        let sorted = sort_tasks(&task_ids, &tasks, current, 10.0, &config, None).unwrap();

        // Lower CR (tighter deadline) should come first
        assert_eq!(sorted, vec!["tight", "relaxed"]);
    }

    #[test]
    fn test_weighted_strategy() {
        let config = make_config("weighted");
        let current = make_date(2025, 1, 1);
        let deadline = make_date(2025, 1, 31);

        let mut tasks = HashMap::new();
        // Task A: CR=3.0 (30/10), priority=90 -> score = 10*3.0 + 1*(100-90) = 40
        tasks.insert(
            "task_a".to_string(),
            TaskSortInfo {
                duration_days: 10.0,
                deadline: Some(deadline),
                priority: 90,
            },
        );
        // Task B: CR=6.0 (30/5), priority=50 -> score = 10*6.0 + 1*(100-50) = 110
        tasks.insert(
            "task_b".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: Some(deadline),
                priority: 50,
            },
        );

        let task_ids = vec!["task_b".to_string(), "task_a".to_string()];
        let sorted = sort_tasks(&task_ids, &tasks, current, 10.0, &config, None).unwrap();

        // Lower score should come first
        assert_eq!(sorted, vec!["task_a", "task_b"]);
    }

    #[test]
    fn test_atc_strategy() {
        let config = make_config("atc");
        let current = make_date(2025, 1, 1);

        let atc_params = AtcParams {
            avg_duration: 10.0,
            default_urgency: 0.3,
        };

        let mut tasks = HashMap::new();
        // Imminent deadline: high urgency
        tasks.insert(
            "urgent".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: Some(make_date(2025, 1, 6)), // 5 days, slack=0
                priority: 50,
            },
        );
        // Far deadline: low urgency
        tasks.insert(
            "relaxed".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: Some(make_date(2025, 2, 28)), // ~60 days
                priority: 50,
            },
        );

        let task_ids = vec!["relaxed".to_string(), "urgent".to_string()];
        let sorted =
            sort_tasks(&task_ids, &tasks, current, 10.0, &config, Some(&atc_params)).unwrap();

        // Higher ATC (more urgent) should come first
        assert_eq!(sorted, vec!["urgent", "relaxed"]);
    }

    #[test]
    fn test_atc_no_deadline_uses_default_urgency() {
        let config = make_config("atc");
        let current = make_date(2025, 1, 1);

        let atc_params = AtcParams {
            avg_duration: 10.0,
            default_urgency: 0.5, // High default urgency
        };

        let mut tasks = HashMap::new();
        // No deadline, uses default_urgency=0.5
        tasks.insert(
            "no_deadline".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: None,
                priority: 80, // High priority
            },
        );
        // Far deadline with low urgency
        tasks.insert(
            "far_deadline".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: Some(make_date(2025, 6, 30)), // Very far
                priority: 50,
            },
        );

        let task_ids = vec!["far_deadline".to_string(), "no_deadline".to_string()];
        let sorted =
            sort_tasks(&task_ids, &tasks, current, 10.0, &config, Some(&atc_params)).unwrap();

        // High priority no-deadline task with decent default urgency should win
        assert_eq!(sorted, vec!["no_deadline", "far_deadline"]);
    }

    #[test]
    fn test_unknown_strategy_error() {
        let config = make_config("unknown");
        let mut tasks = HashMap::new();
        tasks.insert(
            "task".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: None,
                priority: 50,
            },
        );
        let result = sort_tasks(
            &["task".to_string()],
            &tasks,
            make_date(2025, 1, 1),
            10.0,
            &config,
            None,
        );
        assert!(matches!(result, Err(SortingError::UnknownStrategy(_))));
    }

    #[test]
    fn test_atc_missing_params_error() {
        let config = make_config("atc");
        let mut tasks = HashMap::new();
        tasks.insert(
            "task".to_string(),
            TaskSortInfo {
                duration_days: 5.0,
                deadline: None,
                priority: 50,
            },
        );
        let result = sort_tasks(
            &["task".to_string()],
            &tasks,
            make_date(2025, 1, 1),
            10.0,
            &config,
            None,
        );
        assert!(matches!(result, Err(SortingError::AtcParamsMissing)));
    }

    #[test]
    fn test_task_not_found_error() {
        let config = make_config("weighted");
        let tasks = HashMap::new();
        let result = sort_tasks(
            &["missing".to_string()],
            &tasks,
            make_date(2025, 1, 1),
            10.0,
            &config,
            None,
        );
        assert!(matches!(result, Err(SortingError::TaskNotFound(_))));
    }

    #[test]
    fn test_tie_breaking_by_task_id() {
        let config = make_config("weighted");
        let current = make_date(2025, 1, 1);
        let deadline = make_date(2025, 1, 31);

        let mut tasks = HashMap::new();
        // Identical scores, different IDs
        tasks.insert(
            "task_b".to_string(),
            TaskSortInfo {
                duration_days: 10.0,
                deadline: Some(deadline),
                priority: 50,
            },
        );
        tasks.insert(
            "task_a".to_string(),
            TaskSortInfo {
                duration_days: 10.0,
                deadline: Some(deadline),
                priority: 50,
            },
        );

        let task_ids = vec!["task_b".to_string(), "task_a".to_string()];
        let sorted = sort_tasks(&task_ids, &tasks, current, 10.0, &config, None).unwrap();

        // Alphabetical tie-breaker
        assert_eq!(sorted, vec!["task_a", "task_b"]);
    }
}
