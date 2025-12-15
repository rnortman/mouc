//! Scheduler module for Parallel SGS with optional bounded rollout.
//!
//! This module provides a unified scheduler that implements the Parallel Schedule
//! Generation Scheme (SGS) algorithm with optional bounded rollout lookahead.

mod core;
mod resource_schedule;
mod rollout;
mod state;

pub use core::{ParallelScheduler, ResourceConfig, SchedulerError};
pub use resource_schedule::ResourceSchedule;
pub use rollout::RolloutDecision;
pub use state::SchedulerState;
