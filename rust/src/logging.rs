//! Logging macros for scheduler with verbosity level control.
//!
//! Provides zero-cost logging when disabled (verbosity=0).
//! Verbosity levels match Python's logger:
//! - 0: SILENT (only errors)
//! - 1: CHANGES (task assignments, time advances)
//! - 2: CHECKS (task consideration details)
//! - 3: DEBUG (full algorithm internals)

/// Verbosity level constants.
pub const VERBOSITY_SILENT: u8 = 0;
pub const VERBOSITY_CHANGES: u8 = 1;
pub const VERBOSITY_CHECKS: u8 = 2;
pub const VERBOSITY_DEBUG: u8 = 3;

/// Log at CHANGES level (verbosity >= 1).
///
/// Used for: task assignments, time advances, scheduling decisions.
#[macro_export]
macro_rules! log_changes {
    ($verbosity:expr, $($arg:tt)*) => {
        if $verbosity >= $crate::logging::VERBOSITY_CHANGES {
            eprintln!($($arg)*);
        }
    };
}

/// Log at CHECKS level (verbosity >= 2).
///
/// Used for: task consideration, skip reasons, eligibility checks.
#[macro_export]
macro_rules! log_checks {
    ($verbosity:expr, $($arg:tt)*) => {
        if $verbosity >= $crate::logging::VERBOSITY_CHECKS {
            eprintln!($($arg)*);
        }
    };
}

/// Log at DEBUG level (verbosity >= 3).
///
/// Used for: detailed algorithm internals, rollout simulations.
#[macro_export]
macro_rules! log_debug {
    ($verbosity:expr, $($arg:tt)*) => {
        if $verbosity >= $crate::logging::VERBOSITY_DEBUG {
            eprintln!($($arg)*);
        }
    };
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_verbosity_constants() {
        assert_eq!(VERBOSITY_SILENT, 0);
        assert_eq!(VERBOSITY_CHANGES, 1);
        assert_eq!(VERBOSITY_CHECKS, 2);
        assert_eq!(VERBOSITY_DEBUG, 3);
    }

    #[test]
    fn test_log_macros_compile() {
        // Just verify macros compile and don't panic
        let verbosity = VERBOSITY_SILENT;
        log_changes!(verbosity, "test {}", 1);
        log_checks!(verbosity, "test {}", 2);
        log_debug!(verbosity, "test {}", 3);
    }
}
