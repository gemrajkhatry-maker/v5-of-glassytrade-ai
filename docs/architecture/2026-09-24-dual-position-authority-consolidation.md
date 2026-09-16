# Dual Position Authority — Consolidation Design

**Date:** 2026-09-24
**Status:** Proposal (not yet implemented)
**Scope:** `quant/runtime.py`, `quant/position_manager.py`, `quant/state_machine.py`, `quant/transitions.py`, `quant/multi_engine.py`

---

## 1. Problem Statement

QuantEngine maintains two independent representations of "is there an open position, and what is it":

| Authority | Location | Type | How it changes |
|---|---|---|---|
| **Event-sourced state** | `engine.state.position` (a frozen `PositionState`) | Immutable value object, derived by folding events through `apply_event()` | Updated in `_emit()` via `self.state = apply_event(self.state, event)` |
| **Execution book** | `pm.current_position` (a mutable `Position`) | Live execution object used by OMS calls | Set directly: `pm.current_position = position` or `pm.current_position = remaining` |

These two can disagree. The coordinator's `_engine_has_open_position()` (multi_engine.py:295-333) exists specifically because neither alone is trustworthy — it probes `engine.state.position` first, then falls back to `pm.current_position` for stubs. The `startup_reconcile()` method (runtime.py:1810-1855) contains explicit branches for when the two disagree after restart. The `periodic_reconcile()` method (runtime.py:1874-1961) checks for drift between them every 120 seconds.

**This is not a theoretical concern.** The codebase contains extensive documentation explaining how they diverge and multiple probes to detect the divergence. The divergence is a known architectural weakness.

---

## 2. Root Cause Analysis

### 2.1 How they get out of sync during restart

The restart flow is:

1. **Coordinator** calls `PaperPositionReconciler` to classify persisted positions against the active universe.
2. For each open position row, `engine.restore_position(row_to_position(row))` is called (multi_engine.py:1911).
3. `restore_position()` (runtime.py:700-715) does THREE things:
   - Sets `pm.current_position = position` (execution book)
   - Sets `self.state = self.state.with_position(_position_to_state(position))` (event-sourced state)
   - Appends a synthetic `PositionOpened` event to the `EventStore`
4. Later, `engine.startup_reconcile()` (runtime.py:1810-1855) folds the EventStore and rebuilds `self.state` from scratch.

The divergence scenarios:

- **EventStore fold yields a position but pm is flat**: The fold sees the synthetic `PositionOpened` but nobody restored the execution Position object into `pm.current_position`. This happens when the event store has events from a prior run but the coordinator's reconciliation classified the position as quarantined.
- **pm has a position but fold yields none**: The fold's `PositionOpened` event was pruned, or the EventStore was cleared between runs. The execution book was restored from storage but the event log has no matching event.
- **Partial fills**: A `PositionReduced` event updates `engine.state.position.size` via the fold, but `pm.current_position` is updated separately by `manage_exit()` returning the remaining position. If an event fails to append (persistence failure), the fold won't see the reduction but `pm` already adopted the smaller size.

### 2.2 Why two authorities exist

The split is not accidental — it reflects two genuinely different concerns:

- **`engine.state.position`** (event-sourced): An immutable, auditable, reproducible record of what happened. Used for WS snapshots, periodic reconciliation, and the decision context. It is a *projection* — a reduced-size `PositionState` that lacks the full execution `Position` object (no order details, no costs, no reference to the OMS).

- **`pm.current_position`** (execution book): The live, mutable object that OMS calls (`close()`, `close_partial()`, `add_pyramid()`) operate on. It carries the full execution state: order/signal, costs, pyramid level, realized PnL, trail state references. It is the *operational* truth.

The event-sourced state cannot replace the execution book because it lacks the data OMS methods need. The execution book cannot replace the event-sourced state because it is not auditable, reproducible, or tamper-evident.

---

## 3. Analysis: Which Should Be the Authority?

### 3.1 Option A: Event-sourced state as sole authority

**What this means:** `engine.state.position` is the single source of truth. `pm.current_position` becomes a derived cache that is always consistent with the event-sourced state.

**Pros:**
- Full audit trail (tamper-evident checksum chain)
- Reproducible (same events -> same state)
- Already the basis for WS snapshots and periodic reconciliation
- Aligns with the documented architecture ("EventStore is the source of truth")

**Cons:**
- `PositionState` is a reduced projection — it lacks order/signal details, costs, and the full Position object that OMS methods require
- OMS calls need the live `Position` object (with `_id`, `order.signal`, `open_price`, etc.) — the fold cannot provide this
- Would require the EventStore to carry full `Position` objects (it already does in the event payload, but the folded `PositionState` discards most of the data)
- Every OMS operation would need to re-derive the Position from the event stream, or maintain a separate index

**Verdict:** Not practical without significant rework of the Position type system. The fold produces a summary, not the operational object.

### 3.2 Option B: PositionManager as sole authority

**What this means:** `pm.current_position` is the single source of truth. `engine.state.position` becomes a derived projection that is always consistent with the execution book.

**Pros:**
- `pm.current_position` IS the operational truth — OMS calls use it directly
- Already carries all the data needed for execution (order, signal, costs, trail state)
- Simpler mental model: the thing that executes IS the authority
- No need for `_engine_has_open_position()` to probe two sources

**Cons:**
- Not auditable (no checksum chain, no tamper evidence)
- Not reproducible (cannot replay from events)
- Loses the event-sourcing benefits for position state
- The WS snapshot currently uses `EventStore.fold()` for position data — switching to pm would change the snapshot composition path

**Verdict:** Operationally simpler but sacrifices the audit/reproducibility guarantees that event sourcing provides.

### 3.3 Option C (Recommended): PositionManager as execution authority, EventStore as audit authority — with enforced consistency

**What this means:** Both continue to exist, but with a clear hierarchy:
- `pm.current_position` is the **execution authority** — it is what the OMS operates on
- `EventStore` is the **audit authority** — it is the reproducible record
- `engine.state.position` is a **derived projection** — it MUST always be consistent with `pm.current_position`
- Consistency is enforced at the point of mutation, not detected after the fact

**Pros:**
- Preserves both audit trail and operational correctness
- Clear ownership: mutations go through pm, events are emitted as a consequence, state is folded as a result
- Eliminates the divergence scenarios by construction
- Minimal rework — the existing flow is close to this already

**Cons:**
- Still two things to reason about (but with a clear hierarchy)
- Requires discipline to maintain the invariant

---

## 4. Recommended Solution: Enforced Consistency (Option C)

### 4.1 Core Invariant

**After any position mutation, `engine.state.position` MUST be consistent with `pm.current_position`.**

Specifically:
- `pm.current_position is None` iff `engine.state.position is None`
- `abs(pm.current_position.size - engine.state.position.size) < epsilon`
- Pyramid counts agree: `len(pm.pyramid_positions) == len(engine.state.pyramids)`

This invariant must hold at every observable boundary (bar close, tick, snapshot, reconcile check).

### 4.2 Why They Currently Diverge

The divergence happens because mutations to `pm.current_position` and `engine.state` are performed independently in several places:

| Site | pm mutation | state mutation | Gap |
|---|---|---|---|
| Entry (`_translate_and_submit`) | `pm.current_position = position` (runtime.py:1353) | Via `_emit(PositionOpened)` -> `apply_event` (runtime.py:1798) | If `event_appender.append()` fails, the event is NOT in the store, but `_emit()` still calls `apply_event` (runtime.py:1798) — so state IS updated. Divergence only if the event is never emitted at all. |
| Bar exit (`_manage_exit`) | `pm.current_position = remaining` (runtime.py:1660) | Via `_emit(PositionClosed/Reduced)` -> `apply_event` | Same as above — state follows events, pm is set independently |
| Tick exit (`_manage_tick_exit`) | `pm.current_position = remaining` (runtime.py:925) | `self.state = self.state.with_position(None)` (runtime.py:929) | **Direct state mutation** bypasses the event fold — this is a special case where state is set directly |
| Restore (`restore_position`) | `pm.current_position = position` (runtime.py:703) | `self.state = self.state.with_position(...)` (runtime.py:704) | Both set explicitly — consistent at restore time, but `startup_reconcile()` later rebuilds state from fold |
| Startup reconcile | No pm mutation | `self.state = EngineState(...)` (runtime.py:1847-1855) | State is rebuilt from fold; pm is NOT touched — if fold disagrees with pm, they diverge |

The critical insight: **the tick exit path (runtime.py:928-929) directly mutates `self.state` without going through the event fold.** This is the clearest violation of the event-sourcing invariant.

### 4.3 Refactoring Plan

#### Phase 1: Eliminate direct state mutations (LOW RISK)

Remove all direct `self.state = self.state.with_position(...)` calls outside of `_emit()`. There is exactly one: `_manage_tick_exit` at runtime.py:928-929.

**Change:** Replace the direct mutation with a no-op — the state will be updated by the `PositionClosed` event that `_book_full_close()` -> `_emit()` triggers. If no event is emitted (because `_book_full_close` doesn't emit one directly), emit one explicitly.

**Risk:** Low. The tick exit path already emits `PositionClosed` via `_execute_full_close` -> `_emit`. The direct state mutation is redundant.

**Verification:** Existing tests for tick-level exits already assert position state after close.

#### Phase 2: Unify the restore + reconcile flow (MEDIUM RISK)

Currently `restore_position()` sets both pm and state, then `startup_reconcile()` rebuilds state from the fold. If the fold disagrees with pm, the reconcile method has ad-hoc resolution logic.

**Change:** Make `startup_reconcile()` the sole authority for post-restore state. After the fold:
- If fold says positioned and pm is flat: restore the position into pm from the fold's data (or from storage if the fold's position is a reduced `PositionState` that lacks execution data)
- If fold says flat and pm is positioned: this is a genuine anomaly — log at CRITICAL and adopt pm's book (the broker-facing truth), then emit a compensating `PositionOpened` event to bring the store in sync
- If both say positioned but sizes differ: adopt pm's size (broker truth), emit a `PositionReduced` compensating event

**Key principle:** The execution book (pm) is the broker-facing truth. When the event store disagrees, we trust the broker and emit compensating events to bring the store in line.

**Risk:** Medium. The restore flow is critical for restart correctness. Must be tested with:
- Normal restart (position open, event store intact)
- Restart with pruned event store
- Restart with corrupted event store (checksum chain broken)
- Restart with no event store (fresh process)

#### Phase 3: Add a consistency assertion (LOW RISK)

Add a method `_assert_position_consistency()` that checks the invariant (section 4.1) and call it at:
- End of every bar (after `_manage_exit` and `_check_thesis_flip`)
- End of every tick exit (after `_manage_tick_exit`)
- Before every snapshot composition
- During periodic reconcile (replace the current drift detection with a hard assertion in test mode, soft warning in production)

**Risk:** Low. Assertions are diagnostic — they detect problems, they don't cause them.

#### Phase 4: Simplify `_engine_has_open_position()` (LOW RISK)

Once consistency is enforced, `_engine_has_open_position()` only needs to check ONE source. The recommended source is `engine.state.position` (the event-sourced state) because:
- It is always available (EngineState is constructed in `__init__`)
- It does not require lazy-initializing the PositionManager
- It is the projection the WS snapshot already uses

The fallback to `pm.current_position` can be removed once Phase 3's assertions prove the two never disagree in practice.

**Risk:** Low, provided Phase 3 runs for a release cycle without finding discrepancies.

### 4.4 What NOT to Do

- **Do NOT merge PositionManager into EngineState.** The execution book needs mutable, rich Position objects. Freezing them into PositionState for the fold and then unfreezing for OMS calls would add complexity without benefit.
- **Do NOT make EventStore the sole authority for execution.** OMS methods need live Position objects with order/signal/costs. The fold produces a summary.
- **Do NOT remove the EventStore.** It provides tamper-evident audit, reproducibility, and determinism verification that the execution book cannot.
- **Do NOT add a third authority.** The solution is consolidation, not another layer.

---

## 5. Migration Safety

### 5.1 Restart/Reconciliation Flow (Target State)

```
Process starts
  |
  v
Coordinator scans contracts, spawns engines
  |
  v
For each engine with persisted positions:
  engine.restore_position(position)
    -> pm.current_position = position
    -> EventStore seeded with PositionOpened
    -> engine.state updated (provisional)
  |
  v
engine.startup_reconcile()
  -> fold = event_store.fold()
  -> if fold.position and pm.current_position:
       verify consistency; if sizes differ, emit compensating event
  -> if fold.position and not pm.current_position:
       CRITICAL log; adopt fold into pm (if possible) or mark unresolved
  -> if not fold.position and pm.current_position:
       CRITICAL log; emit compensating PositionOpened to align store
  -> engine.state = fold (with any compensating events applied)
  |
  v
Trading resumes — consistency invariant enforced at every mutation
```

### 5.2 Backward Compatibility

- The `restore_position()` API does not change — it still accepts a Position object
- The `startup_reconcile()` API does not change — it is still called once before trading
- The `_engine_has_open_position()` function continues to work (initially checking both, then simplified)
- WS snapshot composition does not change — it continues to use `EventStore.fold()`
- Periodic reconcile becomes simpler (can assert rather than detect)

### 5.3 Rollback Plan

Each phase is independently reversible:
- Phase 1 (remove direct state mutation): revert the single-line change
- Phase 2 (unify restore/reconcile): revert to the current ad-hoc logic
- Phase 3 (consistency assertion): remove the assertion calls
- Phase 4 (simplify probe): restore the fallback logic

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Removing direct state mutation in tick exit breaks a test | Low | Low | Tests already assert post-close state via events; fix any that relied on the direct mutation |
| Compensating events in restart flow confuse the audit trail | Medium | Medium | Compensating events are clearly labeled (reason="RESTART_RECONCILE") and logged at WARNING |
| Consistency assertion fires in production | Low | Medium | Phase 3 starts with logging-only (no halt); escalate to halt after a bake period |
| Simplifying `_engine_has_open_position` misses an edge case | Low | High | Keep the dual-probe for one release cycle; only simplify after zero assertions fire |
| EventStore fold fails (corruption) and pm has the real position | Low | High | pm is the broker-facing truth; always trust it over a failed fold |

---

## 7. Success Criteria

1. `_engine_has_open_position()` only needs to check one source (no fallback)
2. `startup_reconcile()` has no "adopt from pm" branches — the fold and pm always agree
3. `periodic_reconcile()` never reports position drift between pm and state
4. No direct `self.state = self.state.with_position(...)` calls outside `_emit()`
5. All existing tests pass without modification (or with minimal, clearly-scoped changes)
6. A restart with a corrupted event store still produces correct position state

---

## 8. Implementation Priority

| Phase | Effort | Risk | Value | Priority |
|---|---|---|---|---|
| Phase 1: Remove direct state mutation | 1 hour | Low | Eliminates one divergence path | **P0 — do first** |
| Phase 3: Add consistency assertion | 2 hours | Low | Makes future divergence visible | **P0 — do second** |
| Phase 2: Unify restore/reconcile | 4 hours | Medium | Eliminates the restart divergence | **P1 — do third** |
| Phase 4: Simplify probe | 1 hour | Low | Cleans up the symptom | **P2 — do last** |

Total estimated effort: ~1 day of focused work, plus test verification.

---

## 9. Summary

The dual position authority is a real architectural weakness but not an emergency. The two authorities serve genuinely different purposes (audit vs. execution) and both must continue to exist. The fix is not to choose one and eliminate the other, but to enforce consistency between them at every mutation point.

The recommended approach:
1. **PositionManager is the execution authority** — it is what OMS operates on and what the broker sees
2. **EventStore is the audit authority** — it is the tamper-evident, reproducible record
3. **engine.state.position is a derived projection** — it must always be consistent with pm, and consistency is enforced at mutation time, not detected after the fact
4. **When they disagree at restart, trust the broker** (pm) and emit compensating events to align the store

This preserves the benefits of event sourcing (audit, reproducibility, determinism) while eliminating the divergence that currently requires probe functions and reconciliation patches.
