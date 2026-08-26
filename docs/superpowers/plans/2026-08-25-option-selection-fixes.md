# Option Contract Selection Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the real bugs from the option-selection review: unaligned ATM strikes silently producing zero contracts, expired chains leaking through the expiry-advance loop, naive local dates, inconsistent delta floors, and dead/lying code in `select_expiry` and lot sizing.

**Architecture:** Small in-place edits to `quant/amt/session/scanner.py` and `quant/amt/session/selector.py`, plus one shared helper in `quant/contracts/timezones.py`. No new modules, no signature changes. Tests live beside existing ones in `tests/quant/amt/session/`.

**Tech Stack:** Python 3.11+, pytest (repo root `pytest.ini`, testpaths `tests` + `backend/tests`). Run tests from repo root.

## Global Constraints

- No new dependencies; stdlib only.
- Reuse `quant.contracts.timezones.IST` — never construct inline `timezone(timedelta(hours=5, minutes=30))`.
- Do NOT change risk-parameter values except where a task explicitly says so (Task 4 unifies the effective-delta floor at **0.30**, matching the documented "Fabio Cushion System").
- Existing public signatures must not change (`scan_top_n`, `select_strike`, `select_expiry`, `validate_option`, `translate_underlying_signal_to_option`, `compute_option_lot_size`).
- Mark deliberate simplifications with `# ponytail:` comments.

## Out of scope (reviewed, deliberately skipped)

- Whole-chain volume-ratio momentum detection — heuristic works; methodology change is not a bug fix. Upgrade path: OI-change-based bias.
- Hard-coded `delta=0.5` on fallback monitoring rows — cosmetic, monitoring-only.
- Minimum-1-lot floor in lot sizing — deliberate product decision, needs owner sign-off.
- Deleting dead `select_strike`/`select_expiry` — pinned by parity tests as an API contract; separate decision.

---

### Task 1: IST-safe "today" helper

The scanner and selector compare expiries against `date.today()` — machine-local time. On any non-IST host, DTE checks and expiry-day logic shift around midnight. The repo already centralizes IST in `quant/contracts/timezones.py`; add one helper there and adopt it at both call sites.

**Files:**
- Modify: `quant/contracts/timezones.py`
- Modify: `quant/amt/session/scanner.py`
- Modify: `quant/amt/session/selector.py` (`validate_option`, ~line 212)
- Test: `tests/quant/contracts/test_timezones.py`

**Interfaces:**
- Produces: `today_ist() -> date` from `quant.contracts.timezones`. Later tasks import it as `from quant.contracts.timezones import today_ist`.

- [ ] **Step 1: Write the failing test**

Create `tests/quant/contracts/test_timezones.py`:

```python
"""Tests for quant.contracts.timezones helpers."""
from datetime import datetime

from quant.contracts.timezones import IST, today_ist


def test_today_ist_matches_ist_clock():
    assert today_ist() == datetime.now(tz=IST).date()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quant/contracts/test_timezones.py -q`
Expected: FAIL with `ImportError: cannot import name 'today_ist'`

- [ ] **Step 3: Write minimal implementation**

In `quant/contracts/timezones.py`, change the import line:

```python
from datetime import date, datetime, time, timezone, timedelta
```

Append at the end of the file:

```python
def today_ist() -> date:
    """Current calendar date in IST — the exchange's date."""
    return datetime.now(tz=IST).date()
```

- [ ] **Step 4: Adopt at call sites**

In `quant/amt/session/scanner.py`, add to imports:

```python
from quant.contracts.timezones import today_ist
```

Replace every `date.today()` in `_scan_underlying_for_contracts` (the expiry-advance loop comparison and the big-move DTE check) with `today_ist()`. Keep the `date` import if still used elsewhere in the file after Task 3; remove it when unused.

In `quant/amt/session/selector.py`, add to imports:

```python
from quant.contracts.timezones import today_ist
```

In `validate_option`, replace `today = date.today()` with:

```python
        today = today_ist()
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/quant/contracts/test_timezones.py tests/quant/amt/session -q`
Expected: PASS (new test passes, existing session tests unaffected).

- [ ] **Step 6: Commit**

```bash
git add quant/contracts/timezones.py quant/amt/session/scanner.py quant/amt/session/selector.py tests/quant/contracts/test_timezones.py
git commit -m "fix: use IST calendar date for expiry/DTE comparisons"
```

---

### Task 2: Snap ATM to the listed strike grid

`_scan_underlying_for_contracts` generates candidate strikes as `atm + i*interval` using `chain.atm_strike` verbatim. If the broker returns an off-grid ATM (e.g. 23437), every `option_map.get(float(strike))` misses and the underlying silently yields zero contracts, dropping into the ATM-monitoring fallback. Root-cause fix: snap ATM to the nearest strike actually listed in the chain before generating candidates.

**Files:**
- Modify: `quant/amt/session/scanner.py` (~lines 260-262)
- Test: `tests/quant/amt/session/test_scanner.py`

**Interfaces:**
- Consumes: nothing new; uses `chain.calls.keys()`.
- Produces: behavior only — downstream scoring/filters unchanged.

- [ ] **Step 1: Write the failing test**

Add to `TestOptionScannerService` in `tests/quant/amt/session/test_scanner.py`:

```python
    def test_unaligned_atm_snaps_to_listed_strike(self):
        """Broker-reported atm_strike off the strike grid (e.g. 23437) must be
        snapped to the nearest listed strike, else all candidate lookups miss
        and the scan silently returns nothing."""
        calls = self._full_calls(atm=23400.0, interval=50)
        chain = _make_chain(
            atm=23437.0,  # off-grid spot print
            expiry_iso=_next_tuesday_iso(),
            calls=calls,
        )
        broker = MagicMock()
        broker.get_option_chain.return_value = chain

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert results, "off-grid ATM must still produce contracts"
        # Nearest listed strike to 23437 is 23450.
        assert results[0].strike == 23450
```

Note: `_make_chain` sets `chain.spot_price = spot_price or atm`, so spot is also 23437 — fine; only `atm_strike` drives candidate generation.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest "tests/quant/amt/session/test_scanner.py::TestOptionScannerService::test_unaligned_atm_snaps_to_listed_strike" -q`
Expected: FAIL — `assert results` fails (empty list); generated strikes 23387/23437/23487... match nothing on the 50-grid.

- [ ] **Step 3: Write minimal implementation**

In `_scan_underlying_for_contracts`, replace:

```python
        atm = chain.atm_strike
        interval = self._STRIKE_INTERVALS.get(u.upper(), 50)
```

with:

```python
        atm = chain.atm_strike
        interval = self._STRIKE_INTERVALS.get(u.upper(), 50)
        listed = sorted(chain.calls.keys())
        if listed:
            # ponytail: snap to nearest listed strike — broker atm prints
            # (e.g. 23437) off the grid make every candidate lookup miss.
            atm = min(listed, key=lambda s: abs(s - atm))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/quant/amt/session/test_scanner.py -q`
Expected: PASS — new test passes; aligned chains snap to themselves so existing tests unaffected.

- [ ] **Step 5: Commit**

```bash
git add quant/amt/session/scanner.py tests/quant/amt/session/test_scanner.py
git commit -m "fix: snap scanner ATM to nearest listed strike so off-grid spots don't empty scans"
```

---

### Task 3: Expired-chain guard in advance loop and fallback path

Two leaks let expired chains through:

1. The advance loop `while chain is not None and effective_expiry_index < 3:` exits when the index hits 3 while `chain` still holds whatever index 3 returned — never revalidated. Existing tests only pass because they reuse one stale-expiry mock chain and rely on this leak.
2. The ATM-monitoring fallback (~line 529) refetches with raw `expiry_index` and never checks expiry at all.

Fix both by validating `expiry >= today_ist()` before use.

**Files:**
- Modify: `quant/amt/session/scanner.py` (advance loop ~lines 224-258; fallback fetch ~lines 529-537)
- Test: `tests/quant/amt/session/test_scanner.py` (new tests + fix stale hardcoded expiries)
- Modify: `backend/tests/unit/domain/test_option_scanner.py` (same stale expiries)

**Interfaces:**
- Consumes: `today_ist` from Task 1.
- Produces: none new.

- [ ] **Step 1: Write failing tests and update tests that depend on the leak**

Several existing tests pass `expiry_iso="2026-03-20"` (in the past). After the fix those chains are correctly rejected, so give them live expiries using the existing `_next_tuesday_iso()` helper:

- `test_scanner_returns_result`: `expiry_iso=_next_tuesday_iso()`
- `test_scanner_returns_put`: `expiry_iso=_next_tuesday_iso()`
- `test_scan_top_n_picks_highest_score`: `expiry_iso=_next_tuesday_iso()`
- `test_scan_advances_past_expired_series`: already mixes past + future; keep as is.
- In `backend/tests/unit/domain/test_option_scanner.py`: same substitution for every past-dated `_make_chain(expiry_iso=...)`; copy the `_next_tuesday_iso()` helper into that file if absent.
- Any further failures in Step 4 caused by past-dated mock expiries: same substitution.

Add to `TestOptionScannerService`:

```python
    def test_all_expired_series_returns_empty(self):
        """When every series up to index cap 3 is expired, scan returns empty —
        it must never fall through with the last expired chain."""
        calls = self._full_calls()
        past = _make_chain(atm=23400.0, expiry_iso="2020-01-07", calls=calls)
        broker = MagicMock()
        broker.get_option_chain.return_value = past

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert results == []
        assert broker.get_option_chain.call_count == 4  # indexes 0..3 tried

    def test_fallback_monitoring_skips_expired_chain(self):
        """ATM-monitoring fallback must not monitor an expired series."""
        calls = self._full_calls()
        past = _make_chain(atm=23400.0, expiry_iso="2020-01-07", calls=calls)
        broker = MagicMock()
        broker.get_option_chain.return_value = past

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert results == []
```

Without the fix, both fail: the first returns scored contracts from the expired chain, the second returns 2 fallback monitoring rows with score=50.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/quant/amt/session/test_scanner.py -q`
Expected: the two new tests FAIL; updated existing tests may also fail until Step 3 lands.

- [ ] **Step 3: Write minimal implementation**

Replace the advance loop in `_scan_underlying_for_contracts` with:

```python
        effective_expiry_index = expiry_index
        chain = ensure_sync_adapter_result(
            "broker.get_option_chain",
            self._broker.get_option_chain,
            underlying=u,
            exchange=_exchange,
            expiry_index=effective_expiry_index,
        )
        while chain is not None:
            expiry_date = (
                chain.expiry.date()
                if hasattr(chain.expiry, "date")
                else (date.fromisoformat(chain.expiry) if isinstance(chain.expiry, str) else chain.expiry)
            )
            if expiry_date >= today_ist():
                break
            if effective_expiry_index >= 3:
                logger.info("%s: no live expiry up to index 3 — skipping", u)
                chain = None
                break
            effective_expiry_index += 1
            logger.info(
                "%s: exp %s is past — advancing to index %d",
                u,
                expiry_date,
                effective_expiry_index,
            )
            chain = ensure_sync_adapter_result(
                "broker.get_option_chain",
                self._broker.get_option_chain,
                underlying=u,
                exchange=_exchange,
                expiry_index=effective_expiry_index,
            )
```

In the fallback block, after the existing `if chain is None: continue`, add:

```python
                    _fb_exp = (
                        chain.expiry.date()
                        if hasattr(chain.expiry, "date")
                        else None
                    )
                    if _fb_exp is not None and _fb_exp < today_ist():
                        continue
```

Note: the big-move DTE check below the loop already uses `expiry_date`; it only runs when a live chain broke the loop, so it stays valid.

- [ ] **Step 4: Run tests**

Run: `pytest tests/quant/amt/session backend/tests/unit/domain/test_option_scanner.py -q`
Expected: PASS. Fix any remaining past-dated mock expiries with `_next_tuesday_iso()` until green.

Then the wider suite: `pytest tests/quant -q`
Expected: PASS (no behavior change for live-future chains).

- [ ] **Step 5: Commit**

```bash
git add quant/amt/session/scanner.py tests/quant/amt/session/test_scanner.py backend/tests/unit/domain/test_option_scanner.py
git commit -m "fix: never select or monitor an expired option series"
```

---

### Task 4: Unify effective-delta floor; drop dead cushion cap

Two inconsistencies in `selector.py`:

1. Stop translation clamps delta to `[0.20, 1.0]` (~line 434) while lot sizing clamps to `[0.30, 1.0]` (~line 309). Same underlying stop maps to different option risk depending on which function runs. Unify on **0.30** — the value documented in the Fabio Cushion System docstring — via one module constant. All existing translation tests use delta=0.50, so no pinned values change.
2. `compute_option_lot_size` line ~306: `min(cushion, session_profit * 0.30)` where `cushion = session_profit * 0.20` — the 30% cap can never bind. Delete the dead `min()` (behavior identical).

**Files:**
- Modify: `quant/amt/session/selector.py` (constant near config, floors at ~309/~434, cushion at ~302-306)
- Test: `tests/quant/amt/session/test_selector.py`

**Interfaces:**
- Produces: module constant `MIN_EFFECTIVE_DELTA: float = 0.30` in `quant.amt.session.selector`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/quant/amt/session/test_selector.py`:

```python
def test_effective_delta_floor_is_unified():
    """Stop translation and lot sizing must share one delta floor."""
    from quant.amt.session.selector import MIN_EFFECTIVE_DELTA

    assert MIN_EFFECTIVE_DELTA == 0.30


def test_translate_uses_shared_delta_floor():
    """A delta below the floor must clamp to the shared floor,
    not the old translation-only 0.20 floor."""
    from quant.amt.session.selector import MIN_EFFECTIVE_DELTA, OptionSelector
    from quant.decision.signal_builder import Signal

    sig = Signal(
        type="LONG", reason="t", entry=100.0, sl=98.0, tp=104.0, rr=2.0,
        model_label="m", symbol="NIFTY", timestamp=None,
    )
    out = OptionSelector().translate_underlying_signal_to_option(
        sig, "NIFTY 20 MAR 23400 CE", option_ltp=100.0, delta=0.05,
    )
    # eff_delta clamps to MIN_EFFECTIVE_DELTA: opt risk = 2.0 * 0.30 = 0.60
    assert out.sl == out.entry - abs(sig.entry - sig.sl) * MIN_EFFECTIVE_DELTA


def test_cushion_adds_twenty_pct_of_session_profit():
    """Session profit adds exactly 20% of profit to risk budget."""
    from quant.amt.session.selector import OptionSelector

    sel = OptionSelector()
    base = sel.compute_option_lot_size(
        account_equity=100_000, risk_pct=0.01, underlying_stop_points=20,
        option_delta=0.5, lot_size=65, session_profit=0.0,
    )
    with_cushion = sel.compute_option_lot_size(
        account_equity=100_000, risk_pct=0.01, underlying_stop_points=20,
        option_delta=0.5, lot_size=65, session_profit=50_000,
    )
    # Risk budget goes 1000 -> 11000 rupees (base + 20% of 50k).
    lots_base = 1000 / (65 * 20 * max(0.30, min(1.0, 0.5)))
    lots_cushion = 11000 / (65 * 20 * max(0.30, min(1.0, 0.5)))
    assert base == max(1, int(lots_base))
    assert with_cushion == min(int(lots_cushion), 50)
```

If `Signal` requires more fields than shown, mirror the constructor usage in `tests/quant/decision/test_option_signal_translation.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/quant/amt/session/test_selector.py -q`
Expected: FAIL — `ImportError: cannot import name 'MIN_EFFECTIVE_DELTA'`, and `test_translate_uses_shared_delta_floor` computes sl with the 0.20 floor.

- [ ] **Step 3: Write minimal implementation**

In `quant/amt/session/selector.py`, above `OptionSelectorConfig` add:

```python
# One floor for mapping underlying stops to option stops via delta.
# 0.30 per the Fabio Cushion System — shared by lot sizing and stop translation.
MIN_EFFECTIVE_DELTA = 0.30
```

In `compute_option_lot_size`, replace:

```python
        # 1. Calculate allowed rupee risk with intraday cushion
        base_risk = account_equity * risk_pct
        cushion = max(0.0, session_profit * 0.20) if session_profit > 0 else 0.0
        # Cap cushion at 30% of total session profit
        total_risk_rupees = base_risk + min(cushion, session_profit * 0.30 if session_profit > 0 else 0.0)
```

with:

```python
        # 1. Calculate allowed rupee risk with intraday cushion
        base_risk = account_equity * risk_pct
        # ponytail: cushion is exactly 20% of session profit — the old
        # min(..., 30% profit) cap could never bind.
        cushion = max(0.0, session_profit * 0.20) if session_profit > 0 else 0.0
        total_risk_rupees = base_risk + cushion
```

and replace `effective_delta = max(0.30, min(1.0, abs(option_delta)))` with:

```python
        effective_delta = max(MIN_EFFECTIVE_DELTA, min(1.0, abs(option_delta)))
```

Also update the docstring bullet `Option stop points = underlying_stop_points * max(0.30, ...)` to reference `MIN_EFFECTIVE_DELTA`.

In `translate_underlying_signal_to_option`, replace:

```python
        eff_delta = max(0.20, min(1.0, abs(delta)))
```

with:

```python
        eff_delta = max(MIN_EFFECTIVE_DELTA, min(1.0, abs(delta)))
```

and update the docstring formula lines (`max(0.20, ...)` → `max(MIN_EFFECTIVE_DELTA, ...)`).

- [ ] **Step 4: Run tests**

Run: `pytest tests/quant/amt/session/test_selector.py tests/quant/decision/test_option_signal_translation.py tests/quant/test_adversarial_regression.py -q`
Expected: PASS (translation tests all use delta=0.50, unaffected by the floor change).

- [ ] **Step 5: Commit**

```bash
git add quant/amt/session/selector.py tests/quant/amt/session/test_selector.py
git commit -m "fix: unify effective-delta floor at 0.30 and drop dead cushion cap"
```

---

### Task 5: select_expiry truthfulness cleanup

`select_expiry` is dead in production but pinned by parity tests — keep it, make it honest:

- Docstring says gamma-trap after **14:30** ("last 45 min"); comment says "last 15 min"; code uses `current_hour >= 15` (15:00–15:30 IST = last 30 min). Fix prose to match code: **after 15:00 IST, last 30 minutes**.
- Comment claims `min_dte` "default 1" but `min_days_to_expiry` defaults to **0**, making lines 365-366 unreachable (`parsed` non-empty was guaranteed earlier). Fix comment, delete dead tail.

**Files:**
- Modify: `quant/amt/session/selector.py:320-368`
- Test: existing parity tests only (no new tests — comments + provably-dead code).

**Interfaces:** none changed.

- [ ] **Step 1: Apply edits**

Replace the docstring block:

```
        Scalping-optimized strategy:
        - ALWAYS prefer current-week expiry for maximum gamma.
        - Only skip to next week if today IS expiry day AND after 14:30
          (gamma trap zone in last 45 min).
        - Minimum DTE=1 (allow 1-day expiry for gamma scalping).
```

with:

```
        Scalping-optimized strategy:
        - ALWAYS prefer current-week expiry for maximum gamma.
        - Only skip to next week if today IS expiry day AND after 15:00 IST
          (gamma trap zone — last 30 min before NSE close).
        - min_days_to_expiry gates the first pass (default 0 allows 0-DTE).
```

Replace:

```python
        min_dte = self.cfg.min_days_to_expiry  # default 1

        # Check if today is expiry day and we're in gamma-trap zone (after 14:30 IST)
        is_expiry_day = parsed[0] == today
        in_gamma_trap = is_expiry_day and current_hour >= 15  # 3 PM IST — last 15 min
```

with:

```python
        min_dte = self.cfg.min_days_to_expiry  # default 0 — 0-DTE allowed pre-trap

        # Gamma-trap zone: expiry day after 15:00 IST (last 30 min before close)
        is_expiry_day = parsed[0] == today
        in_gamma_trap = is_expiry_day and current_hour >= 15
```

Replace the tail:

```python
        # Even DTE=0 is acceptable for intraday scalping (before gamma trap)
        if parsed:
            return parsed[0].isoformat()

        return None
```

with:

```python
        # Even DTE=0 is acceptable for intraday scalping (before gamma trap).
        # ponytail: parsed is guaranteed non-empty by the early return above.
        return parsed[0].isoformat()
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/quant/amt/session/test_selector.py tests/quant/amt/session/test_parity* -q`
Expected: PASS (behavior identical; `parsed[0]` path was already the only reachable outcome).

- [ ] **Step 3: Commit**

```bash
git add quant/amt/session/selector.py
git commit -m "docs: correct select_expiry gamma-trap/DTE comments, drop unreachable branch"
```

---

### Final verification

- [ ] Full relevant suites:

```bash
pytest tests/quant/amt tests/quant/decision tests/quant/contracts backend/tests/unit/domain/test_option_scanner.py -q
```

Expected: all PASS.

- [ ] Parity checks still green:

```bash
pytest tests/quant/amt/session/test_parity.py tests/quant/amt/session/test_selector.py -q
```

Expected: PASS.

