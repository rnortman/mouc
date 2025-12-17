//! Critical path scheduling algorithm.
//!
//! This module implements critical path scheduling as an alternative to the
//! greedy parallel SGS scheduler. It eliminates priority contamination by
//! focusing only on tasks that are actually on the critical path to attractive
//! targets.

mod cache;
mod calculation;
pub mod rollout;
mod scheduler;
mod scoring;
mod state;
mod types;

pub use calculation::{
    build_dependents_map, calculate_critical_path, calculate_critical_path_interned,
    calculate_critical_path_with_dependents, CriticalPathResult, DependentsMap, InternedContext,
};
pub use rollout::{ResourceReservation, RolloutConfig};
pub use scheduler::{CriticalPathScheduler, CriticalPathSchedulerError};
pub use scoring::{score_target, score_task};
pub use state::CriticalPathSchedulerState;
pub use types::{CriticalPathConfig, TargetInfo, TaskTiming};
