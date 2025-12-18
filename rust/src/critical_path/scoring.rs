//! Scoring functions for target and task selection.

use chrono::NaiveDate;

use super::types::{CriticalPathConfig, TargetInfo, TaskId, UrgencyDenominator, WorkTransform};

/// Transform the work term according to config.
///
/// The work term divisor can be:
/// - `work^exponent` (Power mode, default exponent=1.0)
/// - `ln(work)` (Log mode)
/// - `log10(work)` (Log10 mode)
///
/// Special cases for Power mode:
/// - exponent=0.0: returns 1.0 (effectively removes work term)
/// - exponent=1.0: returns work unchanged (linear, default behavior)
pub fn transform_work(work: f64, config: &CriticalPathConfig) -> f64 {
    let w = work.max(0.1); // Avoid log(0) or division by zero
    match config.work_transform {
        WorkTransform::Power => {
            if config.work_exponent == 0.0 {
                1.0 // Effectively removes work term
            } else if config.work_exponent == 1.0 {
                w // No transformation (default)
            } else {
                w.powf(config.work_exponent)
            }
        }
        WorkTransform::Log => w.ln().max(0.1), // Floor to avoid issues with work < e
        WorkTransform::Log10 => w.log10().max(0.1), // Floor to avoid issues with work < 10
    }
}

/// Score a target by its attractiveness.
///
/// Formula: (priority / f(work)) * urgency
/// where f(work) is configured by work_transform and work_exponent.
///
/// Higher score = more attractive target to work on.
pub fn score_target(
    target: &TargetInfo,
    config: &CriticalPathConfig,
    current_time: NaiveDate,
    avg_work: f64,
) -> f64 {
    let priority = target.priority as f64;
    let transformed_work = transform_work(target.total_work, config);
    let urgency = compute_urgency(target, config, current_time, avg_work);

    (priority / transformed_work) * urgency
}

/// Compute urgency for a target with a deadline.
///
/// Formula: `urgency = exp(-slack / (K * avg_work))`
/// where `slack = deadline - now - critical_path_length`
///
/// Returns urgency > 1.0 for negative slack (slipping deadlines),
/// 1.0 for slack = 0, and exponential decay floored by `urgency_floor` for positive slack.
pub fn compute_deadline_urgency(
    deadline: NaiveDate,
    critical_path_length: f64,
    current_time: NaiveDate,
    config: &CriticalPathConfig,
    avg_work: f64,
) -> f64 {
    let days_until = (deadline - current_time).num_days() as f64;
    let slack = days_until - critical_path_length;

    let denominator = config.k * avg_work.max(1.0);
    let urgency = (-slack / denominator).exp();
    if slack > 0.0 {
        urgency.max(config.urgency_floor)
    } else {
        urgency
    }
}

/// Compute urgency for a target without a deadline.
///
/// Formula: `urgency = max(min_deadline_urgency * multiplier, floor)`
///
/// If `min_deadline_urgency` is None (no deadline targets exist), returns 1.0.
pub fn compute_no_deadline_urgency(
    min_deadline_urgency: Option<f64>,
    config: &CriticalPathConfig,
) -> f64 {
    match min_deadline_urgency {
        Some(min_urg) => {
            (min_urg * config.no_deadline_urgency_multiplier).max(config.urgency_floor)
        }
        None => 1.0,
    }
}

/// Compute urgency factor for a target (internal helper).
///
/// Note: For no-deadline targets, this returns a fixed value without context.
/// Use `compute_no_deadline_urgency` with precomputed min_deadline_urgency
/// for context-aware behavior.
fn compute_urgency(
    target: &TargetInfo,
    config: &CriticalPathConfig,
    current_time: NaiveDate,
    avg_work: f64,
) -> f64 {
    match target.deadline {
        Some(deadline) => compute_deadline_urgency(
            deadline,
            target.critical_path_length,
            current_time,
            config,
            avg_work,
        ),
        None => {
            // Fallback without context - just use multiplier
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

/// Compute urgency for a task based on its slack relative to a target.
///
/// Formula: `urgency = exp(-slack / (K * denominator))`
///
/// Returns urgency > 1.0 for negative slack (behind schedule),
/// 1.0 for slack = 0 (on critical path), and exponential decay
/// floored by `urgency_floor` for positive slack.
///
/// # Arguments
/// * `slack` - Task's slack relative to a target (days)
/// * `config` - Scheduler configuration
/// * `denominator` - The value to use in the decay formula (varies by config)
pub fn compute_task_urgency(slack: f64, config: &CriticalPathConfig, denominator: f64) -> f64 {
    let decay_factor = config.k * denominator.max(1.0);
    let urgency = (-slack / decay_factor).exp();
    if slack > 0.0 {
        urgency.max(config.urgency_floor)
    } else {
        urgency
    }
}

/// Get the urgency denominator for a target based on config.
///
/// Returns the appropriate value to use in the task urgency formula:
/// - GlobalAvg: uses the provided avg_work
/// - TargetWork: uses target's total_work
/// - CriticalPath: uses target's critical_path_length
pub fn get_urgency_denominator(
    target: &TargetInfo,
    avg_work: f64,
    config: &CriticalPathConfig,
) -> f64 {
    match config.urgency_denominator {
        UrgencyDenominator::GlobalAvg => avg_work,
        UrgencyDenominator::TargetWork => target.total_work,
        UrgencyDenominator::CriticalPath => target.critical_path_length,
    }
}

/// Score a task based on its maximum contribution across all targets.
///
/// Formula: `max over all targets G: [ target_score(G) * urgency(slack(T, G)) ]`
///
/// This unified scoring considers all targets a task contributes to and returns
/// the maximum score. Critical path tasks (slack=0) get urgency=1.0, so they
/// naturally score highest for their target.
///
/// # Arguments
/// * `task_target_slacks` - Iterator of (target_int, slack) pairs for this task
/// * `target_scores` - Precomputed target scores indexed by target_int
/// * `target_denominators` - Urgency denominators per target indexed by target_int
/// * `config` - Scheduler configuration
///
/// Returns the maximum score contribution, or 0.0 if task has no targets.
pub fn score_task_unified<'a>(
    task_target_slacks: impl Iterator<Item = &'a (TaskId, f64)>,
    target_scores: &[f64],
    target_denominators: &[f64],
    config: &CriticalPathConfig,
) -> f64 {
    task_target_slacks
        .map(|(target_int, slack)| {
            let idx = *target_int as usize;
            let target_score = target_scores.get(idx).copied().unwrap_or(0.0);
            let denominator = target_denominators.get(idx).copied().unwrap_or(1.0);
            let urgency = compute_task_urgency(*slack, config, denominator);
            target_score * urgency
        })
        .fold(0.0_f64, f64::max)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rustc_hash::FxHashSet;

    fn make_target(id: &str, priority: i32, total_work: f64, cp_length: f64) -> TargetInfo {
        TargetInfo {
            target_id: id.to_string(),
            target_int: 0, // Test value
            critical_path_ints: Vec::new(),
            critical_path_tasks: FxHashSet::default(),
            total_work,
            critical_path_length: cp_length,
            priority,
            deadline: None,
            urgency: 0.0,
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
        let config = CriticalPathConfig::default(); // k=2.0
        let current_time = d(2025, 1, 15);

        let mut past_deadline = make_target("a", 50, 10.0, 10.0);
        past_deadline.deadline = Some(d(2025, 1, 10)); // Already past!

        // slack = (10 - 15) - 10 = -15 days
        // urgency = exp(-(-15) / (2 * 10)) = exp(0.75) ≈ 2.117
        let urgency = compute_urgency(&past_deadline, &config, current_time, 10.0);
        let expected = (0.75_f64).exp();
        assert!(urgency > 1.0); // Above maximum for slipping deadlines
        assert!((urgency - expected).abs() < 1e-9);
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
    fn test_compute_deadline_urgency() {
        let config = CriticalPathConfig::default();
        let current_time = d(2025, 1, 1);

        // Tight deadline (1 day slack)
        let tight = compute_deadline_urgency(
            d(2025, 1, 12), // 11 days away
            10.0,           // 10 days of work
            current_time,
            &config,
            10.0,
        );

        // Loose deadline (21 days slack)
        let loose = compute_deadline_urgency(
            d(2025, 2, 1), // 31 days away
            10.0,          // 10 days of work
            current_time,
            &config,
            10.0,
        );

        assert!(tight > loose);
        assert!(tight <= 1.0);
        assert!(loose >= config.urgency_floor);
    }

    #[test]
    fn test_compute_no_deadline_urgency() {
        let config = CriticalPathConfig::default();

        // With deadline context
        let urg = compute_no_deadline_urgency(Some(0.8), &config);
        assert!((urg - 0.8 * config.no_deadline_urgency_multiplier).abs() < 1e-9);

        // Without deadline context (no deadline targets)
        let urg_none = compute_no_deadline_urgency(None, &config);
        assert!((urg_none - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_no_deadline_urgency_respects_floor() {
        // Custom config with low multiplier
        let config = CriticalPathConfig::new(
            2.0,  // k
            0.01, // no_deadline_urgency_multiplier (very low)
            0.1,  // urgency_floor
            0,
            true,
            1.0,
            Some(30),
            "power",
            1.0,
            true,         // prefer_fungible_resources
            "global_avg", // urgency_denominator
        )
        .unwrap();

        // Even with very low min_deadline_urgency * multiplier, should respect floor
        let urg = compute_no_deadline_urgency(Some(0.5), &config);
        assert!((urg - config.urgency_floor).abs() < 1e-9); // 0.5 * 0.01 = 0.005 < 0.1, so floor
    }

    #[test]
    fn test_no_deadline_urgency_with_small_floor() {
        // Config like user's: urgency_floor=0.001, multiplier=0.9
        let config = CriticalPathConfig::new(
            1.5,   // k
            0.9,   // no_deadline_urgency_multiplier
            0.001, // urgency_floor (very low)
            0,
            true,
            1.0,
            Some(60),
            "power",
            1.0,
            true,         // prefer_fungible_resources
            "global_avg", // urgency_denominator
        )
        .unwrap();

        // With some deadline urgency
        let urg = compute_no_deadline_urgency(Some(0.5), &config);
        // Should be 0.5 * 0.9 = 0.45, not 0.9 * 0.001 = 0.0009
        assert!((urg - 0.45).abs() < 1e-9);

        // Without deadline targets, should get 1.0, not some tiny value
        let urg_none = compute_no_deadline_urgency(None, &config);
        assert!((urg_none - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_transform_work_power_default() {
        let config = CriticalPathConfig::default();
        // Default is power with exponent 1.0 (linear)
        assert!((transform_work(10.0, &config) - 10.0).abs() < 1e-9);
        assert!((transform_work(100.0, &config) - 100.0).abs() < 1e-9);
    }

    #[test]
    fn test_transform_work_power_sqrt() {
        let config = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "power",
            0.5,
            true,
            "global_avg",
        )
        .unwrap();
        // sqrt transform
        assert!((transform_work(4.0, &config) - 2.0).abs() < 1e-9);
        assert!((transform_work(100.0, &config) - 10.0).abs() < 1e-9);
    }

    #[test]
    fn test_transform_work_power_zero() {
        let config = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "power",
            0.0,
            true,
            "global_avg",
        )
        .unwrap();
        // exponent=0 means no work term (returns 1.0)
        assert!((transform_work(10.0, &config) - 1.0).abs() < 1e-9);
        assert!((transform_work(100.0, &config) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_transform_work_log() {
        let config = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "log",
            1.0,
            true,
            "global_avg",
        )
        .unwrap();
        // ln(e) = 1, ln(e^2) = 2
        let e = std::f64::consts::E;
        assert!((transform_work(e, &config) - 1.0).abs() < 1e-9);
        assert!((transform_work(e * e, &config) - 2.0).abs() < 1e-9);
    }

    #[test]
    fn test_transform_work_log10() {
        let config = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "log10",
            1.0,
            true,
            "global_avg",
        )
        .unwrap();
        // log10(10) = 1, log10(100) = 2
        assert!((transform_work(10.0, &config) - 1.0).abs() < 1e-9);
        assert!((transform_work(100.0, &config) - 2.0).abs() < 1e-9);
    }

    #[test]
    fn test_transform_work_floors_small_values() {
        let config_log = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "log",
            1.0,
            true,
            "global_avg",
        )
        .unwrap();
        // Very small work values should be floored to avoid negative/tiny log values
        assert!(transform_work(0.01, &config_log) >= 0.1);

        let config_log10 = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "log10",
            1.0,
            true,
            "global_avg",
        )
        .unwrap();
        assert!(transform_work(0.01, &config_log10) >= 0.1);
    }

    // Tests for compute_task_urgency

    #[test]
    fn test_compute_task_urgency_zero_slack() {
        let config = CriticalPathConfig::default(); // k=2.0
                                                    // Zero slack (on critical path) should give urgency = 1.0
        assert!((compute_task_urgency(0.0, &config, 10.0) - 1.0).abs() < 1e-9);
        // Negative slack should give urgency > 1.0
        // slack=-5, denom=10, k=2: exp(-(-5) / (2 * 10)) = exp(0.25) ≈ 1.284
        let expected = (0.25_f64).exp();
        assert!((compute_task_urgency(-5.0, &config, 10.0) - expected).abs() < 1e-9);
    }

    #[test]
    fn test_compute_task_urgency_positive_slack() {
        let config = CriticalPathConfig::default(); // k=2.0, urgency_floor=0.1
        let denominator = 10.0;
        // slack=10, denominator=10, k=2: urgency = exp(-10 / (2 * 10)) = exp(-0.5) ≈ 0.606
        let urgency = compute_task_urgency(10.0, &config, denominator);
        let expected = (-0.5_f64).exp();
        assert!((urgency - expected).abs() < 1e-9);
        assert!(urgency < 1.0);
        assert!(urgency > config.urgency_floor);
    }

    #[test]
    fn test_compute_task_urgency_respects_floor() {
        let config = CriticalPathConfig::default(); // urgency_floor=0.1
        let denominator = 1.0;
        // Very large slack should hit the floor
        let urgency = compute_task_urgency(100.0, &config, denominator);
        assert!((urgency - config.urgency_floor).abs() < 1e-9);
    }

    #[test]
    fn test_compute_task_urgency_k_parameter() {
        // Higher K = more tolerant of slack (slower decay)
        let config_low_k = CriticalPathConfig::new(
            1.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "power",
            1.0,
            true,
            "global_avg",
        )
        .unwrap();
        let config_high_k = CriticalPathConfig::new(
            4.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "power",
            1.0,
            true,
            "global_avg",
        )
        .unwrap();

        let slack = 10.0;
        let denominator = 10.0;
        let urgency_low_k = compute_task_urgency(slack, &config_low_k, denominator);
        let urgency_high_k = compute_task_urgency(slack, &config_high_k, denominator);

        // Higher K should give higher urgency for same slack
        assert!(urgency_high_k > urgency_low_k);
    }

    // Tests for get_urgency_denominator

    #[test]
    fn test_get_urgency_denominator_modes() {
        let target = make_target("test", 50, 100.0, 25.0);
        let avg_work = 50.0;

        // GlobalAvg mode
        let config_global = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "power",
            1.0,
            true,
            "global_avg",
        )
        .unwrap();
        assert!((get_urgency_denominator(&target, avg_work, &config_global) - 50.0).abs() < 1e-9);

        // TargetWork mode
        let config_work = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "power",
            1.0,
            true,
            "target_work",
        )
        .unwrap();
        assert!((get_urgency_denominator(&target, avg_work, &config_work) - 100.0).abs() < 1e-9);

        // CriticalPath mode
        let config_cp = CriticalPathConfig::new(
            2.0,
            0.5,
            0.1,
            0,
            true,
            1.0,
            Some(30),
            "power",
            1.0,
            true,
            "critical_path",
        )
        .unwrap();
        assert!((get_urgency_denominator(&target, avg_work, &config_cp) - 25.0).abs() < 1e-9);
    }

    // Tests for score_task_unified

    #[test]
    fn test_score_task_unified_single_target() {
        let config = CriticalPathConfig::default();
        let target_scores = vec![0.0, 10.0, 5.0]; // target 1 has score 10, target 2 has score 5
        let target_denominators = vec![10.0, 10.0, 10.0];

        // Task on critical path of target 1 (slack=0)
        let task_slacks = vec![(1u32, 0.0)];
        let score = score_task_unified(
            task_slacks.iter(),
            &target_scores,
            &target_denominators,
            &config,
        );
        assert!((score - 10.0).abs() < 1e-9); // target_score * urgency(0) = 10 * 1.0 = 10

        // Task with slack of 10 on target 1
        let task_slacks = vec![(1u32, 10.0)];
        let score = score_task_unified(
            task_slacks.iter(),
            &target_scores,
            &target_denominators,
            &config,
        );
        let expected = 10.0 * (-0.5_f64).exp(); // k=2, denom=10: exp(-10/(2*10))
        assert!((score - expected).abs() < 1e-9);
    }

    #[test]
    fn test_score_task_unified_multi_target_uses_max() {
        let config = CriticalPathConfig::default();
        let target_scores = vec![0.0, 10.0, 8.0]; // target 1: 10, target 2: 8
        let target_denominators = vec![10.0, 10.0, 10.0];

        // Task with slack on target 1 but critical for target 2
        // Target 1: 10 * exp(-10 / 20) ≈ 10 * 0.606 = 6.06
        // Target 2: 8 * 1.0 = 8.0
        // Max = 8.0
        let task_slacks = vec![(1u32, 10.0), (2u32, 0.0)];
        let score = score_task_unified(
            task_slacks.iter(),
            &target_scores,
            &target_denominators,
            &config,
        );
        assert!((score - 8.0).abs() < 1e-9);
    }

    #[test]
    fn test_score_task_unified_empty_targets() {
        let config = CriticalPathConfig::default();
        let target_scores = vec![10.0, 5.0];
        let target_denominators = vec![10.0, 10.0];

        // Task with no targets
        let task_slacks: Vec<(TaskId, f64)> = vec![];
        let score = score_task_unified(
            task_slacks.iter(),
            &target_scores,
            &target_denominators,
            &config,
        );
        assert!((score - 0.0).abs() < 1e-9);
    }

    #[test]
    fn test_score_task_unified_critical_path_always_wins() {
        // Verify the key invariant: critical path task of top target beats all others
        let config = CriticalPathConfig::default();
        let target_scores = vec![0.0, 10.0, 9.0]; // target 1: 10 (top), target 2: 9
        let target_denominators = vec![10.0, 10.0, 10.0];

        // Task A: critical for target 1 (top target)
        let task_a_slacks = vec![(1u32, 0.0)];
        let score_a = score_task_unified(
            task_a_slacks.iter(),
            &target_scores,
            &target_denominators,
            &config,
        );

        // Task B: critical for target 2
        let task_b_slacks = vec![(2u32, 0.0)];
        let score_b = score_task_unified(
            task_b_slacks.iter(),
            &target_scores,
            &target_denominators,
            &config,
        );

        // Task C: critical for both target 2 and has some slack on target 1
        let task_c_slacks = vec![(1u32, 5.0), (2u32, 0.0)];
        let score_c = score_task_unified(
            task_c_slacks.iter(),
            &target_scores,
            &target_denominators,
            &config,
        );

        // Task A (critical for top target) should beat all others
        assert!(
            score_a > score_b,
            "Critical task for top target should beat critical task for lower target"
        );
        assert!(
            score_a > score_c,
            "Critical task for top target should beat multi-target task"
        );
    }
}
