//! Scoring functions for target and task selection.

use chrono::NaiveDate;

use super::types::{CriticalPathConfig, TargetInfo};

/// Score a target by its attractiveness.
///
/// Formula: (priority / total_work) * urgency
///
/// Higher score = more attractive target to work on.
pub fn score_target(
    target: &TargetInfo,
    config: &CriticalPathConfig,
    current_time: NaiveDate,
    avg_work: f64,
) -> f64 {
    let priority = target.priority as f64;
    let work = target.total_work.max(0.1); // Avoid division by zero
    let urgency = compute_urgency(target, config, current_time, avg_work);

    (priority / work) * urgency
}

/// Compute urgency factor for a target.
///
/// For targets with deadlines:
///   urgency = exp(-max(0, slack) / (K * avg_work))
/// where slack = deadline - now - critical_path_length
///
/// For targets without deadlines:
///   urgency = no_deadline_urgency_multiplier, floored by urgency_floor
fn compute_urgency(
    target: &TargetInfo,
    config: &CriticalPathConfig,
    current_time: NaiveDate,
    avg_work: f64,
) -> f64 {
    match target.deadline {
        Some(deadline) => {
            let days_until_deadline = (deadline - current_time).num_days() as f64;
            let slack = days_until_deadline - target.critical_path_length;

            if slack <= 0.0 {
                // Already late or exactly on time - maximum urgency
                1.0
            } else {
                let denominator = config.k * avg_work.max(1.0);
                (-slack / denominator).exp().max(config.urgency_floor)
            }
        }
        None => {
            // No deadline - use fixed urgency based on config
            config
                .no_deadline_urgency_multiplier
                .max(config.urgency_floor)
        }
    }
}

/// Score a task within a critical path using WSPT (Weighted Shortest Processing Time).
///
/// Formula: priority / duration
///
/// Higher score = better task to schedule first.
pub fn score_task(priority: i32, duration: f64) -> f64 {
    let priority = priority as f64;
    let duration = duration.max(0.1); // Avoid division by zero
    priority / duration
}

/// Compute urgency with access to all targets (for deriving default urgency).
///
/// For non-deadline targets, this computes:
///   min(urgency of deadline targets) * multiplier, floored
pub fn compute_urgency_with_context(
    target: &TargetInfo,
    all_targets: &[TargetInfo],
    config: &CriticalPathConfig,
    current_time: NaiveDate,
    avg_work: f64,
) -> f64 {
    match target.deadline {
        Some(_) => compute_urgency(target, config, current_time, avg_work),
        None => {
            // Find minimum urgency among deadline targets
            let min_deadline_urgency = all_targets
                .iter()
                .filter(|t| t.deadline.is_some())
                .map(|t| compute_urgency(t, config, current_time, avg_work))
                .min_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
                .unwrap_or(1.0);

            (min_deadline_urgency * config.no_deadline_urgency_multiplier).max(config.urgency_floor)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn make_target(id: &str, priority: i32, total_work: f64, cp_length: f64) -> TargetInfo {
        TargetInfo {
            target_id: id.to_string(),
            critical_path_tasks: HashSet::new(),
            total_work,
            critical_path_length: cp_length,
            priority,
            deadline: None,
            score: 0.0,
        }
    }

    fn d(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    #[test]
    fn test_score_target_basic() {
        let config = CriticalPathConfig::default();
        let current_time = d(2025, 1, 1);

        // Higher priority, lower work = better score
        let target1 = make_target("a", 100, 10.0, 10.0);
        let target2 = make_target("b", 50, 10.0, 10.0);

        let score1 = score_target(&target1, &config, current_time, 10.0);
        let score2 = score_target(&target2, &config, current_time, 10.0);

        assert!(score1 > score2); // Higher priority wins
    }

    #[test]
    fn test_score_target_work_matters() {
        let config = CriticalPathConfig::default();
        let current_time = d(2025, 1, 1);

        // Same priority, lower work = better score (low-hanging fruit)
        let target1 = make_target("a", 50, 5.0, 5.0);
        let target2 = make_target("b", 50, 50.0, 50.0);

        let score1 = score_target(&target1, &config, current_time, 10.0);
        let score2 = score_target(&target2, &config, current_time, 10.0);

        assert!(score1 > score2); // Lower work wins
    }

    #[test]
    fn test_urgency_with_deadline() {
        let config = CriticalPathConfig::default();
        let current_time = d(2025, 1, 1);

        // Tight deadline = high urgency
        let mut tight_deadline = make_target("a", 50, 10.0, 10.0);
        tight_deadline.deadline = Some(d(2025, 1, 12)); // 11 days, 1 day slack

        // Loose deadline = low urgency
        let mut loose_deadline = make_target("b", 50, 10.0, 10.0);
        loose_deadline.deadline = Some(d(2025, 2, 1)); // 31 days, 21 days slack

        let score_tight = score_target(&tight_deadline, &config, current_time, 10.0);
        let score_loose = score_target(&loose_deadline, &config, current_time, 10.0);

        assert!(score_tight > score_loose); // Tight deadline more urgent
    }

    #[test]
    fn test_urgency_past_deadline() {
        let config = CriticalPathConfig::default();
        let current_time = d(2025, 1, 15);

        let mut past_deadline = make_target("a", 50, 10.0, 10.0);
        past_deadline.deadline = Some(d(2025, 1, 10)); // Already past!

        let urgency = compute_urgency(&past_deadline, &config, current_time, 10.0);
        assert!((urgency - 1.0).abs() < 1e-9); // Maximum urgency
    }

    #[test]
    fn test_no_deadline_uses_floor() {
        let config = CriticalPathConfig::default();
        let current_time = d(2025, 1, 1);

        let no_deadline = make_target("a", 50, 10.0, 10.0);
        let urgency = compute_urgency(&no_deadline, &config, current_time, 10.0);

        // Should use no_deadline_urgency_multiplier (0.5) capped by floor (0.1)
        assert!((urgency - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_score_task_wspt() {
        // Higher priority, shorter duration = better
        assert!(score_task(100, 1.0) > score_task(100, 10.0)); // Shorter is better
        assert!(score_task(100, 5.0) > score_task(50, 5.0)); // Higher priority is better
    }

    #[test]
    fn test_urgency_with_context() {
        let config = CriticalPathConfig::default();
        let current_time = d(2025, 1, 1);

        let mut deadline_target = make_target("a", 50, 10.0, 10.0);
        deadline_target.deadline = Some(d(2025, 1, 15)); // 14 days, 4 days slack

        let no_deadline_target = make_target("b", 50, 5.0, 5.0);

        let all_targets = vec![deadline_target.clone(), no_deadline_target.clone()];

        let urgency_a = compute_urgency_with_context(
            &deadline_target,
            &all_targets,
            &config,
            current_time,
            10.0,
        );
        let urgency_b = compute_urgency_with_context(
            &no_deadline_target,
            &all_targets,
            &config,
            current_time,
            10.0,
        );

        // Non-deadline target gets fraction of min deadline urgency
        assert!(urgency_a > urgency_b);
        assert!(urgency_b >= config.urgency_floor);
    }
}
