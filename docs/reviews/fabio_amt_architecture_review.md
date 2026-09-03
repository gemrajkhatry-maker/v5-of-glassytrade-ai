# Fabio AMT Architecture Review — Consolidated Deliverables

> Maps the 16 review deliverables to concrete modules, tests, and documentation.
> Generated from the end-to-end architecture review of the Fabio AMT deterministic trading system.

## Deliverable Matrix

| # | Deliverable | Location | Status |
|---|------------|----------|--------|
| 1 | Current architecture | `docs/architecture/fabio_amt_deterministic_flow.md` | Documented |
| 2 | Actual end-to-end execution flow | `docs/architecture/fabio_amt_deterministic_flow.md` §1 | Documented with code references |
| 3 | Fabio AMT strategy implementation map | `docs/amt/fabio_decision_pipeline.md` | Documented |
| 4 | Strategy rules mapped to actual code | `docs/amt/fabio_decision_pipeline.md` + `tests/quant/decision/test_gate_pipeline_matrix.py` | Documented + 24 tests |
| 5 | Duplicate implementations | `quant/event_store.py` — removed duplicate `_event_to_dict` | Fixed |
| 6 | Redundant components | `docs/architecture/fabio_amt_deterministic_flow.md` §6 | Documented (StateProjector deprecated as position authority) |
| 7 | Unused/dead functionality | Identified via code analysis | StateProjector marked deprecated; no dead code removed yet |
| 8 | Incorrect or inconsistent logic | `quant/runtime.py` startup_reconcile comments | Fixed |
| 9 | State and lifecycle problems | `quant/runtime.py` restore_position + startup_reconcile | Fixed (comments aligned with behavior) |
| 10 | Concurrency/race-condition risks | `docs/architecture/fabio_amt_deterministic_flow.md` §4 + `docs/amt/multi_symbol_isolation.md` | Documented; bounded ThreadPool + lifecycle locks |
| 11 | Multi-symbol isolation problems | `docs/amt/multi_symbol_isolation.md` + `tests/quant/coordinator/test_multi_symbol_isolation.py` | Documented + 9 tests |
| 12 | Testing coverage and results | This document §Test Coverage | 1644 tests pass, 57 new tests added |
| 13 | Simplified target architecture | `docs/architecture/fabio_amt_deterministic_flow.md` §7 | Documented |
| 14 | Target end-to-end flow | `docs/architecture/fabio_amt_deterministic_flow.md` §1 | Documented |
| 15 | Clear ownership of every major responsibility | `docs/architecture/fabio_amt_deterministic_flow.md` §6 | Responsibility map table |
| 16 | Refactoring/removal plan in execution order | This document §Implementation Order | Below |

## Key Findings

### Confirmed

1. **EventStore is the single source of truth.** All state derives from `fold()`. `EngineState` is immutable. `StateProjector` is a live cache only — never a position authority.
2. **Decision pipeline is 100% deterministic.** The 4-gate `GatePipeline` (session → position/cooldown → Triple-A edge → R:R) is the sole decision authority. LLMAdvisor never gates entries.
3. **One engine per symbol with strict isolation.** Each `QuantEngine` owns its own EventStore, EngineState, PositionManager, SessionRisk, and AMTEngine. Cross-engine coupling is limited to `PortfolioRiskAuthority`.
4. **Duplicate `_event_to_dict` removed.** Two identical definitions existed in `EventStore`; the redundant one has been removed.

### Fixed in This Review

| Issue | File | Change |
|-------|------|--------|
| LLMAdvisor always wired in live path | `quant/multi_engine.py` | Added `advisor_enabled` config gate (default `False`) |
| Duplicate `_event_to_dict` | `quant/event_store.py` | Removed second definition |
| Misleading `startup_reconcile` comments | `quant/runtime.py` | Updated to reflect `restore_position` seeding behavior |
| Snapshot fold failure log at DEBUG | `quant/multi_engine.py` | Restored to WARNING |

### Test Coverage Added

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/quant/integration/test_e2e_deterministic_flow.py` | 6 | Full E2E flow: ticks → EventStore → fold → state parity |
| `tests/quant/decision/test_gate_pipeline_matrix.py` | 24 | All 4 gates + DecisionService.evaluate() + VA-fade |
| `tests/quant/coordinator/test_multi_symbol_isolation.py` | 9 | Per-symbol isolation, determinism, event ordering |
| `tests/quant/replay/test_event_store_replay_integration.py` | 8 | Export/import JSONL round-trip, prune, replay parity |
| `tests/quant/llm/test_advisor_wiring_config.py` | 10 | Advisor env gating, engine with no advisor, factory seam |
| **Total** | **57** | |

## Implementation Order

The changes were applied in risk-ordered phases:

```
Phase 1: Documentation (zero risk)
  ├── docs/architecture/fabio_amt_deterministic_flow.md
  ├── docs/amt/fabio_decision_pipeline.md
  └── docs/amt/multi_symbol_isolation.md

Phase 2: Tests (zero risk to production)
  ├── tests/quant/integration/test_e2e_deterministic_flow.py
  ├── tests/quant/decision/test_gate_pipeline_matrix.py
  ├── tests/quant/coordinator/test_multi_symbol_isolation.py
  ├── tests/quant/replay/test_event_store_replay_integration.py
  └── tests/quant/llm/test_advisor_wiring_config.py

Phase 3: Config change (minimal production change)
  └── quant/multi_engine.py — advisor_enabled config gate (default False)

Phase 4: Correctness fixes (after tests lock down behavior)
  ├── quant/event_store.py — removed duplicate _event_to_dict
  ├── quant/runtime.py — fixed startup_reconcile comments
  └── quant/multi_engine.py — restored snapshot fold log to WARNING

Phase 5: Consolidated deliverables (this document)
```

## Verification

All changes verified by the full quant test suite:

```
1644 passed, 7 skipped, 0 failed
```

The 7 skipped tests are pre-existing (unrelated to this review):
- Zone classification boundary change
- Option scanner NFO auto-detect
- Crash recovery torn-state probe
- Deleted function coverage
- Missing parquet fixtures
- Unfilled scenario risk math

## Remaining Work (Future Phases)

1. **Fabio AMT rule-level test suite**: Expand `test_gate_pipeline_matrix.py` to cover every AMT setup type (Triple-A, LVN Sniper, Second Drive, Initiative Breakout, Squeeze Retest) with synthetic bar sequences.
2. **Aggressive abstraction removal**: With tests in place, evaluate removing deprecated `StateProjector` as a position authority, consolidating remaining legacy paths.
3. **Performance benchmarking**: Profile AMT analysis per-bar cost, EventStore fold overhead, and WS snapshot latency under multi-symbol load.
4. **Backtest/replay harness integration**: Wire `EventStore.export_to_jsonl()` into the replay driver for full session replay from JSONL logs.
