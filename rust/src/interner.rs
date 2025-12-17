//! String interning for fast hash lookups.
//!
//! Converts string task IDs to integer IDs for faster HashMap operations.

use rustc_hash::FxHashMap;

/// Interned task ID (u32 for compact storage and fast hashing).
pub type TaskIdInt = u32;

/// String interner that maps task ID strings to integers.
#[derive(Debug, Clone)]
pub struct TaskIdInterner {
    to_int: FxHashMap<String, TaskIdInt>,
    from_int: Vec<String>,
}

impl TaskIdInterner {
    /// Create a new interner with pre-allocated capacity.
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            to_int: FxHashMap::with_capacity_and_hasher(capacity, Default::default()),
            from_int: Vec::with_capacity(capacity),
        }
    }

    /// Intern a string, returning its integer ID.
    /// If already interned, returns the existing ID.
    pub fn intern(&mut self, s: &str) -> TaskIdInt {
        if let Some(&id) = self.to_int.get(s) {
            return id;
        }
        let id = self.from_int.len() as TaskIdInt;
        self.from_int.push(s.to_string());
        self.to_int.insert(s.to_string(), id);
        id
    }

    /// Get the integer ID for a string, if it exists.
    #[inline]
    pub fn get(&self, s: &str) -> Option<TaskIdInt> {
        self.to_int.get(s).copied()
    }

    /// Get the string for an integer ID.
    #[inline]
    pub fn resolve(&self, id: TaskIdInt) -> Option<&str> {
        self.from_int.get(id as usize).map(|s| s.as_str())
    }

    /// Number of interned strings.
    pub fn len(&self) -> usize {
        self.from_int.len()
    }

    /// Check if empty.
    pub fn is_empty(&self) -> bool {
        self.from_int.is_empty()
    }
}

impl Default for TaskIdInterner {
    fn default() -> Self {
        Self::with_capacity(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_intern_and_resolve() {
        let mut interner = TaskIdInterner::with_capacity(10);

        let id1 = interner.intern("task_a");
        let id2 = interner.intern("task_b");
        let id3 = interner.intern("task_a"); // duplicate

        assert_eq!(id1, id3); // same string = same ID
        assert_ne!(id1, id2);

        assert_eq!(interner.resolve(id1), Some("task_a"));
        assert_eq!(interner.resolve(id2), Some("task_b"));
        assert_eq!(interner.get("task_a"), Some(id1));
        assert_eq!(interner.get("nonexistent"), None);
    }
}
