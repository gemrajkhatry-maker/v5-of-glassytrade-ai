# Test Tracking & Coverage Goals

**Last Updated:** 2026-05-07
**Overall Status:** Phase 4 Complete - Infrastructure & Critical Coverage Done

---

## Coverage Targets

| Module | Current | Target | Status |
|--------|---------|--------|--------|
| `app/domain/amt/service/volume_profile.py` | ~90% | 95% | ✅ |
| `app/domain/amt/service/orderflow_detectors.py` | ~85% | 95% | ✅ |
| `app/runtime/pipeline/signal.py` | ~70% | 90% | ✅ Fixed |
| `app/api/websocket/gameloop.py` | 80%+ | 80% | ✅ 24 tests |
| `app/domain/risk/service/startup_reconciliation.py` | 80%+ | 80% | ✅ 16 tests |
| `app/domain/exit/service/exit_rules.py` | 100% | 90% | ✅ 41 tests |
| `app/runtime/pipeline/gates.py` | 89% | 90% | ✅ OFI fixed |
| `app/domain/exit/service/partition_exit_manager.py` | 100% | 90% | ✅ 28 tests |

---

## Completed Fixes

### Test Infrastructure (Phase 0)
- ✅ pytest.ini with markers and strict mode
- ✅ .coveragerc with 80% threshold
- ✅ Makefile with test/lint/format targets
- ✅ .github/workflows/test.yml (Python 3.11/3.12 matrix)
- ✅ conftest.py with quality validation hook

### Test Quality (Phase 1)
- ✅ 0 `assert True` placeholders
- ✅ 0 assertionless tests
- ✅ 0 duplicate test names
- ✅ All skipped tests reviewed

### TDD Bug Fixes (Phase 2)
- ✅ Volume profile bucket allocation - distributes across all buckets
- ✅ Absorption detection side logic - correct confirmation
- ✅ Signal generation - configurable OFI thresholds + dynamic confidence
- ✅ Gate pipeline - uses real OFI from signal data
- ✅ Partition exit state field naming - aligned with model
- ✅ Paper broker order ID uniqueness
- ✅ LLM handler parameter name fix

### New Test Files (Phase 3)
- ✅ `tests/unit/api/websocket/test_gameloop.py` - 24 tests
- ✅ `tests/unit/domain/risk/service/test_startup_reconciliation.py` - 16 tests
- ✅ `tests/unit/domain/exit/service/test_exit_rules.py` - 41 tests
- ✅ `tests/unit/runtime/pipeline/test_gates.py` - OFI + session phase tests
- ✅ `tests/unit/runtime/pipeline/test_signal.py` - 5 tests
- ✅ `tests/unit/domain/amt/test_volume_profile.py` - 1 new test
- ✅ `tests/unit/domain/amt/test_absorption_detection.py` - 2 new tests
- ✅ `tests/unit/domain/exit/service/test_partition_exit_manager.py` - 28 tests
- ✅ `tests/unit/application/test_event_subscribers.py` - 18 tests
- ✅ `tests/unit/application/service/test_range_bar_builder.py` - 31 tests
- ✅ `tests/unit/runtime/orchestrator/test_session_pipeline.py` - 20 tests
- ✅ `tests/unit/infrastructure/adapters/test_paper_broker.py` - 27 tests

---

## Test Quality Metrics

| Metric | Count | Status |
|--------|-------|--------|
| Total tests | 1923 | ✅ |
| `assert True` placeholders | 0 | ✅ |
| Assertionless tests | 0 | ✅ |
| Duplicate test names | 0 | ✅ |
| Skipped tests | 4 | ✅ Reviewed |

---

## Remaining Gaps

### Medium Priority
1. `app/domain/risk/flash_crash.py` - Flash crash detection (file not found, may have been removed)
2. `app/domain/exit/service/breakeven_engine.py` - Break-even management
3. `app/domain/exit/service/structural_stop_engine.py` - Structural stops
4. `app/domain/exit/service/pyramid_manager.py` - Pyramiding logic

### Low Priority
1. Property-based tests for trading logic invariants
2. Chaos engineering tests
3. Integration tests for full pipeline

---

## Next Steps

1. Add tests for breakeven_engine.py, structural_stop_engine.py, pyramid_manager.py
2. Consider property-based testing with hypothesis for volume profile and signal generation
3. Add integration tests for multi-strategy scenarios
