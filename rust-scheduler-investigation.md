# Rust Scheduler Investigation

**Date**: 2025-12-14
**Investigation**: Feasibility of rewriting greedy schedulers in Rust for performance

## Executive Summary

This investigation examines rewriting Mouc's greedy scheduling algorithms (Parallel SGS and Bounded Rollout) in Rust. Key findings:

- **Viable candidates**: Both `parallel_sgs.py` and `bounded_rollout.py` are computationally intensive and well-suited for Rust
- **Performance gain estimate**: 5-20x speedup for large schedules (100+ tasks)
- **Interface**: PyO3 provides mature Python-Rust bindings with minimal overhead
- **Distribution impact**: Moderate - requires pre-built wheels for major platforms
- **Development effort**: Medium - core algorithms are pure logic with minimal Python-specific dependencies
- **Recommendation**: Proceed with prototype, starting with Parallel SGS scheduler

## Current Implementation Analysis

### Scheduler Architecture

The codebase contains two greedy scheduling algorithms:

1. **Parallel SGS** (`src/mouc/scheduler/algorithms/parallel_sgs.py`, ~908 LOC)
   - Implements Parallel Schedule Generation Scheme for RCPSP
   - Greedy-with-foresight approach for resource assignment
   - Multiple prioritization strategies (CR-first, priority-first, weighted, ATC)
   - Handles DNS periods, resource constraints, dependencies

2. **Bounded Rollout** (`src/mouc/scheduler/algorithms/bounded_rollout.py`, ~1430 LOC)
   - Extends Parallel SGS with lookahead simulation
   - Runs mini-simulations to evaluate schedule vs. skip decisions
   - More sophisticated but computationally expensive
   - State copying and rollout evaluation add overhead

### Code Structure

Both schedulers share common patterns:
- Topological sorting for dependency resolution
- Backward pass for deadline/priority propagation
- Forward pass with greedy scheduling
- Resource schedule tracking (`ResourceSchedule` class)
- Configuration-driven prioritization

**Total scheduler codebase**: ~4,320 lines of Python

### Computational Hotspots

Performance-critical operations identified:

1. **Sorting eligible tasks** (happens at each time step)
   - Computed for every eligible task at every scheduling decision point
   - CR/priority/ATC score calculations
   - Multiple sort operations per iteration

2. **Resource availability checks** (N tasks × M resources × T time steps)
   - `next_available_time()` - iterates through busy periods
   - `calculate_completion_time()` - walks through DNS gaps
   - Uses `bisect.insort` for maintaining sorted busy periods

3. **Rollout simulations** (Bounded Rollout only)
   - Deep copying of scheduler state
   - Running full forward scheduling in simulation
   - Can trigger multiple simulations per decision point
   - Exponential complexity in worst case

4. **Topological sorting and backward pass**
   - One-time cost at initialization
   - Less critical than forward pass

## Rust Rewrite Scope

### What to Rewrite

**Phase 1: Core Scheduling Engine**
- `ParallelScheduler._schedule_forward()`
- `BoundedRolloutScheduler._schedule_forward()`
- `ResourceSchedule` class (busy period tracking)
- Sort key computation functions
- Eligibility checking logic

**Phase 2: Pre-processing**
- Backward pass (`_calculate_latest_dates()`)
- Topological sort (`_topological_sort_for_backward()`)
- CR/priority computation

**Keep in Python**
- Configuration and config parsing
- Task input/output conversion
- High-level orchestration
- Logging and debugging output
- Integration with broader Mouc ecosystem

### Data Interface

The interface between Python and Rust would pass:

**Inputs to Rust**:
```rust
struct Task {
    id: String,
    duration_days: f64,
    resources: Vec<(String, f64)>,
    dependencies: Vec<Dependency>,
    start_after: Option<Date>,
    end_before: Option<Date>,
    start_on: Option<Date>,
    end_on: Option<Date>,
    resource_spec: Option<String>,
    priority: i32,
}

struct Dependency {
    entity_id: String,
    lag_days: f64,
}

struct SchedulingConfig {
    strategy: Strategy,
    cr_weight: f64,
    priority_weight: f64,
    // ... other config fields
}
```

**Outputs from Rust**:
```rust
struct ScheduledTask {
    task_id: String,
    start_date: Date,
    end_date: Date,
    duration_days: f64,
    resources: Vec<String>,
}

struct AlgorithmResult {
    scheduled_tasks: Vec<ScheduledTask>,
    algorithm_metadata: HashMap<String, Value>,
}
```

## Python-Rust Interface

### Recommended: PyO3 + maturin

**PyO3** is the industry-standard solution for Python-Rust bindings:

**Advantages**:
- Native Python types (dict, list, date) conversion
- Zero-copy data sharing where possible
- Mature ecosystem, widely used (polars, ruff, pydantic-core)
- Excellent error handling and Python exception support
- Strong typing on both sides

**Example Interface**:
```rust
use pyo3::prelude::*;
use pyo3::types::PyDate;

#[pyclass]
struct RustParallelScheduler {
    // Rust implementation
}

#[pymethods]
impl RustParallelScheduler {
    #[new]
    fn new(
        tasks: Vec<PyTask>,
        current_date: &PyDate,
        config: PySchedulingConfig,
    ) -> PyResult<Self> {
        // Convert and initialize
    }

    fn schedule(&self) -> PyResult<PyAlgorithmResult> {
        // Run scheduling algorithm
        // Return results
    }
}

#[pymodule]
fn mouc_rust(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<RustParallelScheduler>()?;
    Ok(())
}
```

**Usage from Python**:
```python
from mouc_rust import RustParallelScheduler

scheduler = RustParallelScheduler(tasks, current_date, config)
result = scheduler.schedule()
```

### Alternative: CFFI

Less recommended but viable:
- More manual memory management
- C ABI boundary (less ergonomic)
- Better for existing C libraries, not greenfield Rust

### Build Tool: maturin

**maturin** handles PyO3 project building:
- Automatically builds wheels for multiple platforms
- Integrates with PyPI publishing workflow
- Supports mixed Python/Rust projects
- Development mode for rapid iteration

## Packaging & Distribution Impact

### Build System Changes

**Current** (pure Python):
```toml
[build-system]
requires = ["setuptools>=61", "wheel"]
build-backend = "setuptools.build_meta"
```

**With Rust**:
```toml
[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

[project]
# ... existing config ...

[tool.maturin]
features = ["pyo3/extension-module"]
module-name = "mouc._rust"
python-source = "src"
```

### Platform Support

**Pre-built wheels needed for**:
- Linux (x86_64, aarch64)
- macOS (x86_64, arm64)
- Windows (x86_64)

**CI/CD Requirements**:
- GitHub Actions with matrix builds
- Cross-compilation or platform-specific runners
- Wheel upload to PyPI for each platform

**Example GitHub Actions**:
```yaml
- uses: PyO3/maturin-action@v1
  with:
    command: build
    args: --release --out dist
    manylinux: auto
```

### Installation Experience

**With pre-built wheels** (best case):
```bash
pip install mouc  # Downloads appropriate wheel, fast install
```

**Without pre-built wheels** (fallback):
```bash
pip install mouc  # Triggers Rust compilation, slower but works
# Requires: Rust toolchain (cargo) installed
```

**Mitigation**:
- Build wheels for all major platforms in CI
- Document Rust requirement for source builds
- Consider pure-Python fallback for unsupported platforms

### Dependency Impact

**New dependencies**:
- `maturin` (build-time only)
- Rust toolchain (build-time only, ~1GB)

**User impact**:
- No new runtime dependencies
- Faster installs with pre-built wheels
- Slightly larger package size (~1-2MB per platform)

## Expected Performance Improvements

### Performance Estimates

Based on typical Rust vs. Python performance characteristics:

| Workload | Tasks | Current (Python) | Estimated (Rust) | Speedup |
|----------|-------|------------------|------------------|---------|
| Small | 10-20 | <100ms | <20ms | 5x |
| Medium | 50-100 | 500ms - 2s | 50-200ms | 10x |
| Large | 200+ | 5-30s | 0.5-2s | 10-15x |
| Bounded Rollout (medium) | 50 | 2-10s | 200ms - 1s | 10-20x |

**Factors favoring Rust**:
1. **Tight loops**: Scheduling involves many iterations with simple arithmetic
2. **Sorting**: Rust's sort is highly optimized, often 3-5x faster than Python
3. **Memory allocation**: Stack allocation vs. Python heap objects
4. **No GIL**: True parallelism possible for future enhancements
5. **Cache efficiency**: Smaller data structures, better locality

**Bounded Rollout Benefits**:
- State copying is expensive in Python (deep copying dictionaries)
- Rust's `Clone` trait with stack-allocated data is much faster
- Simulation-heavy workloads see the biggest gains

### Bottleneck Analysis

**Python bottlenecks**:
- Dictionary lookups (O(1) but constant overhead ~100ns)
- List sorting (Timsort is good, but Rust's is better)
- `timedelta` arithmetic (object creation overhead)
- Function call overhead (Python's is ~100ns per call)

**Rust advantages**:
- Inline function calls (zero overhead)
- Primitive operations (i64, f64) are native CPU instructions
- No reference counting in hot loops
- SIMD auto-vectorization possible

### When Benefits Matter Most

**High-impact scenarios**:
- Large roadmaps (100+ entities with workflows = 300+ tasks)
- Bounded Rollout with frequent rollout decisions
- Tight deadlines requiring many iterations
- CI/CD pipelines running schedules frequently

**Low-impact scenarios**:
- Small roadmaps (<20 tasks)
- Infrequent scheduling runs
- I/O-bound operations (Jira sync, file writes)

## Implementation Strategy

### Phased Approach

**Phase 1: Parallel SGS Core** (2-3 weeks)
- Port `_schedule_forward()` to Rust
- Port `ResourceSchedule` class
- Basic PyO3 bindings
- Test suite port
- Benchmark comparison

**Phase 2: Full Parallel SGS** (1-2 weeks)
- Backward pass in Rust
- All prioritization strategies
- Complete feature parity
- Integration tests

**Phase 3: Bounded Rollout** (2-3 weeks)
- Port rollout simulation logic
- State copying optimization
- Rollout decision tracking
- Performance validation

**Phase 4: Optimization** (1-2 weeks)
- Profiling and hotspot identification
- Algorithmic improvements
- SIMD exploration
- Memory layout optimization

### Development Environment

**Requirements**:
- Rust toolchain (rustup)
- Python 3.10+ with development headers
- maturin for building
- Existing Mouc test suite

**Development workflow**:
```bash
# Install maturin
uv pip install maturin

# Create Rust extension structure
maturin new --mixed

# Develop with hot reload
maturin develop

# Run Python tests against Rust implementation
pytest tests/
```

### Testing Strategy

**Approach**:
1. Port existing Python tests to validate Rust implementation
2. Property-based testing (hypothesis) for edge cases
3. Fuzz testing for scheduler correctness
4. Benchmark suite for performance regression

**Validation**:
- Identical results to Python implementation (bit-for-bit)
- All existing tests pass
- Performance benchmarks show expected gains

## Risks & Trade-offs

### Technical Risks

**1. Complexity Increase**
- Mixed Python/Rust codebase harder to understand
- Two languages to maintain
- Build system complexity

*Mitigation*: Clear interface boundaries, good documentation, automated builds

**2. Build/Distribution Challenges**
- Platform-specific wheels required
- CI/CD complexity increase
- Potential install failures without Rust toolchain

*Mitigation*: Comprehensive CI matrix, pre-built wheels, fallback documentation

**3. Debugging Difficulty**
- Rust panics vs. Python exceptions
- Stack traces cross language boundary
- Less familiar tooling for Python devs

*Mitigation*: Excellent error messages, PyO3 exception handling, logging

**4. Maintenance Burden**
- Changes require updating both Python and Rust
- API stability concerns
- Version compatibility

*Mitigation*: Stable interface design, versioning policy, backward compatibility

### Benefits vs. Costs

**Benefits**:
- ✅ 5-20x performance improvement
- ✅ Better scalability for large roadmaps
- ✅ Enables more sophisticated algorithms (rollout becomes practical)
- ✅ Modern, safe language (memory safety, thread safety)
- ✅ Potential for future parallelism

**Costs**:
- ❌ Development time (~6-10 weeks initial implementation)
- ❌ Increased build complexity
- ❌ Learning curve for contributors
- ❌ Platform-specific testing requirements
- ❌ Slightly larger distribution size

### When NOT to Do This

**Skip Rust rewrite if**:
- Typical workloads are <50 tasks (speedup not meaningful)
- Team has no Rust experience and no time to learn
- Platform support is critical (exotic architectures)
- Pure-Python requirement (some deployment environments)

**Consider alternatives**:
- PyPy (JIT compilation, can be 2-5x faster, but limited library support)
- Numba (JIT for numerical code, more limited scope)
- Cython (middle ground, easier than Rust but less performance)
- Algorithmic improvements (better big-O can beat language change)

## Recommendations

### Primary Recommendation: Proceed with Prototype

**Next steps**:
1. **Create proof-of-concept** (1 week)
   - Minimal Parallel SGS in Rust
   - Basic PyO3 bindings
   - Single test case working
   - Measure actual speedup

2. **Evaluate POC results** (decision point)
   - Is speedup as expected?
   - Is implementation complexity acceptable?
   - Does it integrate cleanly?

3. **If positive, continue with Phase 1** (see Implementation Strategy)

### Alternative: Optimize Python First

Before committing to Rust:
- Profile current implementation (cProfile, line_profiler)
- Identify specific hotspots
- Try targeted optimizations:
  - Replace list sorts with heap queue for partial sorting
  - Cache computed values (CR, priorities)
  - Use `__slots__` for data classes
  - Consider NumPy for bulk operations

**Estimated gain**: 20-50% speedup with careful optimization
**Effort**: 1-2 weeks
**Risk**: Lower than Rust rewrite

### Decision Criteria

**Proceed with Rust if**:
- Profiling shows hotspots in schedulers (not I/O)
- Large roadmaps (100+ tasks) are common use case
- Team can commit to Rust maintenance
- Performance is a priority

**Stick with Python if**:
- Current performance is acceptable
- Team prefers simplicity
- Pure-Python requirement exists
- Focus is on features, not speed

## Questions to Resolve

1. **What are typical roadmap sizes?** (Need usage data to estimate real-world impact)
2. **Where is time actually spent?** (Need profiling data: scheduler vs. I/O vs. parsing)
3. **Is Bounded Rollout used in practice?** (If not, skip Phase 3)
4. **What platforms must be supported?** (Affects wheel build matrix)
5. **Who will maintain Rust code?** (Skills inventory)
6. **What's the performance budget?** (How slow is too slow?)

## Appendix: Technical Details

### Date Handling

Python's `datetime.date` maps to Rust via PyO3:

```rust
use pyo3::types::PyDate;
use chrono::NaiveDate;

// Convert Python date to Rust
let py_date: &PyDate = ...;
let year = py_date.get_year();
let month = py_date.get_month() as u32;
let day = py_date.get_day() as u32;
let rust_date = NaiveDate::from_ymd_opt(year, month, day).unwrap();
```

**Recommendation**: Use `chrono::NaiveDate` in Rust core, convert at boundaries

### Resource Schedule Optimization

Current Python uses `bisect.insort` for O(log n) insertion. Rust opportunities:

```rust
// Option 1: BTreeSet (ordered, efficient range queries)
use std::collections::BTreeSet;

// Option 2: Vec with binary search (matches Python approach)
fn add_busy_period(&mut self, start: Date, end: Date) {
    let idx = self.busy_periods.binary_search(&(start, end))
        .unwrap_or_else(|e| e);
    self.busy_periods.insert(idx, (start, end));
}

// Option 3: Optimize common case (append to end)
fn add_busy_period(&mut self, start: Date, end: Date) {
    if self.busy_periods.last().map_or(true, |&(_, last_end)| start > last_end) {
        self.busy_periods.push((start, end));  // O(1)
    } else {
        // Fall back to binary search insertion
    }
}
```

### Parallel Execution Potential

Future optimization: parallelize rollout simulations

```rust
use rayon::prelude::*;

// Run multiple rollout scenarios in parallel
let scores: Vec<f64> = scenarios
    .par_iter()
    .map(|scenario| evaluate_scenario(scenario))
    .collect();
```

**Note**: Initial implementation should be single-threaded for simplicity

---

**End of Investigation Report**
