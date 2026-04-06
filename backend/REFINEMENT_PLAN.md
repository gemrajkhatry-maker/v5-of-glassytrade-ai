# Refinement Plan — Quick Wins

> **Context:** After Phase 0-1 completion (1735 passing, 1915 collected)
> **Date:** 2026-04-02
> **Status:** Prioritized list of remaining improvements that don't require major restructuring

---

## Quick Wins (Low Risk, High Value)

### 1. [✅ DONE] Domain → Config Layer Inversions (2 files)

Both `option_scanner.py` and `vp_contract_selector.py` import `settings` just to get `SCANNER_UNDERLYINGS`. Both already have try/except ImportError guards with sensible defaults.

**Fix:** Add an optional `default_underlyings: list[str]` parameter to the constructor. Pass it from ServiceGraph. This makes the imports unnecessary and eliminates the layer violation cleanly.

**Effort:** 30 minutes per file

**Impact:** Removes 2 import-linter exemptions

---

### 2. [✅ DONE] Property Forwards for Test Compatibility (trading_session.py)

The tests access `svc._sessions`, `svc._session_eviction_interval`, etc. which live on `SessionStateManager`, not `TradingSessionService`. We added property forwards so test code works without modification. This is **already done**.

---

### 3. [✅ DONE] Duplicate Code Eliminated

- `_depth_to_dto()` extracted to `shared/depth_dto.py` — DONE
- Duplicate R:R line in `entry_gate.py` removed — DONE
- IST timezone constant created at `shared/timezones.py` — DONE (can be adopted by 5+ files in future cleanup)

---

### 4. Dead Imports Cleanup (Low Risk)

Scan for `import` statements that are no longer used after our refactoring:

| Module | Unused import to remove |
|--------|----------------------|
| `entry_coordinator.py` | `EventBusPort` (removed) |
| `llm_entry_handler.py` | `EventBusPort` (removed) |
| `llm_overseer_handler.py` | `EventBusPort` (removed) |
| `post_trade_analyst.py` | `EventBusPort` (removed) |
| `trading_session.py` | `EventBusPort` (removed) |

**Status:** All verified removed ✅

---

### 5. Test File Cleanup (Low Risk)

Some test files have duplicate `import pytest` lines from sed-based patching. These don't cause failures but are messy.

**Effort:** 30 minutes to clean

---

### 6. Pydantic Config Warning Fix (Low Risk)

The `shared/config.py` was updated to remove deprecated `Field(env=...)` usage. This eliminated 7 pydantic warnings down to the remaining 4 that come from other modules.

**Status:** Done ✅

---

### 7. Domain → Config Remaining (Medium Risk)

Two imports remain that violate the clean architecture:

```python
# app/domain/fabio_ai/services/option_scanner.py
from app.config import settings  # Only used for SCANNER_UNDERLYINGS

# app/domain/fabio_ai/services/vp_contract_selector.py  
from app.config import settings  # Only used for SCANNER_UNDERLYINGS
```

**Recommended Fix for Phase 2:**
Add `default_underlyings` as optional constructor parameter to both classes.

For `OptionScannerService.__init__`:
```python
def __init__(self, broker, default_underlyings: list[str] | None = None):
    self._broker = broker
    self._default_underlyings = default_underlyings or self._guess_underlyings()
```

For `VPContractSelector.__init__`:
```python
def __init__(self, broker, exchange: str = "MCX", default_underlyings: list[str] | None = None):
    self._default_underlyings = default_underlyings or (
        ["CRUDEOIL", "NATURALGAS"] if exchange == "MCX" else ["NIFTY", "BANKNIFTY"]
    )
```

Then in `ServiceGraph.__init__`:
```python
self.vp_contract_selector = VPContractSelector(
    broker=self.market_data,
    exchange=self.exchange_config.exchange,
    default_underlyings=settings.SCANNER_UNDERLYINGS,
)
```

The `scan_top_n` method in OptionScannerService should use `self._default_underlyings` instead of importing `settings`.

**Effort:** 1 hour
**Impact:** Removes 2 import-linter exemptions, eliminates domain → config dependency

---

## What's NOT in this quick-win plan

The following are **major refactorings** covered in the `MASTER_ARCHITECTURE_PLAN.md` and should NOT be attempted as quick wins:

### God Class Extraction (Phase 4)
- `trading_session.py` (1326 lines) → 6 orchestrators
- `entry_gate.py` (1090 lines) → 8 modules  
- `engine.py` (940 lines) → 5 extraction targets

### Phase 3: Unify Position State
- Merge `TradeManager._positions` + `Portfolio.positions` into single source
- Requires comprehensive migration with dual-run validation

### Phase 7: Engine Cleanup
- Extract history seeding, position recovery, candle loading logic

These each require 2-4 days of focused work with comprehensive testing. They are explicitly tracked in the master plan and will be addressed sequentially.
