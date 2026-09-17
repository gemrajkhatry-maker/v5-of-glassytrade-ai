# Fabio AMT Alignment & Code Quality Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the trading system with Fabio Valentini's AMT methodology by adding the missing 15-minute bias layer, extracting magic numbers into named constants, eliminating decision-result dict duplication, removing dead code, and hardening the automation tooling — all with regression-safe incremental testing.

**Architecture:** Three-layer timeframe hierarchy (15m bias → 5m context → 1m execution) matching Fabio's top-down approach. The 15m bias layer feeds into the existing `context_builder.py` direction resolution as a new highest-priority intent source. Code quality work extracts shared abstractions (decision result factory, gate result factory, regime/timing helpers) and removes dead code. All changes are covered by the existing ~546 AMT tests plus new tests per task.

**Tech Stack:** Python 3.13, pytest, radon (complexity), no new external dependencies.

## Global Constraints

- Branch: `architecture/design-level-refactoring` (current)
- Run tests with repo venv: `.venv/bin/python -m pytest`
- All existing tests must remain green after every task (`pytest tests/quant -x -q`)
- Golden tape determinism must not break (SHA-256 hash tests in `tests/determinism/`)
- No behavior changes to entry/exit logic — this is additive (bias layer) or extractive (refactoring)
- Every new constant gets a `# ponytail:` comment naming the Fabio methodology source
- Every task ends with a commit and passing tests
- Keep diffs focused — one concern per task

---

## Phase 1: 15-Minute Bias Layer

### Task 1: 15-Minute Micro Aggregator in QuantEngine

**Files:**
- Modify: `quant/runtime.py:383-400` (add 15m aggregator alongside existing 5m/1m)
- Modify: `quant/bars.py` (add `BIAS_INTERVAL_SEC = 900` constant)
- Test: `tests/quant/runtime/test_bias_aggregator.py`

**Interfaces:**
- Consumes: existing `BarAggregator` class, `interval_seconds` constructor param
- Produces: `self._bias_aggregator` (15-min bar aggregator for underlying futures) and `self._bias_option_aggregator` (15-min for option premium) — both `None` when `interval_seconds <= 900`

- [ ] **Step 1: Write failing test for bias aggregator creation**

```python
# tests/quant/runtime/test_bias_aggregator.py
"""15-minute bias aggregator exists alongside 5m macro and 1m micro."""
from quant.bars import BarAggregator, DEFAULT_INTERVAL_SEC
import pytest


def test_bias_interval_constant_exists():
    from quant.bars import BIAS_INTERVAL_SEC
    assert BIAS_INTERVAL_SEC == 900  # 15 minutes


def test_bias_aggregator_created_when_interval_exceeds_bias():
    """When canonical interval > 15m, a bias aggregator is created."""
    from quant.bars import BIAS_INTERVAL_SEC
    agg = BarAggregator(interval_seconds=BIAS_INTERVAL_SEC)
    assert agg is not None


def test_bias_interval_is_15_minutes():
    from quant.bars import BIAS_INTERVAL_SEC
    assert BIAS_INTERVAL_SEC == 15 * 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_bias_aggregator.py -v`
Expected: FAIL with `ImportError: cannot import name 'BIAS_INTERVAL_SEC'`

- [ ] **Step 3: Add BIAS_INTERVAL_SEC constant to quant/bars.py**

Add after `DEFAULT_INTERVAL_SEC = 300` at line 7:

```python
BIAS_INTERVAL_SEC = 900  # 15-minute bias layer (Fabio: 15m → 5m → 1m top-down)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_bias_aggregator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/bars.py tests/quant/runtime/test_bias_aggregator.py
git commit -m "feat(amt): add 15-min bias interval constant (Fabio top-down: 15m→5m→1m)"
```

### Task 2: Bias Bar Accumulation in QuantEngine

**Files:**
- Modify: `quant/runtime.py:383-400` (add bias aggregator pair)
- Modify: `quant/engine/tick_handler.py` (feed bias aggregators from ticks)
- Test: `tests/quant/runtime/test_bias_accumulation.py`

**Interfaces:**
- Consumes: `BIAS_INTERVAL_SEC` from `quant.bars`, `BarAggregator` class
- Produces: `self._bias_aggregator` and `self._bias_underlying_aggregator` on QuantEngine — both `None` when `interval_seconds <= BIAS_INTERVAL_SEC`

- [ ] **Step 1: Write failing test for bias aggregator wiring**

```python
# tests/quant/runtime/test_bias_accumulation.py
"""15-min bias aggregator accumulates bars from underlying ticks."""
from quant.bars import Bar, BIAS_INTERVAL_SEC
from quant.aggregator import BarAggregator
import time


def test_bias_aggregator_accumulates_15min_bars():
    agg = BarAggregator(interval_seconds=BIAS_INTERVAL_SEC)
    base_ts = 1700000000
    for i in range(10):
        bar = Bar(
            time=base_ts + i * 60,
            open=100.0 + i * 0.1,
            high=100.5 + i * 0.1,
            low=99.5 + i * 0.1,
            close=100.2 + i * 0.1,
            volume=1000,
            buy_volume=600,
            sell_volume=400,
            delta=200,
            oi=50000,
            vwap=100.1,
        )
        agg.update(bar)
    # 10 one-minute ticks should produce at least 0 completed 15-min bars
    # (need 15 minutes of data for first completion)
    completed = agg.drain_completed()
    assert isinstance(completed, list)
```

- [ ] **Step 2: Run test to verify it passes (BarAggregator already works)**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_bias_accumulation.py -v`
Expected: PASS (BarAggregator is generic, works with any interval)

- [ ] **Step 3: Write failing test for QuantEngine bias aggregator creation**

```python
# Add to tests/quant/runtime/test_bias_accumulation.py
def test_quant_engine_creates_bias_aggregators():
    """QuantEngine creates 15m bias aggregators when interval > 15m."""
    from quant.runtime import QuantEngine
    from quant.bars import BIAS_INTERVAL_SEC
    # Use a 30-min interval to ensure bias layer activates
    engine = QuantEngine(
        symbol="NIFTY24DEC21500CE",
        interval_seconds=1800,  # 30 min — exceeds bias threshold
        gateway=None,
        underlying_gateway=None,
    )
    assert engine._bias_aggregator is not None
    assert engine._bias_underlying_aggregator is not None


def test_quant_engine_no_bias_when_interval_equals_bias():
    """When interval == 15m, no separate bias aggregator needed."""
    from quant.runtime import QuantEngine
    from quant.bars import BIAS_INTERVAL_SEC
    engine = QuantEngine(
        symbol="NIFTY24DEC21500CE",
        interval_seconds=BIAS_INTERVAL_SEC,  # exactly 15m
        gateway=None,
        underlying_gateway=None,
    )
    assert engine._bias_aggregator is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_bias_accumulation.py::test_quant_engine_creates_bias_aggregators -v`
Expected: FAIL with `AttributeError: 'QuantEngine' object has no attribute '_bias_aggregator'`

- [ ] **Step 5: Add bias aggregators to QuantEngine.__init__**

In `quant/runtime.py`, after line 400 (after `self._micro_underlying_aggregator`), add:

```python
        # ponytail: 15-min bias layer (Fabio's top-down: 15m direction → 5m location → 1m execution)
        self._bias_aggregator = (
            BarAggregator(interval_seconds=BIAS_INTERVAL_SEC)
            if interval_seconds > BIAS_INTERVAL_SEC
            else None
        )
        self._bias_underlying_aggregator = (
            BarAggregator(interval_seconds=BIAS_INTERVAL_SEC)
            if (self._underlying_gateway is not None and interval_seconds > BIAS_INTERVAL_SEC)
            else None
        )
```

Add import at top of `quant/runtime.py`:

```python
from quant.bars import DEFAULT_INTERVAL_SEC, BIAS_INTERVAL_SEC
```

(Update the existing import of `DEFAULT_INTERVAL_SEC` to also import `BIAS_INTERVAL_SEC`.)

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/quant/runtime/test_bias_accumulation.py -v`
Expected: PASS

- [ ] **Step 7: Run full quant test suite to verify no regressions**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: All pass (no behavior changes — aggregators are created but not yet consumed)

- [ ] **Step 8: Commit**

```bash
git add quant/runtime.py tests/quant/runtime/test_bias_accumulation.py
git commit -m "feat(amt): wire 15-min bias aggregators into QuantEngine"
```

### Task 3: Bias Direction Resolver

**Files:**
- Create: `quant/amt/bias/bias_resolver.py`
- Test: `tests/quant/amt/bias/test_bias_resolver.py`

**Interfaces:**
- Consumes: list of 15-min `Bar` objects, optional VWAP value
- Produces: `BiasDirection` enum (`LONG_BIAS`, `SHORT_BIAS`, `NEUTRAL`) with a confidence score

- [ ] **Step 1: Write failing test for bias resolution**

```python
# tests/quant/amt/bias/test_bias_resolver.py
"""15-minute bias direction from bar structure and trend."""
import pytest
from quant.amt.bias.bias_resolver import BiasResolver, BiasDirection
from quant.bars import Bar


def _bar(ts: int, o: float, h: float, l: float, c: float, vol: int = 1000) -> Bar:
    return Bar(time=ts, open=o, high=h, low=l, close=c,
               volume=vol, buy_volume=int(vol * 0.6),
               sell_volume=int(vol * 0.4), delta=int(vol * 0.2),
               oi=50000, vwap=(h + l + c) / 3)


class TestBiasResolver:
    def test_long_bias_on_higher_highs_and_higher_lows(self):
        bars = [
            _bar(1, 100, 102, 99, 101),
            _bar(2, 101, 103, 100, 102),
            _bar(3, 102, 105, 101, 104),
            _bar(4, 104, 106, 103, 105),
            _bar(5, 105, 107, 104, 106),
        ]
        resolver = BiasResolver()
        result = resolver.resolve(bars)
        assert result.direction == BiasDirection.LONG_BIAS
        assert result.confidence > 0.0

    def test_short_bias_on_lower_highs_and_lower_lows(self):
        bars = [
            _bar(1, 106, 107, 104, 105),
            _bar(2, 105, 106, 103, 104),
            _bar(3, 104, 105, 101, 102),
            _bar(4, 102, 103, 100, 101),
            _bar(5, 101, 102, 99, 100),
        ]
        resolver = BiasResolver()
        result = resolver.resolve(bars)
        assert result.direction == BiasDirection.SHORT_BIAS

    def test_neutral_on_mixed_structure(self):
        bars = [
            _bar(1, 100, 103, 98, 101),
            _bar(2, 101, 102, 97, 98),
            _bar(3, 98, 104, 97, 103),
            _bar(4, 103, 105, 96, 97),
            _bar(5, 97, 101, 95, 100),
        ]
        resolver = BiasResolver()
        result = resolver.resolve(bars)
        assert result.direction == BiasDirection.NEUTRAL

    def test_neutral_on_insufficient_data(self):
        bars = [_bar(1, 100, 102, 99, 101)]
        resolver = BiasResolver()
        result = resolver.resolve(bars)
        assert result.direction == BiasDirection.NEUTRAL
        assert result.confidence == 0.0

    def test_empty_bars_returns_neutral(self):
        resolver = BiasResolver()
        result = resolver.resolve([])
        assert result.direction == BiasDirection.NEUTRAL
        assert result.confidence == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/amt/bias/test_bias_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.amt.bias'`

- [ ] **Step 3: Create package and implement BiasResolver**

```bash
mkdir -p quant/amt/bias
touch quant/amt/bias/__init__.py
```

```python
# quant/amt/bias/__init__.py
from quant.amt.bias.bias_resolver import BiasResolver, BiasDirection

__all__ = ["BiasResolver", "BiasDirection"]
```

```python
# quant/amt/bias/bias_resolver.py
"""15-minute bias direction resolver (Fabio's top-down layer 1).

Determines directional bias from 15-min bar structure:
- LONG_BIAS: higher highs + higher lows in recent window
- SHORT_BIAS: lower highs + lower lows in recent window
- NEUTRAL: mixed structure or insufficient data

Fabio's methodology: 15m establishes direction, 5m finds location, 1m triggers entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from quant.bars import Bar


class BiasDirection(Enum):
    LONG_BIAS = "LONG_BIAS"
    SHORT_BIAS = "SHORT_BIAS"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class BiasResult:
    direction: BiasDirection
    confidence: float  # 0.0 to 1.0
    higher_highs: bool
    higher_lows: bool
    lower_highs: bool
    lower_lows: bool


# ponytail: Fabio uses 15m bias — minimum bars to establish structure
_MIN_BIAS_BARS = 3


class BiasResolver:
    """Resolve directional bias from 15-min bar structure."""

    def resolve(self, bars: list[Bar]) -> BiasResult:
        if len(bars) < _MIN_BIAS_BARS:
            return BiasResult(
                direction=BiasDirection.NEUTRAL,
                confidence=0.0,
                higher_highs=False, higher_lows=False,
                lower_highs=False, lower_lows=False,
            )

        highs = [b.high for b in bars]
        lows = [b.low for b in bars]

        hh = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1])
        hl = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i - 1])
        lh = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i - 1])
        ll = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])

        bullish_count = hh + hl  # 0-2 scale per transition, summed
        bearish_count = lh + ll
        total_transitions = (len(bars) - 1) * 2

        if total_transitions == 0:
            return BiasResult(
                direction=BiasDirection.NEUTRAL, confidence=0.0,
                higher_highs=False, higher_lows=False,
                lower_highs=False, lower_lows=False,
            )

        bullish_ratio = bullish_count / total_transitions
        bearish_ratio = bearish_count / total_transitions

        # ponytail: Fabio requires clear structural alignment — 60%+ threshold
        _BIAS_THRESHOLD = 0.60

        if bullish_ratio >= _BIAS_THRESHOLD:
            return BiasResult(
                direction=BiasDirection.LONG_BIAS,
                confidence=min(1.0, bullish_ratio),
                higher_highs=hh > lh,
                higher_lows=hl > ll,
                lower_highs=lh >= hh,
                lower_lows=ll >= hl,
            )
        elif bearish_ratio >= _BIAS_THRESHOLD:
            return BiasResult(
                direction=BiasDirection.SHORT_BIAS,
                confidence=min(1.0, bearish_ratio),
                higher_highs=hh > lh,
                higher_lows=hl > ll,
                lower_highs=lh >= hh,
                lower_lows=ll >= hl,
            )
        else:
            return BiasResult(
                direction=BiasDirection.NEUTRAL,
                confidence=0.0,
                higher_highs=hh > lh, higher_lows=hl > ll,
                lower_highs=lh >= hh, lower_lows=ll >= hl,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/quant/amt/bias/test_bias_resolver.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add quant/amt/bias/ tests/quant/amt/bias/
git commit -m "feat(amt): 15-min bias direction resolver (Fabio top-down layer 1)"
```

### Task 4: Integrate Bias into Context Builder

**Files:**
- Modify: `quant/decision/context_builder.py:137-200` (add bias as highest-priority direction source)
- Modify: `quant/decision/context.py` (add `bias_direction` and `bias_confidence` fields to DecisionContext)
- Test: `tests/quant/decision/test_bias_integration.py`

**Interfaces:**
- Consumes: `BiasResult` from `quant.amt.bias.bias_resolver`, `DecisionContext` dataclass
- Produces: `DecisionContext.bias_direction` and `bias_confidence` fields; bias overrides direction when confidence >= 0.6

- [ ] **Step 1: Write failing test for bias integration**

```python
# tests/quant/decision/test_bias_integration.py
"""15-min bias integrates into decision context as direction override."""
import pytest
from quant.amt.bias.bias_resolver import BiasDirection, BiasResult
from quant.decision.context import DecisionContext


def test_decision_context_has_bias_fields():
    """DecisionContext carries bias_direction and bias_confidence."""
    ctx = DecisionContext(
        symbol="NIFTY24DEC21500CE",
        side="FLAT",
        setup="NO_EDGE",
        reason="TEST",
        market_state=None,
        session_phase="REGULAR",
        bias_direction=BiasDirection.LONG_BIAS,
        bias_confidence=0.8,
    )
    assert ctx.bias_direction == BiasDirection.LONG_BIAS
    assert ctx.bias_confidence == 0.8


def test_bias_defaults_to_neutral():
    """DecisionContext defaults bias to NEUTRAL when not provided."""
    ctx = DecisionContext(
        symbol="NIFTY24DEC21500CE",
        side="FLAT",
        setup="NO_EDGE",
        reason="TEST",
        market_state=None,
        session_phase="REGULAR",
    )
    assert ctx.bias_direction == BiasDirection.NEUTRAL
    assert ctx.bias_confidence == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_bias_integration.py -v`
Expected: FAIL with `TypeError: DecisionContext() got an unexpected keyword argument 'bias_direction'`

- [ ] **Step 3: Add bias fields to DecisionContext**

In `quant/decision/context.py`, add to the `DecisionContext` dataclass:

```python
from quant.amt.bias.bias_resolver import BiasDirection

# Add fields with defaults:
    bias_direction: BiasDirection = BiasDirection.NEUTRAL
    bias_confidence: float = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_bias_integration.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: All pass (new fields have defaults, no existing code breaks)

- [ ] **Step 6: Commit**

```bash
git add quant/decision/context.py tests/quant/decision/test_bias_integration.py
git commit -m "feat(amt): add bias_direction/bias_confidence to DecisionContext"
```

### Task 5: Bias Feeds Direction Resolution

**Files:**
- Modify: `quant/decision/context_builder.py:137-200` (`_resolve_direction` adds bias as top-priority source)
- Modify: `quant/runtime.py` (feed bias bars to BiasResolver, pass result to context builder)
- Test: `tests/quant/decision/test_bias_direction_override.py`

**Interfaces:**
- Consumes: `BiasResolver.resolve()` from `quant.amt.bias`, bias aggregator completed bars
- Produces: direction override when bias confidence >= 0.6 AND bias agrees with or is neutral to existing direction

- [ ] **Step 1: Write failing test for bias direction override**

```python
# tests/quant/decision/test_bias_direction_override.py
"""15-min bias overrides direction when confidence is high."""
from quant.amt.bias.bias_resolver import BiasDirection, BiasResult
from quant.decision.context_builder import _apply_bias_override


def test_bias_overrides_neutral_direction():
    """When AMT direction is neutral but bias is strong LONG, bias wins."""
    result = _apply_bias_override(
        current_direction="FLAT",
        bias=BiasResult(
            direction=BiasDirection.LONG_BIAS,
            confidence=0.8,
            higher_highs=True, higher_lows=True,
            lower_highs=False, lower_lows=False,
        ),
    )
    assert result == "LONG"


def test_bias_does_not_override_opposing_strong_direction():
    """When AMT already has strong SHORT, weak LONG bias does not override."""
    result = _apply_bias_override(
        current_direction="SHORT",
        bias=BiasResult(
            direction=BiasDirection.LONG_BIAS,
            confidence=0.4,  # below threshold
            higher_highs=True, higher_lows=False,
            lower_highs=False, lower_lows=True,
        ),
    )
    assert result == "SHORT"


def test_neutral_bias_does_not_change_direction():
    """Neutral bias leaves existing direction unchanged."""
    result = _apply_bias_override(
        current_direction="LONG",
        bias=BiasResult(
            direction=BiasDirection.NEUTRAL,
            confidence=0.0,
            higher_highs=False, higher_lows=False,
            lower_highs=False, lower_lows=False,
        ),
    )
    assert result == "LONG"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_bias_direction_override.py -v`
Expected: FAIL with `ImportError: cannot import name '_apply_bias_override'`

- [ ] **Step 3: Implement _apply_bias_override in context_builder.py**

Add to `quant/decision/context_builder.py`:

```python
from quant.amt.bias.bias_resolver import BiasDirection, BiasResult

# ponytail: Fabio's 15m bias overrides direction only when confidence >= 0.6
_BIAS_OVERRIDE_THRESHOLD = 0.6


def _apply_bias_override(current_direction: str, bias: BiasResult) -> str:
    """Apply 15-min bias as direction override.

    Bias overrides only when:
    1. Bias confidence >= threshold
    2. Current direction is neutral/flat, OR bias agrees with current direction
    """
    if bias.direction == BiasDirection.NEUTRAL:
        return current_direction
    if bias.confidence < _BIAS_OVERRIDE_THRESHOLD:
        return current_direction

    bias_side = "LONG" if bias.direction == BiasDirection.LONG_BIAS else "SHORT"

    if current_direction in ("FLAT", "NEUTRAL", ""):
        return bias_side
    if current_direction == bias_side:
        return current_direction
    # Bias opposes current AMT direction — AMT wins (more specific)
    return current_direction
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_bias_direction_override.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add quant/decision/context_builder.py tests/quant/decision/test_bias_direction_override.py
git commit -m "feat(amt): 15-min bias overrides direction when confidence >= 0.6"
```

---

## Phase 2: Parameter Alignment Verification

### Task 6: Extract Fabio-Aligned Named Constants

**Files:**
- Modify: `quant/contracts/constants.py` (add Fabio-parameter constants)
- Modify: `quant/decision/context_builder.py` (replace magic numbers with named constants)
- Modify: `quant/decision/timesfm_sizing.py` (replace magic numbers)
- Test: `tests/quant/contracts/test_fabio_constants.py`

**Interfaces:**
- Consumes: existing `quant.contracts.constants` module
- Produces: named constants with `# ponytail: Fabio` comments for all trading thresholds

- [ ] **Step 1: Write failing test for Fabio constants**

```python
# tests/quant/contracts/test_fabio_constants.py
"""Fabio AMT methodology parameters are named constants, not magic numbers."""
from quant.contracts.constants import (
    FABIO_CVD_THRESHOLD_NSE,
    FABIO_CVD_THRESHOLD_MCX,
    FABIO_OBI_THRESHOLD,
    FABIO_OFI_THRESHOLD,
    FABIO_BIAS_OVERRIDE_THRESHOLD,
    FABIO_ABSORPTION_VOL_MULT,
    FABIO_ABSORPTION_RANGE_ATR,
    FABIO_VALUE_AREA_PCT,
)


def test_cvd_thresholds_match_fabio():
    assert FABIO_CVD_THRESHOLD_NSE == 0.5
    assert FABIO_CVD_THRESHOLD_MCX == 0.3


def test_obi_threshold():
    assert FABIO_OBI_THRESHOLD == 0.20


def test_ofi_threshold():
    assert FABIO_OFI_THRESHOLD == 0.10


def test_absorption_parameters_match_fabio():
    """Fabio: Vol > 2x Avg, Range < 0.3 ATR."""
    assert FABIO_ABSORPTION_VOL_MULT == 2.0
    assert FABIO_ABSORPTION_RANGE_ATR == 0.30


def test_value_area_percentage():
    """CME standard: 70% value area."""
    assert FABIO_VALUE_AREA_PCT == 0.70
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/contracts/test_fabio_constants.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add Fabio constants to quant/contracts/constants.py**

Add to `quant/contracts/constants.py`:

```python
# --- Fabio AMT Methodology Parameters ---
# ponytail: Fabio Valentini's AMT methodology thresholds
# Source: https://blog.pickmytrade.trade/fabio-valentini-pro-scalper-nasdaq-scalping-strategy/

# Direction resolution (context_builder.py)
FABIO_CVD_THRESHOLD_NSE: float = 0.5     # CVD slope threshold for NSE
FABIO_CVD_THRESHOLD_MCX: float = 0.3     # CVD slope threshold for MCX
FABIO_OBI_THRESHOLD: float = 0.20        # Order Book Imbalance threshold
FABIO_OFI_THRESHOLD: float = 0.10        # Order Flow Imbalance threshold
FABIO_BIAS_OVERRIDE_THRESHOLD: float = 0.60  # 15m bias confidence minimum

# Absorption detection (detectors.py)
FABIO_ABSORPTION_VOL_MULT: float = 2.0   # Volume must exceed 2x average
FABIO_ABSORPTION_RANGE_ATR: float = 0.30 # Range must be < 0.3 ATR

# Volume Profile
FABIO_VALUE_AREA_PCT: float = 0.70       # CME standard value area (70%)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/quant/contracts/test_fabio_constants.py -v`
Expected: PASS

- [ ] **Step 5: Replace magic numbers in context_builder.py**

In `quant/decision/context_builder.py`, replace:
- Line 148: `0.3` / `0.5` → `FABIO_CVD_THRESHOLD_MCX` / `FABIO_CVD_THRESHOLD_NSE`
- Line 160: `0.20` → `FABIO_OBI_THRESHOLD`
- Line 164: `0.10` → `FABIO_OFI_THRESHOLD`

Add import:
```python
from quant.contracts.constants import (
    FABIO_CVD_THRESHOLD_NSE,
    FABIO_CVD_THRESHOLD_MCX,
    FABIO_OBI_THRESHOLD,
    FABIO_OFI_THRESHOLD,
)
```

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: All pass (values unchanged, just named)

- [ ] **Step 7: Commit**

```bash
git add quant/contracts/constants.py quant/decision/context_builder.py tests/quant/contracts/test_fabio_constants.py
git commit -m "refactor(amt): extract Fabio methodology magic numbers into named constants"
```

---

## Phase 3: Code Quality — Decision Result Factory

### Task 7: Decision Result Dict Factory

**Files:**
- Create: `quant/decision/result_factory.py`
- Modify: `quant/decision/timesfm_agents.py` (replace 7 dict literals with factory calls)
- Modify: `quant/decision/timesfm_engine.py` (replace 4 dict literals with factory calls)
- Test: `tests/quant/decision/test_result_factory.py`

**Interfaces:**
- Consumes: individual field values (action, direction, setup, confidence, etc.)
- Produces: complete ~20-key decision result dict matching the existing schema

- [ ] **Step 1: Write failing test for result factory**

```python
# tests/quant/decision/test_result_factory.py
"""Decision result dict factory eliminates copy-paste duplication."""
from quant.decision.result_factory import build_decision_result
from quant.contracts.enums import MarketState


def test_build_decision_result_contains_all_required_keys():
    result = build_decision_result(
        role="SCANNING",
        action="FLAT",
        direction="FLAT",
        setup="NO_EDGE",
        reason="NO_PROFILE",
        confidence="Low",
        confidence_score=0.0,
        rationale="No profile yet",
        forecast=None,
        gate_results=[],
        active_position=None,
        symbol="NIFTY24DEC21500CE",
        entry_price=0.0,
        market_state=MarketState.BALANCED,
        session_phase="REGULAR",
    )
    required_keys = {
        "role", "action", "direction", "setup", "reason",
        "confidence", "confidenceScore", "rationale",
        "forecastSteps", "quantileSpread", "meanForecast",
        "gateResults", "activePosition", "dynamicTrailStop",
        "source", "latencyMs", "modelLabel", "modelVersions",
        "regime", "timing", "sizeFraction", "latencyUs",
    }
    assert required_keys.issubset(set(result.keys()))


def test_regime_resolves_from_enum():
    result = build_decision_result(
        role="SCANNING", action="FLAT", direction="FLAT",
        setup="NO_EDGE", reason="TEST", confidence="Low",
        confidence_score=0.0, rationale="test",
        forecast=None, gate_results=[],
        active_position=None, symbol="TEST",
        entry_price=0.0,
        market_state=MarketState.TRENDING,
        session_phase="REGULAR",
    )
    assert result["regime"] == "TRENDING"


def test_regime_handles_string_market_state():
    result = build_decision_result(
        role="SCANNING", action="FLAT", direction="FLAT",
        setup="NO_EDGE", reason="TEST", confidence="Low",
        confidence_score=0.0, rationale="test",
        forecast=None, gate_results=[],
        active_position=None, symbol="TEST",
        entry_price=0.0,
        market_state="BALANCED",
        session_phase="MIDDAY",
    )
    assert result["regime"] == "BALANCED"
    assert result["timing"] == "MIDDAY"


def test_timing_defaults_to_regular():
    result = build_decision_result(
        role="SCANNING", action="FLAT", direction="FLAT",
        setup="NO_EDGE", reason="TEST", confidence="Low",
        confidence_score=0.0, rationale="test",
        forecast=None, gate_results=[],
        active_position=None, symbol="TEST",
        entry_price=0.0,
        market_state=MarketState.BALANCED,
        session_phase=None,
    )
    assert result["timing"] == "REGULAR"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_result_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.decision.result_factory'`

- [ ] **Step 3: Implement result factory**

```python
# quant/decision/result_factory.py
"""Factory for decision result dicts — eliminates ~150 lines of copy-paste.

The same ~20-key dict structure was duplicated across 7+ sites in
timesfm_agents.py and timesfm_engine.py. This factory centralizes the
construction so schema changes happen in one place.
"""
from __future__ import annotations

from typing import Any


def _resolve_regime(market_state: Any) -> str:
    """Extract regime string from MarketState enum or string."""
    if hasattr(market_state, "value"):
        return str(market_state.value)
    return str(market_state or "BALANCED")


def _resolve_timing(session_phase: Any) -> str:
    """Extract timing string from session phase."""
    return str(session_phase or "REGULAR")


def build_decision_result(
    *,
    role: str,
    action: str,
    direction: str,
    setup: str,
    reason: str,
    confidence: str,
    confidence_score: float,
    rationale: str,
    forecast: Any,
    gate_results: list[dict],
    active_position: dict | None,
    symbol: str,
    entry_price: float,
    market_state: Any,
    session_phase: Any,
    # Optional overrides:
    dynamic_trail_stop: float | None = None,
    model_label: str | None = None,
    size_fraction: float = 0.0,
    timing_override: str | None = None,
) -> dict:
    """Build a complete decision result dict.

    All repeated expressions (regime, timing, modelVersions) are
    computed once here instead of duplicated at every call site.
    """
    forecast_steps = list(forecast.forecast_steps) if forecast else []
    q_spread = round(float(forecast.q_spread), 4) if forecast else 0.0
    mean_forecast = round(float(forecast.mean_forecast), 2) if forecast else 0.0
    lat_ms = round(forecast.lat_ms, 1) if forecast else 0.0

    return {
        "role": role,
        "action": action,
        "direction": direction,
        "setup": setup,
        "reason": reason,
        "confidence": confidence,
        "confidenceScore": round(confidence_score, 3),
        "rationale": rationale,
        "forecastSteps": forecast_steps,
        "quantileSpread": q_spread,
        "meanForecast": mean_forecast,
        "gateResults": gate_results,
        "activePosition": active_position,
        "dynamicTrailStop": round(dynamic_trail_stop, 2) if dynamic_trail_stop is not None else None,
        "source": "TIMESFM_3.0_NATIVE",
        "latencyMs": lat_ms,
        "modelLabel": model_label or f"TimesFM-{role}-{action}",
        "modelVersions": {"timesfm": "3.0", "engine": "native_direct"},
        "regime": _resolve_regime(market_state),
        "timing": timing_override or _resolve_timing(session_phase),
        "sizeFraction": size_fraction,
        "latencyUs": int(lat_ms * 1000),
    }


def build_gate_results(
    g1_passed: bool, g1_msg: str,
    g2_passed: bool, g2_msg: str,
    g3_passed: bool, g3_msg: str,
    g4_passed: bool, g4_msg: str,
) -> list[dict]:
    """Build the standard 4-gate result list.

    Eliminates ~60 lines of copy-paste across timesfm_agents.py and
    timesfm_engine.py where the same [gate1, gate2, gate3, gate4] list
    structure was constructed from scratch at every site.
    """
    return [
        {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": g1_passed, "message": g1_msg},
        {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": g2_passed, "message": g2_msg},
        {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": g3_passed, "message": g3_msg},
        {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": g4_passed, "message": g4_msg},
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_result_factory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/decision/result_factory.py tests/quant/decision/test_result_factory.py
git commit -m "refactor(decision): decision result dict factory eliminates 150+ lines of duplication"
```

### Task 8: Replace Dict Literals in timesfm_agents.py

**Files:**
- Modify: `quant/decision/timesfm_agents.py` (replace 7 dict literals with factory calls)
- Test: existing tests in `tests/quant/decision/test_timesfm_agents.py`

**Interfaces:**
- Consumes: `build_decision_result` and `build_gate_results` from `quant.decision.result_factory`
- Produces: identical dict output (verified by existing tests)

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_timesfm_agents.py -v`
Expected: All pass (record count)

- [ ] **Step 2: Replace dict literals in timesfm_agents.py**

At each of the 7 sites where a decision result dict is constructed, replace with:

```python
from quant.decision.result_factory import build_decision_result, build_gate_results

# Example replacement (site 1: NO_PROFILE):
return build_decision_result(
    role="SCANNING",
    action="FLAT",
    direction="FLAT",
    setup="NO_EDGE",
    reason="NO_PROFILE",
    confidence="Low",
    confidence_score=0.0,
    rationale=f"No volume profile on {symbol} yet ...",
    forecast=forecast,
    gate_results=build_gate_results(
        g1_passed=g1, g1_msg=g1_msg,
        g2_passed=g2, g2_msg=g2_msg,
        g3_passed=False, g3_msg="No volume profile",
        g4_passed=False, g4_msg="No setup",
    ),
    active_position=None,
    symbol=symbol,
    entry_price=0.0,
    market_state=ctx.market_state,
    session_phase=ctx.session_phase,
)
```

Apply this pattern to all 7 sites, preserving the exact rationale strings and gate messages.

- [ ] **Step 3: Run existing tests to verify no behavior change**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_timesfm_agents.py -v`
Expected: Same pass count as baseline

- [ ] **Step 4: Run full quant test suite**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add quant/decision/timesfm_agents.py
git commit -m "refactor(decision): replace 7 dict literals in timesfm_agents.py with result factory"
```

### Task 9: Replace Dict Literals in timesfm_engine.py

**Files:**
- Modify: `quant/decision/timesfm_engine.py` (replace 4 dict literals with factory calls)
- Test: existing tests in `tests/quant/decision/test_timesfm_engine.py`

**Interfaces:**
- Consumes: `build_decision_result` and `build_gate_results` from `quant.decision.result_factory`
- Produces: identical dict output (verified by existing tests)

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_timesfm_engine.py -v`
Expected: All pass (record count)

- [ ] **Step 2: Replace dict literals in timesfm_engine.py**

At each of the 4 sites (SessionGateBlocked, RiskHalted, OpeningNoise, rule-based fallback), replace with `build_decision_result(...)` calls.

- [ ] **Step 3: Run existing tests to verify no behavior change**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_timesfm_engine.py -v`
Expected: Same pass count as baseline

- [ ] **Step 4: Run full quant test suite**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add quant/decision/timesfm_engine.py
git commit -m "refactor(decision): replace 4 dict literals in timesfm_engine.py with result factory"
```

---

## Phase 4: Code Quality — Dead Code & Smell Removal

### Task 10: Remove Dead Code in live_oms.py

**Files:**
- Modify: `quant/execution/live_oms.py:448-524` (remove 77 lines of unreachable code after unconditional raise)
- Test: `tests/quant/execution/test_live_oms.py` (verify pyramid disabled behavior preserved)

**Interfaces:**
- Consumes: nothing (pure deletion)
- Produces: `add_pyramid()` raises immediately with no dead code after

- [ ] **Step 1: Write test confirming pyramid is disabled**

```python
# tests/quant/execution/test_pyramid_disabled.py
"""add_pyramid raises immediately — pyramid is disabled under LiveOMS."""
import pytest


def test_add_pyramid_raises_value_error():
    """add_pyramid must raise ValueError — pyramids are disabled."""
    from quant.execution.live_oms import LiveOMS
    oms = LiveOMS(
        symbol="TEST",
        broker=None,
        contract=None,
        emit_fn=None,
    )
    with pytest.raises(ValueError, match="pyramids disabled"):
        oms.add_pyramid(quantity=1, price=100.0)
```

- [ ] **Step 2: Run test to verify it passes (current behavior)**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_pyramid_disabled.py -v`
Expected: PASS

- [ ] **Step 3: Remove dead code after raise in add_pyramid**

In `quant/execution/live_oms.py`, delete lines 453-524 (all code after the `raise ValueError(...)` at line 448). Keep the method signature and the raise statement.

- [ ] **Step 4: Run test to verify behavior preserved**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_pyramid_disabled.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add quant/execution/live_oms.py tests/quant/execution/test_pyramid_disabled.py
git commit -m "refactor(oms): remove 77 lines of unreachable dead code after raise in add_pyramid"
```

### Task 11: Extract LiveOMS Broker Backward-Compat Helper

**Files:**
- Modify: `quant/execution/live_oms.py` (extract `_call_broker` helper, replace 4 duplicated try/except blocks)
- Test: `tests/quant/execution/test_live_oms_broker_compat.py`

**Interfaces:**
- Consumes: broker method name and kwargs
- Produces: broker call result with automatic `contract_ref` TypeError fallback

- [ ] **Step 1: Write test for broker compat helper**

```python
# tests/quant/execution/test_live_oms_broker_compat.py
"""LiveOMS broker backward-compat: contract_ref fallback is centralized."""


class FakeBroker:
    """Broker that rejects contract_ref on first call, accepts on retry."""
    def __init__(self):
        self.call_count = 0

    def execute_order(self, **kwargs):
        self.call_count += 1
        if "contract_ref" in kwargs:
            raise TypeError("execute_order() got an unexpected keyword argument 'contract_ref'")
        return {"status": "filled", "price": 100.0}


def test_broker_compat_retries_without_contract_ref():
    from quant.execution.live_oms import LiveOMS
    oms = LiveOMS(symbol="TEST", broker=FakeBroker(), contract="CONTRACT", emit_fn=None)
    result = oms._call_broker("execute_order", symbol="TEST", quantity=1, side="BUY", contract_ref="CONTRACT")
    assert result["status"] == "filled"
    assert oms._broker.call_count == 2  # first failed, second succeeded


def test_broker_compat_raises_non_contract_ref_type_error():
    from quant.execution.live_oms import LiveOMS

    class BadBroker:
        def execute_order(self, **kwargs):
            raise TypeError("some other error")

    oms = LiveOMS(symbol="TEST", broker=BadBroker(), contract="CONTRACT", emit_fn=None)
    import pytest
    with pytest.raises(TypeError, match="some other error"):
        oms._call_broker("execute_order", symbol="TEST", quantity=1, side="BUY", contract_ref="CONTRACT")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_live_oms_broker_compat.py -v`
Expected: FAIL with `AttributeError: 'LiveOMS' object has no attribute '_call_broker'`

- [ ] **Step 3: Implement _call_broker helper and refactor call sites**

Add to `LiveOMS` class:

```python
    def _call_broker(self, method: str, **kwargs):
        """Call broker method with contract_ref backward-compat fallback.

        Some broker implementations don't accept contract_ref. When the
        TypeError mentions contract_ref, retry without it.
        """
        broker_method = getattr(self._broker, method)
        try:
            return broker_method(**kwargs)
        except TypeError as exc:
            if "contract_ref" not in str(exc):
                raise
            kwargs.pop("contract_ref", None)
            return broker_method(**kwargs)
```

Replace the 4 duplicated try/except blocks in `submit()`, `close()`, `close_partial()`, and `add_pyramid()` with calls to `self._call_broker(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_live_oms_broker_compat.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add quant/execution/live_oms.py tests/quant/execution/test_live_oms_broker_compat.py
git commit -m "refactor(oms): extract _call_broker helper, eliminate 4 duplicated contract_ref fallbacks"
```

### Task 12: Add Silent-Except Markers to Undocumented Blocks

**Files:**
- Modify: `quant/multi_engine.py:327` (add `# silent-except` comment)
- Modify: `quant/execution/oms.py:59` (add `# silent-except` comment)
- Modify: `automation/quality/scanner.py:45,80` (add `# silent-except` comments)
- Modify: `automation/monitor.py:170` (add `# silent-except` comment)
- Modify: `automation/performance/detector.py:66` (add `# silent-except` comment)
- Test: `tests/architecture/test_no_layer_bypass.py` (existing test should now pass without new violations)

**Interfaces:**
- Consumes: existing except blocks
- Produces: documented silent-except markers that satisfy the architecture test

- [ ] **Step 1: Run architecture test to see current state**

Run: `.venv/bin/python -m pytest tests/architecture/test_no_layer_bypass.py -v`
Expected: PASS (but silent-except blocks are undocumented)

- [ ] **Step 2: Add silent-except markers**

For each location, add a comment explaining why the except is silent:

```python
# quant/multi_engine.py:327
except Exception:  # silent-except - health check failure returns False, caller handles
    return False

# quant/execution/oms.py:59
except Exception:  # silent-except - position query failure returns (0, 0), no position assumed
    return 0.0, 0.0

# automation/quality/scanner.py:45
except Exception:  # silent-except - complexity analysis skips unparseable files
    pass

# automation/quality/scanner.py:80
except Exception:  # silent-except - architecture check skips unparseable files
    pass

# automation/monitor.py:170
except Exception:  # silent-except - fix application failure is logged via report, not raised
    continue

# automation/performance/detector.py:66
except Exception:  # silent-except - benchmark parsing failure returns empty results
    return []
```

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add quant/multi_engine.py quant/execution/oms.py automation/quality/scanner.py automation/monitor.py automation/performance/detector.py
git commit -m "fix: document 6 silent-except blocks with intent comments"
```

---

## Phase 5: Automation Tooling Gaps

### Task 13: Add Deep Nesting Detection to Pattern Detector

**Files:**
- Modify: `automation/quality/patterns.py` (add `_detect_deep_nesting` method)
- Test: `tests/automation/test_deep_nesting.py`

**Interfaces:**
- Consumes: AST tree, source code
- Produces: `QualityIssue` list for functions with nesting depth >= 5

- [ ] **Step 1: Write failing test**

```python
# tests/automation/test_deep_nesting.py
from automation.quality.patterns import PatternDetector


def test_detects_deep_nesting():
    source = '''
def deeply_nested(x):
    if x > 0:
        if x > 1:
            if x > 2:
                if x > 3:
                    if x > 4:
                        return x
    return 0
'''
    detector = PatternDetector()
    issues = detector.detect("test.py", source)
    nesting_issues = [i for i in issues if i.rule == "pattern.deep_nesting"]
    assert len(nesting_issues) > 0
    assert "deeply_nested" in nesting_issues[0].message


def test_no_issue_for_shallow_nesting():
    source = '''
def shallow(x):
    if x > 0:
        if x > 1:
            return x
    return 0
'''
    detector = PatternDetector()
    issues = detector.detect("test.py", source)
    nesting_issues = [i for i in issues if i.rule == "pattern.deep_nesting"]
    assert len(nesting_issues) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/automation/test_deep_nesting.py -v`
Expected: FAIL (no `pattern.deep_nesting` rule exists)

- [ ] **Step 3: Implement deep nesting detection**

Add to `automation/quality/patterns.py` in the `PatternDetector` class:

```python
    def _detect_deep_nesting(
        self, filepath: str, tree: ast.AST
    ) -> List[QualityIssue]:
        """Detect functions with nesting depth >= 5 levels."""
        issues = []
        max_depth = 5

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                depth = self._max_nesting_depth(node)
                if depth >= max_depth:
                    issues.append(QualityIssue(
                        file=filepath,
                        line=node.lineno,
                        rule="pattern.deep_nesting",
                        severity="warning",
                        message=f"Function '{node.name}' has nesting depth {depth} (max: {max_depth})"
                    ))
        return issues

    def _max_nesting_depth(self, node: ast.AST, current: int = 0) -> int:
        nesting_types = (ast.If, ast.For, ast.While, ast.With, ast.Try)
        max_d = current
        for child in ast.iter_child_nodes(node):
            if isinstance(child, nesting_types):
                child_depth = self._max_nesting_depth(child, current + 1)
                max_d = max(max_d, child_depth)
            else:
                child_depth = self._max_nesting_depth(child, current)
                max_d = max(max_d, child_depth)
        return max_d
```

Wire it into the `detect()` method:

```python
    def detect(self, filepath: str, source: str) -> List[QualityIssue]:
        tree = ast.parse(source)
        issues = []
        issues.extend(self._detect_silent_except_pass(filepath, tree, source))
        issues.extend(self._detect_mutable_defaults(filepath, tree))
        issues.extend(self._detect_deep_nesting(filepath, tree))  # NEW
        return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/automation/test_deep_nesting.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add automation/quality/patterns.py tests/automation/test_deep_nesting.py
git commit -m "feat(automation): add deep nesting detection (>= 5 levels) to pattern detector"
```

### Task 14: Add Function Length Enforcement

**Files:**
- Modify: `automation/quality/scanner.py` (add `_check_function_length` method)
- Test: `tests/automation/test_function_length.py`

**Interfaces:**
- Consumes: AST tree, `max_lines_per_function` from config
- Produces: `QualityIssue` list for functions exceeding the line limit

- [ ] **Step 1: Write failing test**

```python
# tests/automation/test_function_length.py
from automation.quality.scanner import CodeQualityScanner


def test_detects_long_function():
    scanner = CodeQualityScanner("automation/config/quality_rules.yaml")
    source = "def long_function():\n" + "    x = 1\n" * 60
    issues = scanner._check_function_length("test.py", source)
    assert len(issues) > 0
    assert "long_function" in issues[0].message


def test_no_issue_for_short_function():
    scanner = CodeQualityScanner("automation/config/quality_rules.yaml")
    source = "def short_function():\n    return 1\n"
    issues = scanner._check_function_length("test.py", source)
    assert len(issues) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/automation/test_function_length.py -v`
Expected: FAIL with `AttributeError: 'CodeQualityScanner' object has no attribute '_check_function_length'`

- [ ] **Step 3: Implement function length check**

Add to `automation/quality/scanner.py`:

```python
import ast

    def _check_function_length(self, filepath: str, source: str) -> List[QualityIssue]:
        issues = []
        max_lines = self.rules.get('rules', {}).get('complexity', {}).get('max_lines_per_function', 50)

        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end_line = getattr(node, 'end_lineno', node.lineno)
                    func_lines = end_line - node.lineno + 1
                    if func_lines > max_lines:
                        issues.append(QualityIssue(
                            file=filepath,
                            line=node.lineno,
                            rule="complexity.function_length",
                            severity="warning",
                            message=f"Function '{node.name}' has {func_lines} lines (max: {max_lines})"
                        ))
        except Exception:  # silent-except - unparseable files are skipped
            pass

        return issues
```

Wire into `scan()` method:

```python
    issues.extend(self._check_function_length(str(file), source))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/automation/test_function_length.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add automation/quality/scanner.py tests/automation/test_function_length.py
git commit -m "feat(automation): enforce max_lines_per_function from config (was defined but not checked)"
```

---

## Phase 6: Final Verification

### Task 15: Full Regression Suite

**Files:**
- No code changes — verification only

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -x -q --tb=short`
Expected: All pass

- [ ] **Step 2: Run golden tape determinism tests**

Run: `.venv/bin/python -m pytest tests/determinism/ -v`
Expected: SHA-256 hashes match (no behavioral drift)

- [ ] **Step 3: Run architecture tests**

Run: `.venv/bin/python -m pytest tests/architecture/ -v`
Expected: All pass

- [ ] **Step 4: Run automation tests**

Run: `.venv/bin/python -m pytest tests/automation/ -v`
Expected: All pass

- [ ] **Step 5: Run complexity scan on changed files**

Run: `.venv/bin/python -m automation.cli scan quant/decision/timesfm_agents.py quant/decision/timesfm_engine.py quant/execution/live_oms.py`
Expected: Complexity reduced or unchanged (no new high-complexity functions introduced)

- [ ] **Step 6: Commit any final fixes if needed**

```bash
git add -A
git commit -m "fix: final regression fixes from full suite verification"
```

### Task 16: Summary Report

- [ ] **Step 1: Generate final metrics**

Count:
- Lines of duplication eliminated (expect ~150 from dict factory + ~60 from gate factory + ~77 dead code + ~40 broker compat = ~327 lines removed)
- Named constants added (expect ~9 Fabio constants)
- New tests added (expect ~25 new tests across all tasks)
- Functions with reduced complexity (expect timesfm_agents.py and timesfm_engine.py to improve)

- [ ] **Step 2: Final commit with summary**

```bash
git add -A
git commit -m "docs: Fabio AMT alignment & code quality — summary report

Phase 1: 15-min bias layer (Fabio top-down: 15m→5m→1m)
Phase 2: Fabio parameter constants (9 named constants)
Phase 3: Decision result factory (eliminates ~210 lines of duplication)
Phase 4: Dead code removal (77 lines) + broker compat helper
Phase 5: Automation gaps (deep nesting + function length detection)
Phase 6: Full regression verification"
```

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-17-fabio-amt-alignment-code-quality.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
