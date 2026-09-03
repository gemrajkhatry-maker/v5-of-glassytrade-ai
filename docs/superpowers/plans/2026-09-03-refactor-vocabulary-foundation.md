# Refactor Vocabulary Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate scattered numeric/time/instrument/timeout duplicates (audit SMELL-01/04/05/12/16) behind single-owner vocabulary modules.

**Architecture:** Extract `shared/money.py` and `shared/net_policy.py` as sole owners; make `quant/contracts/numeric.py` + `decimal_utils.py` thin re-exports; make `instrument_registry.py` the sole lot/tick source; consolidate frontend IST to one module. No behavior change — pure move + delegate + parity tests.

**Tech Stack:** Python 3 (`Decimal`), pytest (`pythonpath=. backend`, `asyncio_mode=auto`), ruff, TypeScript (frontend `tsc --noEmit`), vitest.

## Global Constraints

- `pytest.ini`: `pythonpath = . backend`, `testpaths = tests backend/tests`, `--import-mode=importlib`.
- Backend tests run as: `cd backend && PYTHONPATH=..:. .venv/bin/python -m pytest tests/ -q --no-header`.
- Root quant tests run as: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --no-header`.
- Brokers tests run as: `cd brokers && PYTHONPATH=..:. .venv/bin/python -m pytest -q --no-header`.
- Lint gate: `.venv/bin/python -m ruff check quant backend/app brokers shared tests backend/tests` and `cd frontend && npx tsc --noEmit`.
- All monetary values use `Decimal`; `float` only at WS/DTO presenter edge.
- DRY, YAGNI, TDD, frequent commits — one commit per task minimum.

---

## File Structure

| File | Responsibility after plan |
|---|---|
| `shared/money.py` (new) | Sole `to_decimal/to_float/safe_decimal_operation` owner. One None-policy. |
| `shared/net_policy.py` (new) | Sole timeout/retry/backoff tables + `capped_exp_delay`. |
| `quant/contracts/numeric.py` (modify) | Thin re-export of `shared.money.to_float`. |
| `quant/contracts/decimal_utils.py` (modify) | Thin re-export of `shared.money.to_decimal`. |
| `backend/app/infrastructure/adapters/dhan_broker_adapter.py` (modify) | Delete local `_to_decimal`, import from `shared.money`. |
| `backend/app/infrastructure/adapters/dhan_order_feed.py` (modify) | Delete local `_to_float`, import from `shared.money`. |
| `quant/contracts/instrument_registry.py` (modify) | Sole lot/tick/freeze/strike store (already is; add `get_lot_size/get_tick_size` helpers). |
| `brokers/broker/market_info.py` (modify) | Delete fallback `LOT_SIZES`/`STEP_SIZES` tables, delegate 100% to registry. |
| `brokers/broker/dhan/domain/constants.py` (modify) | Delete `LOT_SIZES`/`STRIKE_STEPS` tables, re-export from registry. |
| `frontend/time/ist.ts` (new) | Sole `IST_OFFSET_SECONDS` + `toISTSeconds()` owner. |
| `frontend/constants.ts` (modify) | Re-export from `time/ist.ts`. |
| `frontend/config.ts` (modify) | Delete duplicate `IST_OFFSET_SECONDS`. |
| `quant/brokers/multiplexed_feed.py` (modify) | Replace `ts -= 19800.0` with named helper. |
| `tests/quant/contracts/test_money_parity.py` (new) | None-matrix + backoff golden + lot parity tests. |

---

### Task 1: Canonical numeric vocabulary in shared/money.py

**Files:**
- Create: `shared/money.py`
- Create: `tests/quant/contracts/test_money_parity.py`
- Modify: none yet

**Interfaces:**
- Consumes: nothing (leaf module, stdlib `decimal.Decimal` only).
- Produces: `shared.money.to_decimal(value: Any) -> Decimal`, `shared.money.to_float(value: Any, default: float = 0.0) -> float`, `shared.money.safe_decimal_operation(a, b, operation: str) -> Decimal` — used by Tasks 2–3.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/contracts/test_money_parity.py
from decimal import Decimal
from shared.money import to_decimal, to_float

def test_none_maps_to_zero():
    assert to_decimal(None) == Decimal("0")
    assert to_float(None) == 0.0

def test_bad_string_raises_for_decimal_returns_default_for_float():
    import pytest
    with pytest.raises(ValueError):
        to_decimal("abc")
    assert to_float("abc") == 0.0
    assert to_float("abc", default=1.5) == 1.5

def test_decimal_passthrough_and_float_string():
    assert to_decimal(Decimal("1.5")) == Decimal("1.5")
    assert to_decimal(123.45) == Decimal("123.45")
    assert to_float(Decimal("123.45")) == 123.45
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.money'`

- [ ] **Step 3: Write minimal implementation**

```python
# shared/money.py
"""Sole numeric vocabulary — Decimal/float conversions. (REF-01)"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from typing import Any

def to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            raise ValueError(f"Cannot convert '{value}' to Decimal")
    raise ValueError(f"Unsupported type: {type(value)}")

def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    if hasattr(value, "__float__"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    return default

def safe_decimal_operation(a: Any, b: Any, operation: str = "add") -> Decimal:
    dec_a = to_decimal(a)
    dec_b = to_decimal(b)
    if operation == "add":
        return dec_a + dec_b
    elif operation == "subtract":
        return dec_a - dec_b
    elif operation == "multiply":
        return dec_a * dec_b
    elif operation == "divide":
        if dec_b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        return dec_a / dec_b
    raise ValueError(f"Unsupported operation: {operation}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add shared/money.py tests/quant/contracts/test_money_parity.py
git commit -m "feat: add shared.money canonical numeric vocabulary"
```

---

### Task 2: Collapse quant shims to re-export shared.money

**Files:**
- Modify: `quant/contracts/decimal_utils.py`
- Modify: `quant/contracts/numeric.py`
- Test: `tests/quant/contracts/test_money_parity.py` (append)

**Interfaces:**
- Consumes: `shared.money.to_decimal`, `shared.money.to_float` (from Task 1).
- Produces: same import names (`quant.contracts.decimal_utils.to_decimal`, `quant.contracts.numeric.to_float`) so all existing callers keep working.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/quant/contracts/test_money_parity.py
def test_quant_shims_are_shared_money():
    import shared.money as m
    import quant.contracts.decimal_utils as du
    import quant.contracts.numeric as nu
    assert du.to_decimal is m.to_decimal
    assert nu.to_float is m.to_float
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py::test_quant_shims_are_shared_money -v`
Expected: FAIL with `AssertionError` (shims are independent copies)

- [ ] **Step 3: Write minimal implementation**

```python
# quant/contracts/decimal_utils.py
"""Thin re-export — owner is shared.money (REF-01)."""
from __future__ import annotations
from shared.money import to_decimal, safe_decimal_operation  # noqa: F401
__all__ = ["to_decimal", "safe_decimal_operation"]
```

```python
# quant/contracts/numeric.py
"""Thin re-export — owner is shared.money (REF-01)."""
from __future__ import annotations
from shared.money import to_float  # noqa: F401
__all__ = ["to_float"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py tests/quant/contracts/test_aggregates.py -q --no-header`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/contracts/decimal_utils.py quant/contracts/numeric.py tests/quant/contracts/test_money_parity.py
git commit -m "refactor: collapse quant numeric shims onto shared.money"
```

---

### Task 3: Migrate backend adapters off private converters

**Files:**
- Modify: `backend/app/infrastructure/adapters/dhan_broker_adapter.py:36-44`
- Modify: `backend/app/infrastructure/adapters/dhan_order_feed.py:55-70`
- Test: `tests/quant/contracts/test_money_parity.py` (append)

**Interfaces:**
- Consumes: `shared.money.to_decimal`, `shared.money.to_float` (Task 1).
- Produces: identical adapter behavior (same defaults `"0"` / `0.0`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/quant/contracts/test_money_parity.py
def test_adapter_converters_match_shared_money():
    from shared.money import to_decimal, to_float
    assert to_decimal(None) == to_decimal(None)
    assert to_float("bad") == 0.0
    # Adapters must import from shared.money, not define privates:
    import pathlib
    adapter = pathlib.Path("backend/app/infrastructure/adapters/dhan_broker_adapter.py").read_text()
    assert "def _to_decimal" not in adapter
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py::test_adapter_converters_match_shared_money -v`
Expected: FAIL with `AssertionError` (`def _to_decimal` still present)

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/infrastructure/adapters/dhan_broker_adapter.py:36-44 REPLACE
from shared.money import to_decimal as _to_decimal
```

```python
# backend/app/infrastructure/adapters/dhan_order_feed.py:64 REPLACE
from shared.money import to_float as _to_float
```

Keep call sites unchanged (`_to_decimal(...)` / `_to_float(...)` keep working). Delete the local `def _to_decimal` block (lines 36-44) and local `def _to_float` block. Note: adapter `_to_decimal(value, default="0")` had a `default` param — replace call sites passing a custom default with `to_decimal(value) if value is not None else Decimal(default)` inline only where needed (only `dhan_broker_adapter.py:159,307-310,315,470-473,524,527,545` — all use default `"0"`, so plain alias suffices).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/test_dhan_broker_adapter.py tests/unit/test_close_order_idempotency.py -q --no-header`
Expected: PASS. Then: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py -q --no-header`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/adapters/dhan_broker_adapter.py backend/app/infrastructure/adapters/dhan_order_feed.py tests/quant/contracts/test_money_parity.py
git commit -m "refactor: adapters use shared.money, delete private converters"
```

---

### Task 4: Instrument registry as sole lot/tick owner

**Files:**
- Modify: `quant/contracts/instrument_registry.py` (add helpers)
- Modify: `brokers/broker/market_info.py:28-77` (derive registry rows, keep extras)
- Modify: `brokers/broker/dhan/domain/constants.py:131-161` (derive registry rows, keep stock extras)
- Test: `tests/quant/contracts/test_money_parity.py` (append parity test)

**Interfaces:**
- Consumes: `quant.contracts.instrument_registry.DEFAULT_REGISTRY` (exists, `_SPECS` has NIFTY=65/0.05/50, BANKNIFTY=30/100, CRUDEOILM=10, GOLDM=100 per lines 61-100).
- Produces: `get_lot_size(root) -> int`, `get_tick_size(root) -> float` on registry; `market_info.get_lot_size/get_step_size` keep signatures and fallbacks.

> Scope correction (2026-09-03, controller): the registry covers ~19 index/MCX roots only — it does NOT cover NSE stock rows (RELIANCE…ULTRACEMCO), display aliases ("NIFTY 50"), or extras (SILVERMIC, GOLDGUINEA), and `STEP_SIZES` strike steps differ semantically from registry `strike_interval` (e.g. GOLDM 50.0 vs 100, SILVERM 250 vs 500). So tables are NOT deleted. Instead: registry-covered entries are derived from the registry, non-covered rows stay as marked extras, and a parity test fails if they ever disagree. Behavior is fully preserved.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/quant/contracts/test_money_parity.py
def test_registry_is_sole_lot_source():
    from quant.contracts.instrument_registry import (
        DEFAULT_REGISTRY, get_lot_size as reg_lot, get_tick_size as reg_tick,
    )
    assert DEFAULT_REGISTRY.try_resolve("NIFTY").lot_size == 65
    assert DEFAULT_REGISTRY.try_resolve("BANKNIFTY").lot_size == 30
    assert DEFAULT_REGISTRY.try_resolve("CRUDEOILM").lot_size == 10
    assert reg_lot("NIFTY") == 65
    assert reg_tick("CRUDEOIL") == 1.0
    # Parity: every registry-covered root agrees with market_info + dhan constants
    from brokers.broker.market_info import get_lot_size
    from brokers.broker.dhan.domain.constants import LOT_SIZES as DHAN_LOTS
    for spec in DEFAULT_REGISTRY.specs():
        assert get_lot_size(spec.root) == spec.lot_size, spec.root
        if spec.root in DHAN_LOTS:
            assert DHAN_LOTS[spec.root] == spec.lot_size, spec.root
    # Non-registry extras still work (stocks, aliases) — behavior preserved
    assert get_lot_size("RELIANCE") == 250
    assert get_lot_size("NIFTY 50") == 65
    assert get_lot_size("UNKNOWN_XYZ") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py::test_registry_is_sole_lot_source -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError` (`get_lot_size/get_tick_size` don't exist yet on the registry module)

- [ ] **Step 3: Write minimal implementation**

```python
# quant/contracts/instrument_registry.py — append after DEFAULT_REGISTRY def
def get_lot_size(root: str) -> int:
    return DEFAULT_REGISTRY.resolve(root).lot_size

def get_tick_size(root: str) -> float:
    return DEFAULT_REGISTRY.resolve(root).tick_size
```

```python
# brokers/broker/dhan/domain/constants.py:131-161 REPLACE the index/MCX rows of
# LOT_SIZES with registry-derived entries; KEEP the stock rows as marked extras:
from quant.contracts.instrument_registry import DEFAULT_REGISTRY as _REG

LOT_SIZES: dict[str, int] = {
    **{s.root: s.lot_size for s in _REG.specs()},
    # --- Non-registry extras: NSE F&O stocks (lots vary; registry covers indices/MCX only)
    "RELIANCE": 250,
    "TCS": 150,
    "INFY": 600,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "SBIN": 1500,
    "TATAMOTORS": 1500,
    "AXISBANK": 1200,
    "BAJFINANCE": 125,
    "MARUTI": 100,
    "HINDUNILVR": 300,
    "KOTAKBANK": 300,
    "LT": 250,
    "BHARTIARTL": 750,
    "WIPRO": 1000,
    "TATASTEEL": 2500,
    "ADANIENT": 250,
    "NTPC": 2300,
    "POWERGRID": 2600,
    "ULTRACEMCO": 150,
}
```

`STRIKE_STEPS` in the same file: keep as-is (index rows verified equal to registry already: NIFTY 50, BANKNIFTY 100, FINNIFTY 50, MIDCPNIFTY 25, SENSEX/BANKEX 100 — parity test could assert but out of scope; leave untouched).

```python
# brokers/broker/market_info.py — REPLACE the LOT_SIZES literal (lines 28-77) with:
from quant.contracts.instrument_registry import DEFAULT_REGISTRY as _MI_REG

LOT_SIZES: Dict[str, int] = {
    **{s.root: s.lot_size for s in _MI_REG.specs()},
    # --- Non-registry extras: display aliases + stocks + non-registry micros
    "NIFTY 50": 65,
    "NIFTY BANK": 30,
    "NIFTY FIN SERVICE": 60,
    "NIFTY MID SELECT": 120,
    "RELIANCE": 250,
    "TCS": 150,
    "INFY": 600,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "SBIN": 1500,
    "TATAMOTORS": 1500,
    "AXISBANK": 1200,
    "BAJFINANCE": 125,
    "MARUTI": 100,
    "HINDUNILVR": 300,
    "KOTAKBANK": 300,
    "LT": 250,
    "BHARTIARTL": 750,
    "WIPRO": 1000,
    "TATASTEEL": 2500,
    "ADANIENT": 250,
    "NTPC": 2300,
    "POWERGRID": 2600,
    "ULTRACEMCO": 150,
    "SILVERMIC": 1,
}
```

Keep `get_lot_size`/`get_step_size` bodies, fallbacks (`1` / `5.0`), `STEP_SIZES`, `EXPIRY_WEEKDAY`, `ASSET_NAME_MAP` untouched — `STEP_SIZES` strike steps are display/quote steps, NOT registry strike intervals (GOLDM 50 vs 100), so they stay.

⚠️ Domain flag: NSE lot revisions need exchange-notice confirmation before changing `_SPECS`; this task derives (never edits) numbers.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py backend/tests/unit/test_strategy_regressions.py -q --no-header`
Expected: PASS (behavior preserved — fallbacks intact). Then: `cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/test_market_info.py brokers/broker/dhan/tests/test_domain.py -q --no-header`
Expected: PASS (no expectation updates needed — values unchanged)

- [ ] **Step 5: Commit**

```bash
git add quant/contracts/instrument_registry.py brokers/broker/market_info.py brokers/broker/dhan/domain/constants.py tests/quant/contracts/test_money_parity.py
git commit -m "refactor: instrument registry sole lot/tick owner"
```

---

### Task 5: Single IST owner (backend + frontend)

**Files:**
- Create: `frontend/time/ist.ts`
- Modify: `frontend/constants.ts`
- Modify: `frontend/config.ts` (delete duplicate)
- Modify: `quant/brokers/multiplexed_feed.py:502-505`
- Test: `frontend/tests/components/chart/CandleSeriesManager.test.ts` (existing, must stay green)

**Interfaces:**
- Consumes: `quant.contracts.timezones.IST` (exists, `timezone(timedelta(hours=5, minutes=30))`).
- Produces: `frontend/time/ist.ts: IST_OFFSET_SECONDS`, `toISTSeconds()`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/time/ist.test.ts
import { describe, expect, it } from 'vitest';
import { IST_OFFSET_SECONDS, toISTSeconds } from './ist';
describe('ist', () => {
  it('offset is 19800', () => { expect(IST_OFFSET_SECONDS).toBe(19800); });
  it('shifts epoch', () => { expect(toISTSeconds(0)).toBe(19800); });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run time/ist.test.ts`
Expected: FAIL with `Failed to resolve import ./ist` (file not created yet)

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/time/ist.ts
export const IST_OFFSET_SECONDS = 19800; // UTC+5:30, sole frontend owner
export function toISTSeconds(epochSeconds: number): number {
  return epochSeconds + IST_OFFSET_SECONDS;
}
export function fromPreShiftedIST(epochSeconds: number): number {
  return epochSeconds; // documents multiplexed_feed pre-shift; no math here
}
```

```typescript
// frontend/constants.ts REPLACE line 6 with:
export { IST_OFFSET_SECONDS } from './time/ist';
```

Delete `export const IST_OFFSET_SECONDS = 19800;` from `frontend/config.ts:16` (keep `DEFAULT_CHART_CONFIG` etc.). Update `CandleSeriesManager.ts:35`, `VolumeSeriesManager.ts:33`, `ExecutionMarkersManager.ts:35` to `import { IST_OFFSET_SECONDS } from '../../time/ist'` (drop local `const IST_OFFSET =` alias, use `IST_OFFSET_SECONDS` directly).

```python
# quant/brokers/multiplexed_feed.py:502-505 REPLACE
from quant.contracts.timezones import IST as _IST
IST_OFFSET_SECONDS = int(_IST.utcoffset(None).total_seconds())  # 19800
ts -= IST_OFFSET_SECONDS  # pre-shifted IST epoch correction
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run time/ist.test.ts tests/components/chart/CandleSeriesManager.test.ts`
Expected: PASS. Then: `cd frontend && npx tsc --noEmit`
Expected: PASS (no type errors)

- [ ] **Step 5: Commit**

```bash
git add frontend/time/ist.ts frontend/time/ist.test.ts frontend/constants.ts frontend/config.ts "frontend/components/chart/CandleSeriesManager.ts" "frontend/components/chart/VolumeSeriesManager.ts" "frontend/components/chart/ExecutionMarkersManager.ts" quant/brokers/multiplexed_feed.py
git commit -m "refactor: single IST owner frontend/backend"
```

---

### Task 6: Single net-policy owner + backoff golden test

**Files:**
- Create: `shared/net_policy.py`
- Modify: `brokers/broker/dhan/domain/constants.py:214-237` (delegate)
- Modify: `frontend/config.ts:188-203` (document as generated mirror)
- Test: `tests/quant/contracts/test_money_parity.py` (append)

**Interfaces:**
- Consumes: nothing (leaf tables; values copied verbatim: `TIMEOUT=10.0, RETRIES=3, BACKOFF=0.5, MAX_DELAY=30.0, WS_PING=30.0, RECONNECT=5.0, MAX_ATTEMPTS=30`).
- Produces: `shared.net_policy.DEFAULT_TIMEOUT_SECONDS`, `DEFAULT_MAX_RETRIES`, `capped_exp_delay(attempt, base=0.5, cap=30.0) -> float`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/quant/contracts/test_money_parity.py
def test_backoff_golden_table():
    from shared.net_policy import capped_exp_delay
    assert capped_exp_delay(0) == 0.5
    assert capped_exp_delay(1) == 1.0
    assert capped_exp_delay(2) == 2.0
    assert capped_exp_delay(10) == 30.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py::test_backoff_golden_table -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.net_policy'`

- [ ] **Step 3: Write minimal implementation**

```python
# shared/net_policy.py
"""Sole timeout/retry/backoff owner. Frontend NETWORK_CONFIG mirrors these values. (REF-04)"""
from __future__ import annotations

DEFAULT_TIMEOUT_SECONDS: float = 10.0
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BACKOFF_FACTOR: float = 0.5
DEFAULT_RETRY_MAX_DELAY_SECONDS: float = 30.0
WS_PING_INTERVAL_SECONDS: float = 30.0
WS_RECONNECT_DELAY_SECONDS: float = 5.0
WS_MAX_RECONNECT_ATTEMPTS: int = 30
INSTRUMENT_CACHE_TTL_SECONDS: int = 86400

def capped_exp_delay(attempt: int, base: float = DEFAULT_RETRY_BACKOFF_FACTOR, cap: float = DEFAULT_RETRY_MAX_DELAY_SECONDS) -> float:
    return min(base * (2 ** attempt), cap)
```

Names match `dhan/domain/constants.py` exactly (verified 20+ importers use these names via `domain/__init__.py`). In `brokers/broker/dhan/domain/constants.py:208-239` replace the 8 literals with `from shared.net_policy import (...)` re-exports (keep names so importers don't change). In `frontend/config.ts:188-203` add comment `// Mirror of shared/net_policy.py — change both` above `NETWORK_CONFIG` (values stay `5, 30, 30, 180_000, 10`).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py -q --no-header`
Expected: PASS. Then: `.venv/bin/python -m ruff check quant backend/app brokers shared tests backend/tests`
Expected: PASS (no new violations)

- [ ] **Step 5: Commit**

```bash
git add shared/net_policy.py brokers/broker/dhan/domain/constants.py frontend/config.ts tests/quant/contracts/test_money_parity.py
git commit -m "refactor: single net-policy owner with backoff golden test"
```

---

## Self-Review

- Spec coverage: audit REF-01 (Tasks 1-3) ✅, REF-02 ticks/lots (Task 4) ✅, REF-03 time (Task 5) ✅, REF-04 timeouts (Task 6) ✅. Higher layers (REF-05+ entities/services/boundaries) explicitly out of scope — next plan.
- Placeholder scan: no TBD/TODO; every step has exact paths, code blocks, commands, expected outputs.
- Type consistency: `to_decimal -> Decimal`, `to_float -> float`, `get_lot_size -> int`, `capped_exp_delay -> float`, `IST_OFFSET_SECONDS = 19800` consistent across tasks.
