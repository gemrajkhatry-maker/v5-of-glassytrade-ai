# Test Tracking & Coverage Goals

**Last Updated:** 2026-05-07
**Overall Status:** In Progress

---

## Coverage Targets

| Module | Current | Target | Status |
|--------|---------|--------|--------|
| `app/domain/amt/service/volume_profile.py` | ~90% | 95% | ✅ |
| `app/domain/amt/service/orderflow_detectors.py` | ~85% | 95% | ✅ |
| `app/runtime/pipeline/signal.py` | ~70% | 90% | ✅ Fixed |
| `app/api/websocket/gameloop.py` | 0% | 80% | ✅ Added 24 tests |
| `app/domain/risk/service/startup_reconciliation.py` | 0% | 80% | ✅ Added 16 tests |
| `app/domain/exit/service/exit_rules.py` | ~60% | 90% | ⏳ |

---

## Completed Fixes

### Test Quality (Phase 1)
- ✅ Fixed 9 `assert True` placeholders
- ✅ Enhanced conftest.py with shared fixtures

### TDD Bug Fixes (Phase 2)
- ✅ Volume profile bucket allocation - distributes across all buckets
- ✅ Absorption detection side logic - correct confirmation
- ✅ Signal generation - configurable OFI thresholds + dynamic confidence

### New Test Files (Phase 3)
- ✅ `tests/unit/api/websocket/test_gameloop.py` - 24 tests
- ✅ `tests/unit/domain/risk/service/test_startup_reconciliation.py` - 16 tests
- ✅ `tests/unit/runtime/pipeline/test_signal.py` - 5 tests
- ✅ `tests/unit/domain/amt/test_volume_profile.py` - 1 new test
- ✅ `tests/unit/domain/amt/test_absorption_detection.py` - 2 new tests

---

## Remaining Gaps

### Critical (Untested)
1. `app/domain/exit/service/exit_rules.py` - Exit classification logic
2. `app/runtime/pipeline/gates.py` - Hardcoded OFI values (known bug)
3. `app/domain/exit/service/partition_exit_manager.py` - Field naming bug (known)

### Medium Priority
1. `app/domain/risk/flash_crash.py` - Flash crash detection
2. `app/domain/exit/service/breakeven_engine.py` - Break-even management
3. `app/domain/exit/service/structural_stop_engine.py` - Structural stops

### Low Priority
1. `app/domain/exit/service/pyramid_manager.py` - Pyramiding logic
2. Property-based tests for trading logic
3. Chaos engineering tests

---

## Test Quality Metrics

| Metric | Count | Status |
|--------|-------|--------|
| Total tests | ~1970+ | ✅ |
| `assert True` placeholders | 0 | ✅ Fixed |
| Assertionless tests | ~19 | ⏳ Needs fix |
| Duplicate test names | ~70+ | ⏳ Needs fix |
| Skipped tests | ~36 | ⏳ Review needed |

---

## Next Steps

1. Fix remaining 19 assertionless tests
2. Fix 70+ duplicate test names
3. Add tests for exit_rules.py
4. Fix gate pipeline hardcoded OFI values
5. Fix partition exit state field naming
