# Spec 2 Footprint/CVD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make footprint updates timestamp-canonical and volume-conserving, and make CVD updates idempotent with read-only snapshots.

**Architecture:** Normalize timestamps at the footprint and CVD state boundaries using `epoch_to_iso`. Preserve existing state containers and math, adding only residual reconciliation and an explicit slope-persistence mutation switch.

**Tech Stack:** Python, pytest, existing `OHLC`, `FootprintCandle`, `epoch_to_iso`, and AMT compute functions.

## Global Constraints

- No money-path / auction / TimesFM / options / Gate1–4 risk changes.
- No mocks of production math; tests construct real `OHLC` values and use production analyzers.
- Keep backtest, replay, and live behavior on the same production classes.

---

### Task 1: Canonical, in-place footprint updates

**Files:**
- Modify: `quant/amt/orderflow/footprint.py`
- Test: `tests/quant/amt/orderflow/test_footprint.py`

**Interfaces:**
- Consumes: `epoch_to_iso(time: str | float | int | None) -> str`
- Produces: canonical footprint dict keys and in-place final-candle replacement

- [ ] Add tests that update the final candle at the same list length and assert completed entries survive.
- [ ] Add epoch/ISO collision tests for analyzer and tick accumulator.
- [ ] Run focused tests and confirm they fail before implementation.
- [ ] Normalize keys at both footprint state boundaries and use incremental replacement for equal length / growth-by-one.
- [ ] Run `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_footprint.py -q` and expect all tests to pass.

### Task 2: Gaussian side-volume conservation

**Files:**
- Modify: `quant/amt/orderflow/footprint.py`
- Test: `tests/quant/amt/orderflow/test_footprint.py`

**Interfaces:**
- Consumes: existing Gaussian weights and integer `FootprintLevel` volumes
- Produces: `Σask == round(buy_total)` and `Σbid == round(sell_total)`

- [ ] Add a rounding-sensitive real `OHLC` fixture and assertions for ask, bid, volume, and delta totals.
- [ ] Run the focused test and confirm pre-fix drift.
- [ ] Reconcile side-specific residuals onto the POC/heaviest raw level.
- [ ] Run the complete footprint test file and expect all tests to pass.

### Task 3: Idempotent and observational CVD

**Files:**
- Modify: `quant/amt/orderflow/cvd.py`
- Test: `tests/quant/amt/orderflow/test_cvd.py`

**Interfaces:**
- Consumes: normalized `OHLC.time`
- Produces: one state transition per normalized timestamp; mutation-free `state()`

- [ ] Add an epoch/ISO duplicate test asserting value and history advance once.
- [ ] Keep the existing backwards-time reset assertion.
- [ ] Add a repeated-`state()` test asserting slope sign history and emitted slope do not mutate.
- [ ] Run focused tests and confirm duplicate/read-mutation failures.
- [ ] Normalize before equal/backwards comparison; return state on equality.
- [ ] Add an explicit `_compute_slope(advance_persistence: bool = False)` path and call the mutating path only from `update()`.
- [ ] Run `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_cvd.py -q` and expect all tests to pass.

### Task 4: Debt closure and merge gate

**Files:**
- Modify: `docs/reviews/amt-math-debt-20260922.md`

- [ ] Move all four Spec 2 rows from “Still open” to “Already addressed or obsolete vs audit”.
- [ ] Correct the CVD `state()` claim only after the mutation-free test passes.
- [ ] Run `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture tests/quant/decision tests/quant/execution tests/quant/runtime -q`.
- [ ] Run the focused AMT order-flow tests alongside the repository merge gate if they are not included by that command.
- [ ] Record any intentional/obsolete item explicitly; otherwise close each as addressed.
# Spec 2 Footprint/CVD Implementation Plan

**Goal:** Honest footprint keys/conservation + CVD idempotent updates.

### Task 1: Normalize footprint keys + forming refresh
- Modify `quant/amt/orderflow/footprint.py`
- Test: same bar under epoch + ISO → one key; same-len refresh keeps prior candles

### Task 2: Gaussian residual conservation
- Adjust ask/bid residual onto POC level after round()
- Test: Σ ask+bid == volume (within 1 unit int), Σ(ask-bid) ≈ delta

### Task 3: CVD duplicate timestamp
- Skip delta add when normalized time == last
- Test: update twice same time → value unchanged

### Task 4: CVD state() read-only (if still mutating)
- Persistence append only inside `update`, not `state()`

### Task 5: Merge gate + debt doc Spec 2 rows
