# Signal Flow Truthfulness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the signal stream truthful — `SignalApproved` fires only when a signal is actually routed through the OMS, observer engines go silent, and a blocked approval emits exactly one `SignalBlocked` per blocking episode instead of spamming every 60s.

**Architecture:** All three changes live in `QuantEngine._decide()` (`quant/runtime.py`) plus one new event type in `quant/events.py`. Evaluation cadence is unchanged (every micro-bar); only *emissions* are gated. The portfolio/root vetoes still run every evaluation, so a signal that becomes executable trades immediately — the latch suppresses repeat *notifications* of the same unexecutable setup, never the evaluation itself.

**Tech Stack:** Python 3.12 (`.venv`), pytest, frozen-dataclass event bus (no registration needed for new event types; `transitions.apply_event` treats unknown events as no-ops).

## Global Constraints

- Run tests with `cd /Users/apple/Documents/v5-of-glassytrade-ai && .venv/bin/python -m pytest <path> -q`
- Never emit `SignalApproved` before `self._oms.submit()` succeeds (contract in `quant/execution/ports.py:4`)
- Event order on the live path stays: `DecisionProduced` → (submit) → `SignalApproved` → `PositionOpened`
- Do NOT add `SignalBlocked` to `quant/transitions.py` `apply_event` — unknown events are intentional no-ops in folds
- Do NOT touch `quantv2/` (dead code), `quant/decision/*`, or any gate logic — this plan changes emission, not decisions
- Existing tests that must stay green: `tests/quant/runtime/test_positive_approval.py`, `tests/quant/runtime/test_decide_golden.py`, `tests/quant/runtime/test_runtime.py`, `tests/quant/test_options_execution_isolation.py`, `tests/system/test_quant_execution_e2e.py`, `tests/quant/test_fast_determinism_parity.py`

---

### Task 1: Truthful SignalApproved — emit only after OMS submit

**Files:**
- Modify: `quant/runtime.py:934-955` (approved-branch head) and `quant/runtime.py:1003-1025` (post-submit block)
- Test: `tests/quant/runtime/test_signal_approval_truthful.py` (new)

**Interfaces:**
- Consumes: existing `SignalApproved`/`PositionOpened` events; `QuantEngine._bus`, `._oms`, `._risk`, `._portfolio_risk`
- Produces: `SignalApproved` semantic change — observers (`execution_enabled=False`) and pre-submit vetoes (sizing-0, portfolio reject, OMS raise) no longer emit it. Task 2 builds on the restructured approved-branch.

- [ ] **Step 1: Write the failing tests**

Create `tests/quant/runtime/test_signal_approval_truthful.py`:

```python
# tests/quant/runtime/test_signal_approval_truthful.py
"""SignalApproved means "routed through the OMS" (contract in
quant/execution/ports.py). Observer engines and pre-submit vetoes must not
emit it. Exactly one emission per real submission, before PositionOpened."""

from dataclasses import dataclass
from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.events import PositionOpened, SignalApproved
from quant.runtime import QuantEngine


@dataclass
class _ApprovedDecision:
    signal: Signal
    approved: bool = True
    reason: str = "Triple-A"
    phase: str = ""
    gate_results: tuple = ()
    block_reasons: tuple = ()
    model_label: str = "t"


def _signal():
    return Signal(
        type="LONG", reason="t", entry=14.0, sl=13.0, tp=16.0, rr=2.0,
        model_label="t", symbol="TRUTH-CALL", timestamp="t0",
    )


def _engine(execution_enabled=True, can_accept=(True, "")):
    pra = MagicMock()
    pra.can_accept.return_value = can_accept
    pra.register_open.return_value = True
    eng = QuantEngine(
        gateway=MagicMock(),
        symbol="TRUTH-CALL",
        portfolio_risk=pra,
        execution_enabled=execution_enabled,
    )
    eng._oms = MagicMock()
    eng._oms.lot_size = 1
    eng._oms.submit.return_value = MagicMock()
    eng._risk = MagicMock()
    eng._risk.can_trade.return_value = (True, "")
    eng._risk.state.return_value = MagicMock(trades_today=0, equity=1_000_000)
    eng._risk.position_size.return_value = 2
    stub = MagicMock()
    stub.should_enter.return_value = _ApprovedDecision(_signal())
    eng._strategy = stub
    captured = []
    eng._bus.subscribe(SignalApproved, lambda e: captured.append(e))
    eng._bus.subscribe(PositionOpened, lambda e: captured.append(e))
    return eng, captured


def _bar(n):
    return Bar(time=f"t{300 + n}", open=14.0, high=14.2, low=13.9, close=14.0, volume=10.0)


def test_observer_engine_emits_no_approval():
    eng, captured = _engine(execution_enabled=False)
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    assert captured == []
    eng._oms.submit.assert_not_called()


def test_sizing_zero_emits_no_approval():
    eng, captured = _engine()
    eng._risk.position_size.return_value = 0
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    assert captured == []
    eng._oms.submit.assert_not_called()


def test_portfolio_reject_emits_no_approval():
    eng, captured = _engine(can_accept=(False, "concurrent root position: TRUTH-CALL active"))
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    assert captured == []
    eng._oms.submit.assert_not_called()


def test_real_submission_emits_approval_before_position_opened():
    eng, captured = _engine()
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    eng._oms.submit.assert_called_once()
    assert [type(e).__name__ for e in captured] == ["SignalApproved", "PositionOpened"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_signal_approval_truthful.py -q`
Expected: FAIL — observer/sizing/portfolio tests see a `SignalApproved` event (it is currently emitted at `runtime.py:948` before all gates), so `captured == []` assertions fail.

- [ ] **Step 3: Move the emission (edit `quant/runtime.py:934-955`)**

Replace this block:

```python
        if decision.approved and decision.signal is not None:
            signal = decision.signal
            logger.info(
                "⚡ [APPROVED SIGNAL] %s: %s @ %.2f (SL=%.2f, TP=%.2f, RR=%.2f) — %s | trades_today=%d equity=₹%.0f",
                self.symbol,
                signal.type,
                signal.entry,
                signal.sl,
                signal.tp,
                signal.rr,
                decision.reason,
                risk_st.trades_today,
                risk_st.equity,
            )
            self._emit(SignalApproved(symbol=self.symbol, time=bar.time, signal=signal))
            # ponytail: underlying observer engines stream charts/data but must not submit orders
            if not getattr(self, "_execution_enabled", True):
                logger.debug(
                    "⏭️ [EXECUTION_DISABLED] %s: approved signal not submitted (underlying observer engine)",
                    self.symbol,
                )
                return
```

with:

```python
        if decision.approved and decision.signal is not None:
            signal = decision.signal
            # ponytail: underlying observer engines stream charts/data but must not submit orders
            if not getattr(self, "_execution_enabled", True):
                logger.debug(
                    "⏭️ [EXECUTION_DISABLED] %s: approved signal not submitted (underlying observer engine)",
                    self.symbol,
                )
                return
```

- [ ] **Step 4: Emit after successful submit (edit `quant/runtime.py:1003-1021`)**

Find the end of the submit try/except:

```python
            try:
                position = self._oms.submit(signal, quantity)
            except Exception:
                # C3: a broker/OMS submission failure must not kill the engine
                # thread, and the portfolio risk reserved above must be unwound
                # — the entry never happened, so leaving the reservation in
                # place would leak aggregate headroom for the rest of the day.
                logger.exception(
                    "❌ [ENTRY FAILED] %s: OMS submit raised — skipping entry and "
                    "unwinding risk reservation (engine stays alive)",
                    self.symbol,
                )
                if self._portfolio_risk is not None:
                    reserved = getattr(self, "_open_trade_risk", 0.0)
                    if reserved > 0:
                        self._portfolio_risk.release(reserved, symbol=self.symbol)
                    self._open_trade_risk = 0.0
                return
            self._entry_bar_index = self._bar_index
```

Insert between the end of the `except` block and `self._entry_bar_index = self._bar_index`:

```python
            logger.info(
                "⚡ [SIGNAL EXECUTED] %s: %s %s @ %.2f (SL=%.2f, TP=%.2f, RR=%.2f) — %s | trades_today=%d equity=₹%.0f",
                self.symbol,
                signal.type,
                signal.symbol,
                signal.entry,
                signal.sl,
                signal.tp,
                signal.rr,
                decision.reason,
                risk_st.trades_today,
                risk_st.equity,
            )
            # Contract (quant/execution/ports.py): every SignalApproved must
            # route through an IOMS — emit only after a successful submit.
            self._emit(SignalApproved(symbol=self.symbol, time=bar.time, signal=signal))
            self._entry_bar_index = self._bar_index
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_signal_approval_truthful.py tests/quant/test_options_execution_isolation.py tests/quant/runtime/test_positive_approval.py -q`
Expected: PASS (all 7 tests).

- [ ] **Step 6: Commit**

```bash
git add quant/runtime.py tests/quant/runtime/test_signal_approval_truthful.py
git commit -m "fix(runtime): emit SignalApproved only after OMS submit succeeds"
```

---

### Task 2: SignalBlocked event — one emission per blocking episode

**Files:**
- Modify: `quant/events.py` (add event), `quant/runtime.py` (import, init, helper, call sites, journal whitelists)
- Test: `tests/quant/runtime/test_signal_blocked_latch.py` (new)

**Interfaces:**
- Consumes: Task 1's restructured approved-branch (no emission before submit; the four non-execution exits are: execution-disabled return, sizing-0 return, portfolio can_accept reject, portfolio register reject, OMS-raise).
- Produces: `SignalBlocked(symbol, time, signal, reason)` event — journaled, fold-ignored (unknown-event no-op). `QuantEngine._latch_or_signal_block(signal, block_reason, bar_time)` is the single emission helper later tasks/UI can rely on.

- [ ] **Step 1: Write the failing tests**

Create `tests/quant/runtime/test_signal_blocked_latch.py`:

```python
# tests/quant/runtime/test_signal_blocked_latch.py
"""A blocked approval emits exactly one SignalBlocked per blocking episode.
Evaluation itself is never latched — vetoes still run every bar, so the
moment a signal becomes executable it trades."""

from dataclasses import dataclass
from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.events import SignalBlocked
from quant.runtime import QuantEngine


@dataclass
class _ApprovedDecision:
    signal: Signal
    approved: bool = True
    reason: str = "Triple-A"
    phase: str = ""
    gate_results: tuple = ()
    block_reasons: tuple = ()
    model_label: str = "t"


def _sig():
    return Signal(
        type="LONG", reason="t", entry=14.0, sl=13.0, tp=16.0, rr=2.0,
        model_label="t", symbol="LATCH-CALL", timestamp="t0",
    )


def _engine():
    pra = MagicMock()
    eng = QuantEngine(gateway=MagicMock(), symbol="LATCH-CALL", portfolio_risk=pra)
    eng._oms = MagicMock()
    eng._oms.lot_size = 1
    eng._oms.submit.return_value = MagicMock()
    eng._risk = MagicMock()
    eng._risk.can_trade.return_value = (True, "")
    eng._risk.state.return_value = MagicMock(trades_today=0, equity=1_000_000)
    eng._risk.position_size.return_value = 2
    stub = MagicMock()
    stub.should_enter.return_value = _ApprovedDecision(_sig())
    eng._strategy = stub
    blocked = []
    eng._bus.subscribe(SignalBlocked, lambda e: blocked.append(e))
    return eng, blocked, pra


def _bar(n):
    return Bar(time=f"t{300 + n}", open=14.0, high=14.2, low=13.9, close=14.0, volume=10.0)


def test_sizing_zero_emits_one_blocked_event():
    eng, blocked, _ = _engine()
    eng._risk.position_size.return_value = 0
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    assert len(blocked) == 1
    assert "0 lots" in blocked[0].reason


def test_portfolio_reject_emits_once_per_episode():
    pra = MagicMock()
    pra.can_accept.return_value = (False, "concurrent root position: LATCH-CALL active")
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    for i, bar_index in enumerate((10, 13, 16, 19)):  # each beyond the 2-bar debounce
        eng._bar_index = bar_index
        eng._decide({}, _bar(i))
    assert len(blocked) == 1
    assert pra.can_accept.call_count == 4  # evaluation continues, only emission is latched


def test_new_block_reason_starts_new_episode():
    pra = MagicMock()
    pra.can_accept.side_effect = [
        (False, "concurrent root position: X active"),
        (False, "portfolio open-risk limit: 100+50 > 120"),
    ]
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    eng._bar_index = 13
    eng._decide({}, _bar(1))
    assert len(blocked) == 2


def test_successful_entry_resets_latch():
    pra = MagicMock()
    pra.can_accept.side_effect = [
        (False, "concurrent root position: X active"),
        (True, ""),
        (False, "concurrent root position: X active"),
    ]
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    eng._bar_index = 10
    eng._decide({}, _bar(0))   # blocked → episode 1
    eng._bar_index = 13
    eng._decide({}, _bar(1))   # executes → latch cleared
    eng._bar_index = 16
    eng._decide({}, _bar(2))   # blocked again → fresh episode
    assert len(blocked) == 2
    eng._oms.submit.assert_called_once()


def test_sizing_zero_then_reason_change_emits_twice():
    eng, blocked, _ = _engine()
    eng._risk.position_size.side_effect = [0, 0]
    # same reason → one episode
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    eng._bar_index = 13
    eng._decide({}, _bar(1))
    assert len(blocked) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_signal_blocked_latch.py -q`
Expected: FAIL — `SignalBlocked` does not exist (`ImportError` from `quant.events`).

- [ ] **Step 3: Add the event (edit `quant/events.py`)**

Insert directly after the `SignalApproved` class (line ~50):

```python
@dataclass(frozen=True)
class SignalBlocked(Event):
    """An approved signal could not be routed through the OMS.

    Emitted once per blocking episode: repeats of the same (signal, side)
    blocked for the same reason are latched (debug-logged only) so the
    stream stays truthful without spamming. Never folded into engine state.
    """
    signal: "Signal"
    reason: str = ""
```

- [ ] **Step 4: Wire the latch into `quant/runtime.py`**

4a. Add `SignalBlocked` to the event imports (alphabetical block containing `SignalApproved` at line ~59):

```python
    SignalApproved,
    SignalBlocked,
```

4b. Init latch state — after `self._trace: deque[Event] = deque(maxlen=10_000)` (line ~333):

```python
        # Setup latch: last approved-but-blocked (signal identity, side) and
        # the block reason. Emits SignalBlocked once per blocking episode
        # instead of once per micro-bar. Never suppresses evaluation.
        self._latch_key: tuple[str, str] | None = None
        self._latch_block: str = ""
```

4c. Add the helper method (place directly after `_decide` ends):

```python
    def _latch_or_signal_block(self, signal, block_reason: str, bar_time: str) -> None:
        """Record a blocked approval. First occurrence of an episode (same
        signal blocked for the same reason) warns + emits SignalBlocked;
        repeats debug-log only. Evaluation is never suppressed."""
        key = (getattr(signal, "symbol", "") or self.symbol, str(signal.type))
        new_episode = key != self._latch_key or block_reason != self._latch_block
        self._latch_key, self._latch_block = key, block_reason
        if new_episode:
            logger.warning(
                "🛑 [SIGNAL BLOCKED] %s: %s %s @ %.2f — %s",
                self.symbol, signal.type, signal.symbol, signal.entry, block_reason,
            )
            self._emit(SignalBlocked(
                symbol=self.symbol, time=bar_time, signal=signal, reason=block_reason,
            ))
        else:
            logger.debug(
                "🛑 [SIGNAL BLOCKED] %s: %s %s @ %.2f — %s (repeat, latched)",
                self.symbol, signal.type, signal.symbol, signal.entry, block_reason,
            )
```

4d. Call sites in `_decide`'s approved branch (four non-execution exits):

Replace the sizing-0 block:

```python
            if quantity <= 0:
                logger.info(
                    "⏭️ [SIZING] %s: skipping entry — risk budget affords 0 lots "
                    "(entry=%.2f sl=%.2f lot=%d)",
                    self.symbol, signal.entry, signal.sl, self._oms.lot_size,
                )
                return
```

with:

```python
            if quantity <= 0:
                self._latch_or_signal_block(
                    signal,
                    f"risk budget affords 0 lots (entry={signal.entry:.2f} "
                    f"sl={signal.sl:.2f} lot={self._oms.lot_size})",
                    bar.time,
                )
                return
```

Replace the can_accept reject block:

```python
                if not ok:
                    logger.warning(
                        "🛑 [PORTFOLIO RISK] %s: entry rejected — %s",
                        self.symbol, why,
                    )
                    self._last_rejected_bar_index = self._bar_index
                    return
```

with:

```python
                if not ok:
                    self._latch_or_signal_block(signal, why, bar.time)
                    self._last_rejected_bar_index = self._bar_index
                    return
```

Replace the register reject block:

```python
                if not self._portfolio_risk.register_open(trade_risk, symbol=self.symbol):
                    logger.warning(
                        "🛑 [PORTFOLIO RISK] %s: entry rejected at register — "
                        "cap breached between can_accept and register",
                        self.symbol,
                    )
                    self._last_rejected_bar_index = self._bar_index
                    return
```

with:

```python
                if not self._portfolio_risk.register_open(trade_risk, symbol=self.symbol):
                    self._latch_or_signal_block(
                        signal, "portfolio cap breached between can_accept and register", bar.time,
                    )
                    self._last_rejected_bar_index = self._bar_index
                    return
```

Replace the OMS-raise log inside the `except Exception:` block (keep the reservation unwind):

```python
                logger.exception(
                    "❌ [ENTRY FAILED] %s: OMS submit raised — skipping entry and "
                    "unwinding risk reservation (engine stays alive)",
                    self.symbol,
                )
```

with:

```python
                logger.exception(
                    "❌ [ENTRY FAILED] %s: OMS submit raised — skipping entry and "
                    "unwinding risk reservation (engine stays alive)",
                    self.symbol,
                )
                self._latch_or_signal_block(signal, "OMS submit raised — broker/OMS failure", bar.time)
```

4e. Clear the latch on success — in Task 1's inserted block, right after `self._entry_bar_index = self._bar_index`:

```python
            self._latch_key = None
            self._latch_block = ""
```

4f. Journal both whitelists — add `SignalBlocked` to the two tuples at `quant/runtime.py:320-324` and `quant/runtime.py:417-421`:

```python
        for evt_type in (BarClosed, DecisionProduced,
                        SignalApproved, SignalBlocked,
                        PositionOpened, PositionClosed,
                        PositionReduced,
                        RiskUpdated, DepthUpdated, AmtUpdated,
                        OrderSubmitted, OrderFilled, StopMoved):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_signal_blocked_latch.py tests/quant/runtime/test_signal_approval_truthful.py -q`
Expected: PASS (all 11 tests).

- [ ] **Step 6: Commit**

```bash
git add quant/events.py quant/runtime.py tests/quant/runtime/test_signal_blocked_latch.py
git commit -m "feat(runtime): SignalBlocked event, once per blocking episode"
```

---

### Task 3: Full-suite verification

**Files:**
- None modified (verification only)

**Interfaces:**
- Consumes: Tasks 1-2 complete.
- Produces: confidence that no existing behavior (golden traces, e2e fills, restore folds) regressed.

- [ ] **Step 1: Run the runtime + decision + system suites**

Run: `.venv/bin/python -m pytest tests/quant/runtime tests/quant/test_options_execution_isolation.py tests/system/test_quant_execution_e2e.py tests/quant/test_fast_determinism_parity.py tests/quant/test_portfolio_risk_guard.py -q`
Expected: all PASS. If `test_decide_golden.py::test_decide_golden_matches_committed_snapshot` fails, STOP and investigate — the golden tape contains no approvals, so a failure means unintended behavior drift (do NOT regenerate the snapshot for this change).

- [ ] **Step 2: Run the full quant suite**

Run: `.venv/bin/python -m pytest tests/quant -q`
Expected: PASS (baseline ~950 passed, some skipped). Fix any failures caused by SignalApproved timing assumptions before proceeding.

- [ ] **Step 3: Grep for stale assumptions**

Run: `grep -rn "APPROVED SIGNAL" quant/ backend/app/ tests/ ; grep -rn "SignalApproved" backend/app/ | grep -v test`
Expected: no production code references the old log string; backend/app does not consume `SignalApproved` (verified during audit — only quant/ journals it).

- [ ] **Step 4: Commit (only if verification required fixes)**

```bash
git add -A tests/
git commit -m "test: adjust suites for truthful signal emission semantics"
```

---

## Self-Review

**1. Spec coverage:** The three P0 fixes from the audit are covered: (P0-1) emission after gates → Task 1; (P0-2) observer silence → Task 1 Step 3 (execution-disabled return precedes all emission); (P0-3) setup latch → Task 2 (episode latch — state-driven, no arbitrary time window, so a signal that becomes executable trades immediately; evaluation cadence unchanged).

**2. Placeholder scan:** Every step has complete code, exact anchors quoted from the current file, and exact pytest commands with expected outcomes. No TBDs.

**3. Type consistency:** `_latch_or_signal_block(signal, block_reason, bar_time)` signature used identically at all four call sites; `SignalBlocked(signal, reason)` matches the dataclass; latch attrs `_latch_key`/`_latch_block` initialized in `__init__` and referenced in helper + success-clear. Test helper `_engine()` matches the real `QuantEngine.__init__` kwargs proven by `test_options_execution_isolation.py` (`gateway`, `symbol`, `portfolio_risk`, `execution_enabled`).

## Notes for the implementer

- The log message changes from `⚡ [APPROVED SIGNAL]` to `⚡ [SIGNAL EXECUTED]` — intentional; update any log-grepping runbooks/dashboards.
- `DecisionProduced` cadence is deliberately unchanged: one per micro-bar evaluation is the designed decision stream, not spam. The flood the user saw came from pre-gate `SignalApproved` + `⚡` logs, both fixed here.
- Do not "optimize" by skipping evaluation when latched — the latch deliberately gates only emissions so a freed root/portfolio instantly executes a still-valid setup.
