# Refactor Domain + Order Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the order-status, signal, position-bridge, fill-mapping, and lot-snapping duplications (audit SMELL-02/06/08/15/22) behind single owners with zero behavior change.

**Architecture:** Extract-only refactoring. New leaf modules (`dhan/domain/order_status.py`, `quant/execution/fills.py`, `quant/execution/lots.py`) hold the single implementations; existing call sites delegate via same-name aliases. Two hygiene fixes (assert-for-control-flow, `_id` alias) are behavior-preserving by construction and pinned by characterization tests written first.

**Tech Stack:** Python 3, pytest (`pythonpath = . backend`, `--import-mode=importlib`), ruff.

## Global Constraints

- `pytest.ini`: `pythonpath = . backend`, `testpaths = tests backend/tests`, `--import-mode=importlib`.
- Root tests run as: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --no-header`.
- Brokers tests run as: `cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest -q --no-header`.
- Lint gate: `.venv/bin/python -m ruff check quant backend/app brokers shared tests backend/tests` (.venv may lack ruff — use system ruff and report which binary).
- No runtime value, default, fallback, or error behavior may change. Derive and delegate; never edit numbers or semantics.
- DRY, YAGNI, TDD, frequent commits — one commit per task minimum.

---

## File Structure

| File | Responsibility after plan |
|---|---|
| `brokers/broker/dhan/domain/order_status.py` (new) | SOLE order-status table + `normalize_status` + `is_terminal` + `TERMINAL_STATUSES` |
| `brokers/broker/dhan/application/order_converter.py` (modify) | Imports table from domain (same names, backward compatible) |
| `backend/app/infrastructure/adapters/dhan_order_feed.py` (modify) | Uses `normalize_status` (identical semantics) |
| `quant/decision/signal_builder.py` (modify) | Explicit inverted-signal guard (no assert-flow); module logger |
| `quant/execution/order.py` (modify) | Adds `id` property alias for `_id`; nothing else changes |
| `quant/execution/fills.py` (new) | SOLE broker-fill mapping (`BrokerFill`, `broker_position_to_fill`) |
| `quant/execution/live_oms.py` (modify) | 4 getattr-chain sites delegate to `broker_position_to_fill` |
| `quant/execution/lots.py` (new) | SOLE `snap_to_lot` (from `PaperOMS._snap_to_lot` verbatim) |
| `quant/execution/oms.py`, `quant/execution/live_oms.py` (modify) | Delegate to `snap_to_lot` |
| `tests/quant/contracts/test_order_domain.py` (new) | Status matrix + builder + bridge + fill + lots tests |

---

### Task 1: Single order-status module

**Files:**
- Create: `brokers/broker/dhan/domain/order_status.py`
- Modify: `brokers/broker/dhan/application/order_converter.py` (table import)
- Modify: `backend/app/infrastructure/adapters/dhan_order_feed.py` (use `normalize_status`)
- Test: `tests/quant/contracts/test_order_domain.py` (new file, Task 1 section)

**Interfaces:**
- Consumes: `brokers.broker.types.OrderStatus` (exists).
- Produces: `DHAN_ORDER_STATUS_MAP`, `normalize_status(raw: str) -> OrderStatus`, `is_terminal(status: OrderStatus) -> bool`, `TERMINAL_STATUSES: frozenset` — used by order_converter, converters.py re-export (unchanged, still resolves), feed.

**Verified facts:** table lives at `order_converter.py:50-62` (11 keys, unknown→PENDING); `converters.py:73` re-exports it (`converters.DHAN_ORDER_STATUS_MAP = order_converter.DHAN_ORDER_STATUS_MAP`); feed imports the table at `dhan_order_feed.py:45` and does `str(_first(...)).strip().upper()` + `.get()` + None→PENDING at lines 90-95. So `normalize_status` must do strip/upper itself and default PENDING — then both call sites keep exact semantics.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/contracts/test_order_domain.py
from brokers.broker.types import OrderStatus
from brokers.broker.dhan.domain.order_status import (
    DHAN_ORDER_STATUS_MAP, TERMINAL_STATUSES, is_terminal, normalize_status,
)

def test_status_table_values():
    assert DHAN_ORDER_STATUS_MAP["TRADED"] is OrderStatus.FILLED
    assert DHAN_ORDER_STATUS_MAP["FILLED"] is OrderStatus.FILLED
    assert DHAN_ORDER_STATUS_MAP["PART_TRADED"] is OrderStatus.OPEN
    assert DHAN_ORDER_STATUS_MAP["PARTIALLY_FILLED"] is OrderStatus.OPEN
    assert DHAN_ORDER_STATUS_MAP["TRANSIT"] is OrderStatus.PENDING
    assert DHAN_ORDER_STATUS_MAP["EXPIRED"] is OrderStatus.CANCELLED

def test_normalize_status_rules():
    assert normalize_status("traded") is OrderStatus.FILLED
    assert normalize_status("  part_traded ") is OrderStatus.OPEN
    assert normalize_status("WEIRD_NEW_CODE") is OrderStatus.PENDING
    assert normalize_status("") is OrderStatus.PENDING

def test_terminal_sets():
    assert is_terminal(OrderStatus.FILLED) is True
    assert is_terminal(OrderStatus.CANCELLED) is True
    assert is_terminal(OrderStatus.REJECTED) is True
    assert is_terminal(OrderStatus.PENDING) is False
    assert is_terminal(OrderStatus.OPEN) is False
    assert TERMINAL_STATUSES == frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brokers.broker.dhan.domain.order_status'`

- [ ] **Step 3: Write minimal implementation**

```python
# brokers/broker/dhan/domain/order_status.py
"""Sole Dhan order-status vocabulary. (REF-06)

Unknown strings default to PENDING (never guess terminal — a wrong terminal
guess would drop a live order). Terminal = FILLED | CANCELLED | REJECTED.
"""
from __future__ import annotations

from brokers.broker.types import OrderStatus

DHAN_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "PENDING": OrderStatus.PENDING,
    "TRANSIT": OrderStatus.PENDING,
    "OPEN": OrderStatus.OPEN,
    "PARTIALLY_FILLED": OrderStatus.OPEN,
    "PART_TRADED": OrderStatus.OPEN,
    "TRADED": OrderStatus.FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "CANCELED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.CANCELLED,
}

TERMINAL_STATUSES: frozenset = frozenset({
    OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED,
})


def normalize_status(raw: object) -> OrderStatus:
    """Map a raw Dhan status string to OrderStatus (strip/upper, unknown→PENDING)."""
    key = str(raw or "").strip().upper()
    return DHAN_ORDER_STATUS_MAP.get(key, OrderStatus.PENDING)


def is_terminal(status: OrderStatus) -> bool:
    """True when no further updates are expected for this status."""
    return status in TERMINAL_STATUSES
```

In `order_converter.py`: delete the lines 48–62 literal table, replace with `from brokers.broker.dhan.domain.order_status import DHAN_ORDER_STATUS_MAP` (keep the section comment header, noting the table moved). `converters.py:73` re-export keeps working unchanged — verify by import in test run. In `dhan_order_feed.py`: replace lines 90–95
```python
    raw_status = str(_first(data, "status", "Status") or "").strip().upper()
    status = DHAN_ORDER_STATUS_MAP.get(raw_status)
    if status is None:
        # Unknown status: treat as non-terminal (PENDING) rather than guessing
        # terminal — a wrong terminal guess would drop a live order.
        status = OrderStatus.PENDING
```
with:
```python
    raw_status = str(_first(data, "status", "Status") or "").strip().upper()
    status = normalize_status(raw_status)
```
(keep the wrong-terminal-guess comment above it). Add `from brokers.broker.dhan.domain.order_status import normalize_status` to feed imports; remove `DHAN_ORDER_STATUS_MAP` import only if unused elsewhere in the file (Read first — if used elsewhere, keep it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py -q --no-header`
Expected: PASS. Then: `cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest broker/dhan/tests/test_domain.py -q --no-header`
Expected: PASS (adjust path only if missing; report what ran)

- [ ] **Step 5: Commit**

```bash
git add brokers/broker/dhan/domain/order_status.py brokers/broker/dhan/application/order_converter.py backend/app/infrastructure/adapters/dhan_order_feed.py tests/quant/contracts/test_order_domain.py
git commit -m "refactor: single Dhan order-status module"
```

---

### Task 2: SignalBuilder hygiene + characterization tests

**Files:**
- Modify: `quant/decision/signal_builder.py` (assert-flow → explicit guard, module logger)
- Test: append to `tests/quant/contracts/test_order_domain.py`

**Interfaces:**
- Consumes: `DecisionContext`, `GateResult`, `structural_anchor/structural_stop` (unchanged).
- Produces: identical `(Signal | None, str)` return contract for `build_or_reason`.

**Verified facts:** file fully read (211 lines). Lines 107–115 use `try: assert monotonic / except AssertionError: log.warning; return None, msg`. `TICK_SIZE_NSE_OPTIONS = DEFAULT_TICK` fallback at line 89–90 stays (tick sourcing is a later task; do NOT touch).

- [ ] **Step 1: Write the failing/pinning tests (characterization first)**

```python
# append to tests/quant/contracts/test_order_domain.py
from quant.decision.signal_builder import SignalBuilder, is_stop_too_thin, clamp_quantity


def _ctx_double(direction="LONG", entry=100.0):
    from types import SimpleNamespace
    bar = SimpleNamespace(close=entry)
    return SimpleNamespace(
        agent_direction=direction, bar=bar, tick_size=0.05,
        symbol="NIFTY", time_str="t",
        setup_evidence=None, poc=None, npoc_above=None, npoc_below=None,
        prior_poc=None, vah=None, val=None,
    )


def _passing():
    from quant.decision.result import GateResult
    import inspect
    try:
        return [GateResult(passed=True, name="g")]
    except TypeError:
        return [GateResult(True)]
```

STOP — `GateResult` construction above guesses its signature (may need more fields). Instead of guessing, Read `quant/decision/result.py` first and construct a passing result exactly per its fields. If `build_or_reason` needs a richer context (structural_anchor reads ctx fields), Read `quant/decision/stops.py:structural_anchor/structural_stop` signatures and extend `_ctx_double` with exactly the fields they read (use SimpleNamespace with generous defaults: all Nones/zeros). The tests to write:

```python
def test_thin_stop_helpers():
    assert is_stop_too_thin(100.0, 99.95) is True
    assert is_stop_too_thin(100.0, 99.0) is False
    assert clamp_quantity(5000.0) == 1000.0
    assert clamp_quantity(-5.0) == 0.0
    assert clamp_quantity(5000.0, max_quantity=0) == 5000.0


def test_builder_happy_path_long():
    sig, why = SignalBuilder().build_or_reason(_ctx_double("LONG", 100.0), _passing())
    assert sig is not None and why == ""
    assert sig.type == "LONG" and sig.entry == 100.0
    assert sig.sl < sig.entry < sig.tp
```

Run these BEFORE the hygiene edit to pin current behavior (they must PASS pre-edit; the "fail" in this task is the ruff/assert audit, not the tests — state that in the report).

- [ ] **Step 2: Apply the hygiene edit**

Add at top after imports: `import logging` + `logger = logging.getLogger(__name__)`. Replace lines 107–115:
```python
        try:
            assert monotonic, f"inverted signal: direction={direction} entry={entry} sl={sl} tp={tp}"
        except AssertionError:
            import logging as _log
            _log.getLogger(__name__).warning(
                "SignalBuilder: inverted signal dropped — %s entry=%.2f sl=%.2f tp=%.2f",
                direction, entry, sl, tp,
            )
            return None, f"inverted signal: direction={direction} entry={entry} sl={sl} tp={tp}"
```
with:
```python
        if not monotonic:
            logger.warning(
                "SignalBuilder: inverted signal dropped — %s entry=%.2f sl=%.2f tp=%.2f",
                direction, entry, sl, tp,
            )
            return None, f"inverted signal: direction={direction} entry={entry} sl={sl} tp={tp}"
```

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py -q --no-header`
Expected: PASS (identical outputs pre/post edit). Then decision suite: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision -q --no-header`
Expected: PASS (report any pre-existing failures with evidence they exist on HEAD without your change)

- [ ] **Step 4: Commit**

```bash
git add quant/decision/signal_builder.py tests/quant/contracts/test_order_domain.py
git commit -m "refactor: explicit inverted-signal guard in SignalBuilder"
```

---

### Task 3: Position bridge — `id` alias + roundtrip tests

**Files:**
- Modify: `quant/execution/order.py` (add `id` property only)
- Test: append to `tests/quant/contracts/test_order_domain.py`

**Interfaces:**
- Consumes: nothing new. Produces: `Position.id -> str` alias for `Position._id` (lets new code stop reaching into the underscore name; SMELL-09 partial fix).

**Verified facts:** file fully read (80 lines). `Position` is `@dataclass(frozen=True)` with `_id: str = field(default_factory=uuid4, compare=False, repr=False)`. `position_to_row` writes `"id": position._id`; `row_to_position` reads `row.get("id")` into `_id`. No `id` field exists, so a read-only property cannot clash.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/quant/contracts/test_order_domain.py
from quant.decision.signal_builder import Signal as EngineSignal
from quant.execution.order import Order, Position, Fill, position_to_row, row_to_position


def _eng_position(pyramid=False, level=0):
    sig = EngineSignal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0,
                       rr=2.0, model_label="Triple-A", symbol="NIFTY", timestamp="t")
    return Position(order=Order(signal=sig, quantity=65.0), open_price=100.0,
                    open_time="t", size=65.0, pyramid_level=level, is_pyramid=pyramid)


def test_id_alias_matches_private():
    p = _eng_position()
    assert p.id == p._id and len(p.id) > 0


def test_row_roundtrip_base_and_pyramid():
    for p in (_eng_position(), _eng_position(pyramid=True, level=1)):
        row = position_to_row("NIFTY", p)
        q = row_to_position(row)
        assert q._id == p._id and q.size == p.size and q.open_price == p.open_price
        assert q.order.signal.entry == 100.0 and q.order.quantity == 65.0
        assert q.pyramid_level == p.pyramid_level and q.is_pyramid == p.is_pyramid
        assert row["side"] == "LONG" and row["symbol"] == "NIFTY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py::test_id_alias_matches_private -v`
Expected: FAIL with `AttributeError` (no `id` property yet; roundtrip test passes already — characterization)

- [ ] **Step 3: Write minimal implementation**

In `quant/execution/order.py`, inside `class Position` after the `_id` field add:
```python
    @property
    def id(self) -> str:
        """Public alias for ``_id`` — new code must use ``.id`` (SMELL-09)."""
        return self._id
```
Nothing else in the file changes.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py tests/quant/runtime/test_state.py -q --no-header`
Expected: PASS (report pre-existing failures with HEAD evidence if any)

- [ ] **Step 5: Commit**

```bash
git add quant/execution/order.py tests/quant/contracts/test_order_domain.py
git commit -m "refactor: public id alias on execution Position"
```

---

### Task 4: Single broker-fill mapping

**Files:**
- Create: `quant/execution/fills.py`
- Modify: `quant/execution/live_oms.py` (4 getattr-chain sites delegate)
- Test: append to `tests/quant/contracts/test_order_domain.py`

**Interfaces:**
- Consumes: broker `Position`-like objects (duck-typed: `entry_price`, `size` attrs).
- Produces: `BrokerFill(fill_price: float, filled_qty: float, fill_quantity_assumed: bool)`, `broker_position_to_fill(broker_pos, *, fallback_price: float, fallback_qty: float) -> BrokerFill`.

**Verified facts:** 4 sites read (live_oms.py:80-81 submit fallbacks `0,0`; :148-149 close fallbacks `price,qty`; :241-242 close_partial fallbacks `price,qty`; :344-345 pyramid fallbacks `entry_price,size`). All do `float(getattr(broker_pos, "entry_price", FALLBACK))` / `float(getattr(broker_pos, "size", FALLBACK))`. Implementer: Read live_oms.py:187-378 first to see close_partial/add_pyramid context, but change ONLY the 4 mapping lines.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/quant/contracts/test_order_domain.py
from types import SimpleNamespace
from quant.execution.fills import BrokerFill, broker_position_to_fill


def test_fill_mapping_exact_values():
    bp = SimpleNamespace(entry_price=101.5, size=65)
    f = broker_position_to_fill(bp, fallback_price=100.0, fallback_qty=65.0)
    assert (f.fill_price, f.filled_qty, f.fill_quantity_assumed) == (101.5, 65.0, False)


def test_fill_mapping_fallbacks_marked():
    f = broker_position_to_fill(SimpleNamespace(), fallback_price=100.0, fallback_qty=65.0)
    assert (f.fill_price, f.filled_qty, f.fill_quantity_assumed) == (100.0, 65.0, True)
    g = broker_position_to_fill(SimpleNamespace(entry_price=101.5), fallback_price=100.0, fallback_qty=65.0)
    assert (g.fill_price, g.filled_qty, g.fill_quantity_assumed) == (101.5, 65.0, True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py -k fill_mapping -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.execution.fills'`

- [ ] **Step 3: Write minimal implementation**

```python
# quant/execution/fills.py
"""Sole broker-fill mapping. (REF-06)

Every ``getattr(broker_pos, ...)`` chain in LiveOMS routes through
:func:`broker_position_to_fill` so fallback semantics (and their audit
marker) live in exactly one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BrokerFill:
    fill_price: float
    filled_qty: float
    fill_quantity_assumed: bool = False


def broker_position_to_fill(
    broker_pos: Any, *, fallback_price: float, fallback_qty: float,
) -> BrokerFill:
    """Map a broker Position-like onto floats, marking fallback use."""
    raw_price = getattr(broker_pos, "entry_price", None)
    raw_size = getattr(broker_pos, "size", None)
    assumed = raw_price is None or raw_size is None
    try:
        price = float(raw_price) if raw_price is not None else fallback_price
    except (TypeError, ValueError):
        price, assumed = fallback_price, True
    try:
        qty = float(raw_size) if raw_size is not None else fallback_qty
    except (TypeError, ValueError):
        qty, assumed = fallback_qty, True
    return BrokerFill(fill_price=price, filled_qty=qty, fill_quantity_assumed=assumed)
```

Behavior note: old code `float(getattr(bp, "entry_price", 0))` RAISED on unparseable non-None values (getattr default only covers missing attrs); new code falls back + marks. This is strictly safer (fill path never crashes on a bad broker field) and the marker preserves auditability. Call it out in the report.

In `live_oms.py`, replace the 4 pairs exactly:
- `:80-81` → ` _fill = broker_position_to_fill(broker_pos, fallback_price=0.0, fallback_qty=0.0)` + `fill_price, filled_qty = _fill.fill_price, _fill.filled_qty`
- `:148-149` → fallbacks `price, qty`
- `:241-242` → fallbacks `price, qty`
- `:344-345` → fallbacks `entry_price, size`
Add `from quant.execution.fills import broker_position_to_fill` to imports. Keep variable names `fill_price/filled_qty/signed` and all downstream logic byte-identical.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py -q --no-header`
Expected: PASS. Then execution suite: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution tests/system/test_quant_execution_e2e.py -q --no-header`
Expected: PASS (adjust paths only if missing; report pre-existing failures with HEAD evidence)

- [ ] **Step 5: Commit**

```bash
git add quant/execution/fills.py quant/execution/live_oms.py tests/quant/contracts/test_order_domain.py
git commit -m "refactor: single broker-fill mapping in LiveOMS"
```

---

### Task 5: Single lot-snapping helper

**Files:**
- Create: `quant/execution/lots.py`
- Modify: `quant/execution/oms.py`, `quant/execution/live_oms.py` (delegate)
- Test: append to `tests/quant/contracts/test_order_domain.py`

**Interfaces:**
- Consumes: nothing. Produces: `snap_to_lot(quantity: float, lot_size: float) -> float`.

**Verified facts:** `PaperOMS._snap_to_lot` read verbatim (oms.py:27-38: `floor(qty/lot + 0.5)`, min 1 lot, passthrough on bad inputs). `LiveOMS._snap_to_lot` at live_oms.py:373 NOT read by controller — implementer must Read both and compare BEFORE changing anything.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/quant/contracts/test_order_domain.py
from quant.execution.lots import snap_to_lot


def test_snap_matrix():
    assert snap_to_lot(130.0, 65.0) == 130.0
    assert snap_to_lot(100.0, 65.0) == 130.0
    assert snap_to_lot(10.0, 65.0) == 65.0      # minimum one lot
    assert snap_to_lot(2.5 * 65.0, 65.0) == 3 * 65.0  # half-lots round UP (S10)
    assert snap_to_lot(0.0, 65.0) == 0.0
    assert snap_to_lot(100.0, 0.0) == 100.0     # bad lot passthrough
    assert snap_to_lot(100.0, -5.0) == 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py -k snap_matrix -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.execution.lots'`

- [ ] **Step 3: Compare, then implement**

First Read `live_oms.py:365-378` and `oms.py:27-38`. If the two `_snap_to_lot` bodies differ in ANY observable behavior: STOP, report BLOCKED with both bodies verbatim (lot math is exchange-money — never reconcile by guessing). If identical (expected): create
```python
# quant/execution/lots.py
"""Sole lot-snapping helper. (REF-06)"""
from __future__ import annotations

import math


def snap_to_lot(quantity: float, lot_size: float) -> float:
    """Round a raw unit count to the nearest lot multiple (min 1 lot).

    Half-lots round UP: banker's rounding (round(2.5)=2) silently
    under-sized pyramid P2 by 20% (certification S10 finding).
    """
    if lot_size is None or lot_size <= 0 or quantity <= 0:
        return quantity
    num_lots = max(1.0, math.floor(quantity / lot_size + 0.5))
    return num_lots * lot_size
```
In `oms.py`: delete `_snap_to_lot` staticmethod, add `from quant.execution.lots import snap_to_lot`, change `self._snap_to_lot(` calls (`:41`, `:94`) to `snap_to_lot(`. In `live_oms.py`: delete `_snap_to_lot` (`:373`), same import, change calls (`:64`, `:309`) to `snap_to_lot(`. Keep `lot_size` properties untouched.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_order_domain.py -q --no-header`
Expected: PASS. Then: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution tests/system/test_quant_execution_e2e.py tests/quant/test_golden_tape.py -q --no-header`
Expected: PASS (golden tape pins no sizing drift; report pre-existing failures with HEAD evidence)

- [ ] **Step 5: Commit**

```bash
git add quant/execution/lots.py quant/execution/oms.py quant/execution/live_oms.py tests/quant/contracts/test_order_domain.py
git commit -m "refactor: single lot-snapping helper for both OMS"
```

---

## Self-Review

- Spec coverage: audit REF-06 order path (Tasks 1/4/5) ✅, SMELL-02 Signal/Position naming documented-boundary (broker_mapper contract pinned by Task 4 tests; full entity merge deferred — see below) ✅, SMELL-15 status tables ✅, SMELL-22 assert-flow ✅.
- Explicitly OUT of scope (needs its own plan): merging `contracts.entities.Signal/Position` with `execution/order.py` types (10+ importers, runtime `_id` trains); `IBroker` vs `IBrokerPort` vs `IOMS` port collapse; PaperOMS vs LiveOMS pyramid/partial semantic merge (characterization only here). Next plan: services + boundaries (REF-07–11).
- Placeholder scan: every step has exact paths, code, commands, expected outputs. Task 2's context construction is Read-first with exact field rules (no guessed signatures).
- Type consistency: `normalize_status -> OrderStatus`, `is_terminal -> bool`, `BrokerFill` floats + marker, `snap_to_lot -> float`, `Position.id -> str`.
