# ADR-0004: Keep SessionCache as Centralized Locking Layer

Date: 2026-05-01
Status: DECIDED

## Context

`SessionCache` (`backend/app/application/services/session_cache.py`) is a shallow module with 39 methods, most of which are 1-2 lines delegating to `SessionState` with locking.

### Shallowness Analysis

- **Interface**: 39 methods
- **Implementation**: 39 × 1-2 line delegations with `with self._session._lock:`
- **Shallow by metric**: interface complexity ≈ implementation complexity

### Deletion Test

If we delete SessionCache:
- 39 methods × ~15 call sites = locking logic spreads to 39+ places
- Complexity (centralized locking) **reappears across N callers**
- SessionCache **earns its keep** through centralized locking

## Decision

We will **keep SessionCache** as-is.

### Why Not Absorb into SessionState?

1. **SessionState is a `@dataclass`** — adding 39 methods violates the spirit of a data class
2. **Centralized locking is valuable** — all state access goes through one layer
3. **Refactoring cost is high** — 39+ call sites need updating
4. **No real seam exists** — only one "adapter" (the cache itself)
   - Per the improve-codebase-architecture skill: "One adapter = hypothetical seam. Two adapters = real seam."
   - Since there's only one adapter, the seam is hypothetical — not worth refactoring yet

## Consequences

### Positive

1. **Centralized locking**: All thread-safe state access goes through one layer
2. **No refactoring risk**: Callers don't need updating
3. **Clear responsibility**: SessionCache = locking, SessionState = data

### Negative

1. **Shallow interface**: 39 methods is a large interface
2. **Extra layer**: One more jump when tracing code

### Mitigations

1. **Section comments**: Group related methods (already done)
2. **Keep as-is**: When a second adapter appears (e.g., a test mock), THEN refactor

## Future Work

If a second adapter appears (e.g., `MockSessionCache` for testing), then:
1. Create a proper interface (Protocol)
2. Refactor SessionState to implement the interface
3. Eliminate the pass-through methods

Until then, SessionCache earns its keep through centralized locking.

## References

- Improve Codebase Architecture skill (Candidate 1: SessionCache)
- ARCHITECTURE_REFACTORING_PLAN.md
