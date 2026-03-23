# GlassyTrade AI — Test Coverage Map

**Date:** 2026-03-23

## Test Suites

| File | Tests | Covers |
|------|-------|--------|
| `tests/validation/test_amt_stability_fixes.py` | 22 | All 8 stability fixes + P1 fixes |
| `tests/validation/test_amt_validation.py` | 13 | AMT integration scenarios |
| `tests/unit/domain/test_aggression_scorer.py` | 18 | AggressionScorer + PersistentAggressionScorer |
| `tests/unit/domain/test_market_state_engine.py` | 18 | Market state detection |
| `tests/unit/domain/test_gate_pipeline.py` | 19 | 12-gate sequential validation |
| `tests/unit/domain/test_amt_analyzer.py` | 42 | AMTAnalyzer full integration |
| `tests/unit/domain/test_market_structure_classifier.py` | 12 | Structure classification + hysteresis |
| `tests/unit/domain/test_footprint_analyzer.py` | 39 | Footprint analysis |
| `tests/unit/domain/test_drive_tracker.py` | 14 | Drive detection |
| `tests/unit/domain/test_orderflow_detectors.py` | 16 | Order flow patterns |
| `tests/unit/domain/test_entry_gate.py` | 34 | Three-Align gate + entry signals |
| `tests/unit/test_signal_tracking_service.py` | 11 | Signal tracking + decision history |

## What Is Covered

| Component | Test Coverage | Notes |
|-----------|--------------|-------|
| AggressionScorer | FULL | Static scoring, breakdown, direction_sign |
| PersistentAggressionScorer | FULL | Persistence filter, streak reset, raw history |
| CVDTracker | FULL | Slope computation, sign persistence, session reset |
| MarketStateEngine | FULL | BALANCED/IMBALANCED/PROBING/NO_TRADE transitions |
| MarketStructureClassifier | FULL | 5-state classification, hysteresis parameters |
| LVNPersistenceTracker | FULL | Candidate/promotion/removal lifecycle |
| GatePipeline | FULL | All 12 gates individually + sequential flow |
| EntryGate | FULL | Three-Align check, confirmation bundle, momentum fade |
| FootprintAnalyzer | FULL | Delta profiles, stacked imbalances, absorption |
| SignalTrackingService | FULL | Track/block/wait, history retrieval, DB persistence |
| AMTAnalyzer | FULL | Profile construction, LVN/HVN, state detection, cross-validation |
| PROBING Playbook | FULL | Acceptance/rejection, VWAP context, aggression gating |
| Universal Delta Gate | FULL | Delta=0 blocking, CVD contradiction blocking |

## What Is Missing

| Gap | Risk | Priority |
|-----|------|----------|
| Agent pipeline integration tests | Direction/timing decisions untested | HIGH |
| LLM entry handler integration | Prompt building + parsing untested | MEDIUM |
| Overseer handler tests | Position management decisions untested | MEDIUM |
| Paper broker adapter tests | Order execution untested | MEDIUM |
| End-to-end tick flow | Full pipeline untested | LOW |
| Watchdog manager tests | SL/TP monitoring untested | LOW |

## Critical Behaviors Protected by Tests

1. **Delta Score Persistence** — `test_confirmed_requires_persistence` ensures 3-bar filter
2. **CVD Slope Stability** — `test_slope_sign_persists` ensures sign lock
3. **PROBING+BALANCE Override** — `test_probing_overrides_balance_structure` ensures cross-validation
4. **PROBING Playbook** — `test_probing_acceptance_blocked_by_vwap_context` ensures VWAP gating
5. **LVN Stability** — `test_lvn_requires_persistence` ensures 3-bar emission delay
6. **Structure Hysteresis** — `test_hysteresis_parameters_increased` ensures dwell/cooldown=3
7. **Footprint Alignment** — `test_footprint_confirmed_requires_both_conditions` ensures dual gating
8. **Decision History** — `test_get_recent_decisions_extended_limit` ensures 1000-entry support
9. **Gate Pipeline** — All 12 gates individually tested for pass/fail conditions
10. **Three-Align Gate** — Market state + location + confirmation bundle validation
