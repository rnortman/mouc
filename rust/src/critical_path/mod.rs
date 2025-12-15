//! Critical path scheduling algorithm.
//!
//! This module implements critical path scheduling as an alternative to the
//! greedy parallel SGS scheduler. It eliminates priority contamination by
//! focusing only on tasks that are actually on the critical path to attractive
//! targets.

mod calculation;
mod scheduler;
mod scoring;
mod types;

pub use calculation::{calculate_critical_path, CriticalPathResult};
pub use scheduler::{CriticalPathScheduler, CriticalPathSchedulerError};
pub use scoring::{score_target, score_task};
pub use types::{CriticalPathConfig, TargetInfo, TaskTiming};
