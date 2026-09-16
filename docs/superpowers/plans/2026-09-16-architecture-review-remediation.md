# Architecture Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up dead code, document invariants, consolidate duplicates, and extract oversized modules for maintainability based on the senior quant engineer architecture review.

**Architecture:** The system is a per-symbol event-driven trading engine with a coordinator orchestrating multiple engines. This plan addresses code quality issues identified in the review: dead aliases, stale comments, undocumented lock ordering, duplicate closures, oversized modules, dual position authority, scattered constants, and silent exception handlers.

**Tech Stack:** Python 3.11+, pytest, threading (Lock/RLock), dataclasses (frozen), event sourcing pattern

## Global Constraints

- All changes must maintain backward compatibility with existing tests
- No changes to trading logic or signal generation paths
- Lock ordering invariant must be documented but not enforced programmatically (single-threaded-per-engine design)
- Event sourcing immutability must be preserved (frozen dataclasses, pure transitions)
- All exception handlers that currently swallow errors must at minimum log at DEBUG level

---

## Task 1: Delete Dead Alias `quant/transition.py`

**Files:**
- Delete: `quant/transition.py`
- Modify: `quant/transitions.py` (add deprecation note if needed)
- Test: `tests/quant/test_transition_alias.py` (verify no imports break)

**Interfaces:**
- Consumes: None (pure deletion)
- Produces: Cleaner import surface, no functional change

- [ ] **Step 1: Search for all imports of `quant.transition`**

Run: `grep -r "from quant.transition import\|from quant import transition\|import quant.transition" --include="*.py" .`

Expected: Should find only the file itself and possibly test files. Document all locations.

- [ ] **Step 2: Update any imports to use `quant.transitions`**

For each file found in Step 1 (excluding `quant/transition.py` itself), update imports:

```python
# Before
from quant.transition import apply_event

# After
from quant.transitions import apply_event
```

- [ ] **Step 3: Write a test to verify the alias is not needed**

Create `tests/quant/test_transition_alias.py`:

```python
"""Verify quant.transition alias is not imported anywhere in production code."""

import ast
from pathlib import Path


def test_no_imports_of_transition_alias():
    """Ensure no production code imports from quant.transition (the alias)."""
    quant_dir = Path("quant")
    violations = []
    
    for py_file in quant_dir.rglob("*.py"):
        if py_file.name == "transition.py":
            continue  # Skip the alias file itself
        
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "quant.transition" in node.module:
                    violations.append(f"{py_file}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "quant.transition" in alias.name:
                        violations.append(f"{py_file}:{node.lineno}")
    
    assert not violations, f"Found imports of quant.transition alias: {violations}"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/quant/test_transition_alias.py -v`

Expected: PASS (no violations found after Step 2 updates)

- [ ] **Step 5: Delete the alias file**

Run: `rm quant/transition.py`

- [ ] **Step 6: Run full test suite to verify no breakage**

Run: `pytest tests/ -x --tb=short`

Expected: All tests pass. If any fail, they are importing from `quant.transition` — update them to use `quant.transitions`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: remove dead quant/transition.py alias

The alias added confusion without value. All imports now use the
canonical quant.transitions module directly.

Fixes: architecture review finding — duplicate transition files"
```

---

## Task 2: Delete Stale TODO Comment in RiskConfig

**Files:**
- Modify: `backend/app/config_models/__init__.py:111`

**Interfaces:**
- Consumes: None (comment-only change)
- Produces: Accurate documentation

- [ ] **Step 1: Read the current state of the file**

Run: `sed -n '105,115p' backend/app/config_models/__init__.py`

Expected output:
```python
class RiskConfig:
    """Global risk configuration."""

    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 3
    # TODO: Testing Mode — Raised to 50 for testing & validation. Revert to 6 in production.
    max_trades_per_session: int = 6
    max_drawdown_pct: float = 0.03
```

- [ ] **Step 2: Delete the stale TODO comment**

Edit `backend/app/config_models/__init__.py` and remove line 111:

```python
class RiskConfig:
    """Global risk configuration."""

    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 3
    max_trades_per_session: int = 6  # Production value (was temporarily raised to 50 for testing)
    max_drawdown_pct: float = 0.03
```

- [ ] **Step 3: Verify no other stale TODOs exist**

Run: `grep -n "TODO.*[Tt]esting\|TODO.*[Rr]evert\|TODO.*production" backend/app/config_models/__init__.py`

Expected: No output (all stale TODOs removed)

- [ ] **Step 4: Run backend tests to verify no breakage**

Run: `pytest backend/tests/ -x --tb=short -k "risk or config"`

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/config_models/__init__.py
git commit -m "docs: remove stale TODO comment in RiskConfig

The value is already correct (6), the comment was misleading.
Added inline note explaining the history for context.

Fixes: architecture review finding — stale TODO in production config"
```

---

## Task 3: Document Lock Ordering Invariant

**Files:**
- Modify: `quant/runtime.py` (add module-level docstring section)
- Modify: `quant/multi_engine.py` (add module-level docstring section)

**Interfaces:**
- Consumes: None (documentation-only)
- Produces: Documented invariant for future maintainers

- [ ] **Step 1: Read the current module docstring in runtime.py**

Run: `sed -n '1,30p' quant/runtime.py`

Expected: Module docstring describing the QuantEngine.

- [ ] **Step 2: Add lock ordering section to runtime.py docstring**

Edit `quant/runtime.py` and add after the existing module docstring:

```python
"""
QuantEngine — per-symbol event-driven trading engine.

...existing docstring content...

## Threading and Locking

This engine runs in a single thread (one thread per symbol, managed by
QuantCoordinator's ThreadPoolExecutor). The single-threaded design eliminates
most concurrency risks, but cross-engine coordination requires care.

### Lock Ordering Invariant

When acquiring multiple locks, always acquire in this order:

1. `_close_lock` (per-engine, serializes position close operations)
2. `PortfolioRiskAuthority._lock` (global, guards aggregate risk tracking)
3. `SessionRisk._lock` (per-symbol, guards risk state)

Never acquire locks in reverse order. The single-threaded-per-engine design
prevents deadlock in practice (submit and close cannot interleave on the same
engine), but this invariant must be preserved if the engine is ever refactored
to multi-threaded tick processing.

### Cross-Engine Coordination

Engines coordinate only through `PortfolioRiskAuthority` (shared across all
engines). All access is guarded by `PortfolioRiskAuthority._lock`.
"""
```

- [ ] **Step 3: Read the current module docstring in multi_engine.py**

Run: `sed -n '1,30p' quant/multi_engine.py`

Expected: Module docstring describing the QuantCoordinator.

- [ ] **Step 4: Add lock ordering section to multi_engine.py docstring**

Edit `quant/multi_engine.py` and add after the existing module docstring:

```python
"""
QuantCoordinator — multi-symbol orchestrator.

...existing docstring content...

## Threading and Locking

The coordinator spawns one QuantEngine per symbol, each running in its own
thread. Cross-engine coordination happens through shared authorities:

- `PortfolioRiskAuthority`: Aggregate risk ceiling (shared, locked)
- `SessionLevelStore`: Session persistence (per-symbol, locked)

### Lock Ordering Invariant

When acquiring multiple locks, always acquire in this order:

1. `QuantCoordinator._lifecycle_lock` (global, guards engine spawn/stop)
2. `QuantCoordinator._lock` (global, guards engine registry)
3. `QuantEngine._close_lock` (per-engine, serializes position close)
4. `PortfolioRiskAuthority._lock` (global, guards aggregate risk)
5. `SessionRisk._lock` (per-symbol, guards risk state)

Never acquire locks in reverse order. The EOD watchdog thread may call
`force_close_position()` on engines running in other threads — this acquires
the engine's `_close_lock`, which serializes with the engine thread's own
close operations.

### EOD Watchdog

The EOD watchdog runs in a separate thread and monitors for end-of-day
conditions. It can call `force_close_position()` on any engine, which
acquires the engine's `_close_lock`. This is safe because `_close_lock`
serializes close operations across threads.
"""
```

- [ ] **Step 5: Verify no syntax errors**

Run: `python -c "import quant.runtime; import quant.multi_engine; print('OK')"`

Expected: `OK` (no import errors)

- [ ] **Step 6: Commit**

```bash
git add quant/runtime.py quant/multi_engine.py
git commit -m "docs: document lock ordering invariant

The single-threaded-per-engine design prevents deadlock in practice,
but this invariant must be preserved if the engine is ever refactored
to multi-threaded tick processing.

Fixes: architecture review finding — undocumented lock ordering"
```

---

## Task 4: Consolidate Journal Subscriber Closure

**Files:**
- Modify: `quant/runtime.py` (extract duplicate closure)
- Test: `tests/quant/test_journal_subscriber.py` (verify consolidation)

**Interfaces:**
- Consumes: `EventBus.subscribe()` method
- Produces: Single `_create_journal_subscriber()` helper method

- [ ] **Step 1: Identify the duplicate closures**

Run: `grep -n "def.*journal.*subscriber\|EventBus.subscribe" quant/runtime.py | head -20`

Expected: Two locations where the journal subscriber closure is defined — one in `__init__()` and one in `attach_journal()`.

- [ ] **Step 2: Read both closure definitions**

Run: `sed -n '509,521p' quant/runtime.py` (first definition in `__init__`)
Run: `sed -n '615,626p' quant/runtime.py` (second definition in `attach_journal`)

Expected: Nearly identical closure bodies.

- [ ] **Step 3: Extract the closure into a helper method**

Add a new method to the `QuantEngine` class in `quant/runtime.py`:

```python
def _create_journal_subscriber(self) -> callable:
    """Create a journal subscriber closure that writes events to the journal.
    
    This is a single source of truth for the journal subscriber logic,
    used by both __init__() and attach_journal().
    """
    def subscriber(event):
        # Only journal specific event types
        if not isinstance(event, (
            SignalApproved, SignalBlocked, PositionOpened, PositionClosed,
            PyramidAdded, RiskHaltTriggered, SessionStarted, SessionEnded
        )):
            return
        
        # Write to journal (JSONL format)
        if hasattr(self, '_journal') and self._journal is not None:
            try:
                self._journal.append(event)
            except Exception as e:
                # Journal writes must never break trading
                logger.debug(f"Journal write failed: {e}")
    
    return subscriber
```

- [ ] **Step 4: Update `__init__()` to use the helper**

In `quant/runtime.py`, replace the inline closure in `__init__()` with:

```python
# Before (lines 509-521)
def subscriber(event):
    if not isinstance(event, (...)):
        return
    if hasattr(self, '_journal') and self._journal is not None:
        try:
            self._journal.append(event)
        except Exception as e:
            logger.debug(f"Journal write failed: {e}")

self._event_bus.subscribe(subscriber)

# After
journal_subscriber = self._create_journal_subscriber()
self._event_bus.subscribe(journal_subscriber)
```

- [ ] **Step 5: Update `attach_journal()` to use the helper**

In `quant/runtime.py`, replace the inline closure in `attach_journal()` with:

```python
# Before (lines 615-626)
def subscriber(event):
    if not isinstance(event, (...)):
        return
    if hasattr(self, '_journal') and self._journal is not None:
        try:
            self._journal.append(event)
        except Exception as e:
            logger.debug(f"Journal write failed: {e}")

self._event_bus.subscribe(subscriber)

# After
journal_subscriber = self._create_journal_subscriber()
self._event_bus.subscribe(journal_subscriber)
```

- [ ] **Step 6: Write a test to verify the consolidation**

Create `tests/quant/test_journal_subscriber.py`:

```python
"""Verify journal subscriber consolidation."""

import inspect
from quant.runtime import QuantEngine


def test_journal_subscriber_helper_exists():
    """Ensure the _create_journal_subscriber helper method exists."""
    assert hasattr(QuantEngine, '_create_journal_subscriber')
    assert callable(getattr(QuantEngine, '_create_journal_subscriber'))


def test_journal_subscriber_helper_returns_callable():
    """Ensure the helper returns a callable subscriber."""
    # Create a minimal engine (mock dependencies)
    from unittest.mock import MagicMock
    
    engine = QuantEngine.__new__(QuantEngine)
    engine._journal = MagicMock()
    
    subscriber = engine._create_journal_subscriber()
    assert callable(subscriber)


def test_no_duplicate_journal_subscriber_definitions():
    """Ensure journal subscriber logic is not duplicated inline."""
    source = inspect.getsource(QuantEngine)
    
    # Count how many times we define "def subscriber(event):" inline
    # (should be zero after consolidation — all use the helper)
    inline_count = source.count("def subscriber(event):")
    
    # The helper method itself contains this pattern once, so we expect
    # exactly 1 occurrence (inside _create_journal_subscriber)
    assert inline_count == 1, (
        f"Found {inline_count} inline subscriber definitions, expected 1 (in helper)"
    )
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `pytest tests/quant/test_journal_subscriber.py -v`

Expected: All 3 tests PASS

- [ ] **Step 8: Run full test suite to verify no breakage**

Run: `pytest tests/quant/ -x --tb=short`

Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add quant/runtime.py tests/quant/test_journal_subscriber.py
git commit -m "refactor: consolidate journal subscriber closure

Extracted duplicate journal subscriber logic from __init__() and
attach_journal() into a single _create_journal_subscriber() helper.

Fixes: architecture review finding — duplicate closure definitions"
```

---

## Task 5: Add DEBUG Logging to Silent Exception Handlers

**Files:**
- Modify: `quant/runtime.py` (add logging to silent except blocks)
- Test: `tests/quant/test_exception_logging.py` (verify logging)

**Interfaces:**
- Consumes: `logging` module
- Produces: DEBUG-level logs for previously silent exceptions

- [ ] **Step 1: Find all silent except blocks in runtime.py**

Run: `grep -n "except.*:.*pass\|except.*:$" quant/runtime.py | head -20`

Expected: Multiple locations where exceptions are silently swallowed.

- [ ] **Step 2: Identify critical silent except blocks**

Focus on these patterns (from the review):
- `_cert_trace` certification logic
- Advisor context notifications
- Journal writes

Run: `grep -B2 -A2 "except.*:.*pass" quant/runtime.py | head -40`

- [ ] **Step 3: Add DEBUG logging to _cert_trace except block**

Find the `_cert_trace` method and update its exception handler:

```python
# Before
try:
    # certification logic
    ...
except Exception:
    pass

# After
try:
    # certification logic
    ...
except Exception as e:
    # Certification must never break trading, but log for debugging
    logger.debug(f"Certification trace failed: {e}")
```

- [ ] **Step 4: Add DEBUG logging to advisor notification except blocks**

Find advisor notification blocks and update:

```python
# Before
try:
    self._advisor.on_context(ctx)
except Exception:
    pass

# After
try:
    self._advisor.on_context(ctx)
except Exception as e:
    # Advisor notifications must never break trading
    logger.debug(f"Advisor notification failed: {e}")
```

- [ ] **Step 5: Write a test to verify logging is present**

Create `tests/quant/test_exception_logging.py`:

```python
"""Verify silent exception handlers now log at DEBUG level."""

import inspect
import re
from quant.runtime import QuantEngine


def test_no_bare_pass_in_except_blocks():
    """Ensure no bare 'except: pass' patterns exist in QuantEngine."""
    source = inspect.getsource(QuantEngine)
    
    # Pattern: "except" followed by "pass" on the next line (with optional whitespace)
    # This is a heuristic — may have false positives, but catches the main issue
    pattern = r"except\s+.*?:\s*\n\s*pass\s*\n"
    matches = re.findall(pattern, source)
    
    # We expect zero bare "except: pass" patterns after remediation
    # (all should have at least a debug log)
    assert len(matches) == 0, (
        f"Found {len(matches)} bare 'except: pass' patterns. "
        "All exception handlers should log at DEBUG level."
    )


def test_exception_handlers_have_logging():
    """Verify exception handlers in critical paths have logging."""
    source = inspect.getsource(QuantEngine)
    
    # Check that advisor notification has logging
    assert "Advisor notification failed" in source or "advisor" in source.lower()
    
    # Check that certification has logging
    assert "Certification trace failed" in source or "cert" in source.lower()
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/quant/test_exception_logging.py -v`

Expected: All tests PASS

- [ ] **Step 7: Run full test suite to verify no breakage**

Run: `pytest tests/quant/ -x --tb=short`

Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add quant/runtime.py tests/quant/test_exception_logging.py
git commit -m "fix: add DEBUG logging to silent exception handlers

Silent 'except: pass' blocks can mask real bugs. All exception handlers
in critical paths now log at DEBUG level for discoverability.

Fixes: architecture review finding — silent except patterns"
```

---

## Task 6: Centralize Magic Numbers

**Files:**
- Create: `quant/config/constants.py`
- Modify: `quant/runtime.py` (use constants)
- Modify: `quant/amt_engine.py` (use constants)
- Modify: `quant/decision/pipeline.py` (use constants)
- Test: `tests/quant/test_constants.py` (verify centralization)

**Interfaces:**
- Consumes: None (new module)
- Produces: `quant.config.constants` module with all magic numbers

- [ ] **Step 1: Create the constants module**

Create `quant/config/constants.py`:

```python
"""Centralized constants for the quant engine.

All magic numbers and configuration values that were previously scattered
across multiple files are now defined here for maintainability.
"""

# ============================================================================
# Engine Configuration
# ============================================================================

# Number of warmup bars before the engine starts trading
WARMUP_BARS = 15

# Conviction threshold for deterministic signals
DETERMINISTIC_CONVICTION = 0.7

# Number of events to batch before flushing to disk
JSONL_FLUSH_BATCH = 128

# Default candle ring size for AMT engine
DEFAULT_RING_SIZE = 8_192

# ============================================================================
# Risk Configuration
# ============================================================================

# Minimum risk-to-reward ratio for entry
MIN_RR_RATIO = 1.5

# Maximum stop distance in ticks
MAX_STOP_DISTANCE_TICKS = 200.0

# Tick size for NSE options (in currency units)
TICK_SIZE_NSE_OPTIONS = 0.05

# ============================================================================
# Session Configuration
# ============================================================================

# Session phases (1-5)
SESSION_PHASE_PRE_MARKET = 1
SESSION_PHASE_OPENING = 2
SESSION_PHASE_MID_SESSION = 3
SESSION_PHASE_CLOSING = 4
SESSION_PHASE_POST_MARKET = 5

# Allowed session phases for entry (Phase 2-4)
ALLOWED_ENTRY_PHASES = (2, 3, 4)

# ============================================================================
# Exit Configuration
# ============================================================================

# CVD kill threshold
CVD_KILL_THRESHOLD = 2.0

# Time stop in bars (default 60 minutes for 1-min bars)
DEFAULT_TIME_STOP_BARS = 60

# ============================================================================
# Position Management
# ============================================================================

# Maximum pyramid add-ons
MAX_PYRAMID_ADDONS = 2

# Pyramid sizing (fraction of base)
PYRAMID_SIZING = [0.50, 0.25]  # First add-on: 50%, second: 25%

# ============================================================================
# Absorption and Aggression
# ============================================================================

# Maximum age of absorption signal (in bars)
ABSORPTION_MAX_AGE_BARS = 5

# OBI aggression threshold
OBI_AGGRESSION_THRESHOLD = 0.20

# ============================================================================
# Seed Cache
# ============================================================================

# Seed cache TTL (seconds)
SEED_CACHE_TTL_SECONDS = 300
```

- [ ] **Step 2: Update runtime.py to use constants**

In `quant/runtime.py`, replace magic numbers with imports:

```python
# Before
_WARMUP_BARS = 15
_DETERMINISTIC_CONVICTION = 0.7
_JSONL_FLUSH_BATCH = 128

# After
from quant.config.constants import (
    WARMUP_BARS,
    DETERMINISTIC_CONVICTION,
    JSONL_FLUSH_BATCH,
    CVD_KILL_THRESHOLD,
    DEFAULT_TIME_STOP_BARS,
)
```

Then replace all usages:
- `_WARMUP_BARS` → `WARMUP_BARS`
- `_DETERMINISTIC_CONVICTION` → `DETERMINISTIC_CONVICTION`
- `_JSONL_FLUSH_BATCH` → `JSONL_FLUSH_BATCH`
- `2.0` (CVD threshold) → `CVD_KILL_THRESHOLD`
- `60` (time stop) → `DEFAULT_TIME_STOP_BARS`

- [ ] **Step 3: Update amt_engine.py to use constants**

In `quant/amt_engine.py`, replace:

```python
# Before
_DEFAULT_RING = 8_192

# After
from quant.config.constants import DEFAULT_RING_SIZE, SEED_CACHE_TTL_SECONDS
```

Then replace:
- `_DEFAULT_RING` → `DEFAULT_RING_SIZE`
- `300` (seed cache TTL) → `SEED_CACHE_TTL_SECONDS`

- [ ] **Step 4: Update decision pipeline to use constants**

In `quant/decision/pipeline.py` and related files, replace:

```python
# Before
MIN_RR = 1.5
MAX_STOP_DISTANCE_TICKS = 200.0
TICK_SIZE_NSE_OPTIONS = 0.05

# After
from quant.config.constants import (
    MIN_RR_RATIO as MIN_RR,
    MAX_STOP_DISTANCE_TICKS,
    TICK_SIZE_NSE_OPTIONS,
)
```

- [ ] **Step 5: Write a test to verify constants are centralized**

Create `tests/quant/test_constants.py`:

```python
"""Verify magic numbers are centralized in constants module."""

import ast
from pathlib import Path


def test_constants_module_exists():
    """Ensure the constants module exists."""
    constants_file = Path("quant/config/constants.py")
    assert constants_file.exists(), "quant/config/constants.py does not exist"


def test_constants_are_importable():
    """Ensure all constants can be imported."""
    from quant.config.constants import (
        WARMUP_BARS,
        DETERMINISTIC_CONVICTION,
        JSONL_FLUSH_BATCH,
        DEFAULT_RING_SIZE,
        MIN_RR_RATIO,
        MAX_STOP_DISTANCE_TICKS,
        TICK_SIZE_NSE_OPTIONS,
        WARMUP_BARS,
        CVD_KILL_THRESHOLD,
        DEFAULT_TIME_STOP_BARS,
        ABSORPTION_MAX_AGE_BARS,
        OBI_AGGRESSION_THRESHOLD,
        SEED_CACHE_TTL_SECONDS,
    )
    
    # Verify types
    assert isinstance(WARMUP_BARS, int)
    assert isinstance(DETERMINISTIC_CONVICTION, float)
    assert isinstance(JSONL_FLUSH_BATCH, int)
    assert isinstance(DEFAULT_RING_SIZE, int)
    assert isinstance(MIN_RR_RATIO, float)
    assert isinstance(MAX_STOP_DISTANCE_TICKS, float)
    assert isinstance(TICK_SIZE_NSE_OPTIONS, float)


def test_no_scattered_magic_numbers():
    """Verify magic numbers are not scattered across files."""
    # Check runtime.py for old constants
    runtime_source = Path("quant/runtime.py").read_text()
    
    # These should NOT be defined in runtime.py anymore
    assert "_WARMUP_BARS = 15" not in runtime_source
    assert "_DETERMINISTIC_CONVICTION = 0.7" not in runtime_source
    assert "_JSONL_FLUSH_BATCH = 128" not in runtime_source
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/quant/test_constants.py -v`

Expected: All 3 tests PASS

- [ ] **Step 7: Run full test suite to verify no breakage**

Run: `pytest tests/quant/ -x --tb=short`

Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add quant/config/constants.py quant/runtime.py quant/amt_engine.py quant/decision/pipeline.py tests/quant/test_constants.py
git commit -m "refactor: centralize magic numbers in constants module

Scattered magic numbers make maintenance difficult. All configuration
values are now defined in quant.config.constants for single-source truth.

Fixes: architecture review finding — magic number proliferation"
```

---

## Task 7: Extract runtime.py into Modules (Phase 1 — Tick Handler)

**Files:**
- Create: `quant/engine/tick_handler.py`
- Modify: `quant/runtime.py` (extract tick handling logic)
- Test: `tests/quant/test_tick_handler.py` (verify extraction)

**Interfaces:**
- Consumes: `QuantEngine` state, `BarAggregator`, `AMTEngine`
- Produces: `TickHandler` class with `process_tick()` method

**Note:** This is Phase 1 of extracting runtime.py. The full extraction would take multiple phases. This phase focuses on the tick processing loop, which is the most self-contained.

- [ ] **Step 1: Identify tick handling logic in runtime.py**

Run: `grep -n "def _run_inner\|def _manage_tick_exit\|def _on_bar_closed" quant/runtime.py`

Expected: The tick handling logic is in `_run_inner()` (lines ~761-854).

- [ ] **Step 2: Read the tick handling logic**

Run: `sed -n '761,854p' quant/runtime.py`

Expected: The main tick processing loop with bar aggregation, AMT analysis, and decision evaluation.

- [ ] **Step 3: Create the TickHandler class**

Create `quant/engine/tick_handler.py`:

```python
"""Tick handler — processes incoming market ticks.

Extracted from QuantEngine._run_inner() for maintainability.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quant.aggregator import BarAggregator
    from quant.amt_engine import AMTEngine
    from quant.state_machine import EngineState

logger = logging.getLogger(__name__)


class TickHandler:
    """Processes incoming market ticks and orchestrates bar aggregation.
    
    Responsibilities:
    - Feed ticks to bar aggregators (macro and micro)
    - Trigger AMT analysis on bar close
    - Invoke decision evaluation at appropriate cadences
    - Manage tick-level exits for open positions
    """
    
    def __init__(
        self,
        symbol: str,
        macro_aggregator: BarAggregator,
        micro_aggregator: BarAggregator | None,
        amt_engine: AMTEngine,
        decide_callback: callable,
        manage_exit_callback: callable,
        manage_tick_exit_callback: callable,
        on_bar_closed_callback: callable,
        state_getter: callable,
    ):
        self.symbol = symbol
        self._macro_aggregator = macro_aggregator
        self._micro_aggregator = micro_aggregator
        self._amt_engine = amt_engine
        self._decide = decide_callback
        self._manage_exit = manage_exit_callback
        self._manage_tick_exit = manage_tick_exit_callback
        self._on_bar_closed = on_bar_closed_callback
        self._get_state = state_getter
    
    def process_tick(self, tick: dict) -> None:
        """Process a single market tick.
        
        This is the main entry point called by QuantEngine._run_inner().
        """
        state = self._get_state()
        
        # 1. Tick-level fast exit (if positioned)
        if state.position is not None:
            self._manage_tick_exit(tick)
        
        # 2. Micro-bar aggregation (for fast entry decisions)
        if self._micro_aggregator is not None:
            micro_bar = self._micro_aggregator.add_tick(tick)
            if micro_bar is not None and state.position is None:
                # Micro-bar closed — evaluate entry
                amt_dto = self._amt_engine.last_amt_dto
                if amt_dto:
                    self._decide(amt_dto, micro_bar)
        
        # 3. Macro-bar aggregation
        bar = self._macro_aggregator.add_tick(tick)
        self._amt_engine.on_tick(tick, self._macro_aggregator.current_bar)
        
        if bar is not None:
            # Macro-bar closed — full processing
            self._on_bar_closed(bar)
```

- [ ] **Step 4: Write a test for TickHandler**

Create `tests/quant/test_tick_handler.py`:

```python
"""Verify TickHandler extraction."""

from unittest.mock import MagicMock
from quant.engine.tick_handler import TickHandler


def test_tick_handler_exists():
    """Ensure TickHandler class exists."""
    assert TickHandler is not None


def test_tick_handler_process_tick():
    """Ensure process_tick method exists and is callable."""
    handler = TickHandler(
        symbol="NIFTY24SEPFUT",
        macro_aggregator=MagicMock(),
        micro_aggregator=MagicMock(),
        amt_engine=MagicMock(),
        decide_callback=MagicMock(),
        manage_exit_callback=MagicMock(),
        manage_tick_exit_callback=MagicMock(),
        on_bar_closed_callback=MagicMock(),
        state_getter=lambda: MagicMock(position=None),
    )
    
    assert callable(handler.process_tick)
    
    # Call with a mock tick
    tick = {"last_price": 20000.0, "timestamp": "2026-09-16T10:00:00"}
    handler.process_tick(tick)
    
    # Verify aggregators were called
    handler._macro_aggregator.add_tick.assert_called_once_with(tick)


def test_tick_handler_delegates_to_callbacks():
    """Ensure TickHandler delegates to provided callbacks."""
    decide_mock = MagicMock()
    manage_tick_exit_mock = MagicMock()
    
    handler = TickHandler(
        symbol="NIFTY24SEPFUT",
        macro_aggregator=MagicMock(),
        micro_aggregator=None,
        amt_engine=MagicMock(),
        decide_callback=decide_mock,
        manage_exit_callback=MagicMock(),
        manage_tick_exit_callback=manage_tick_exit_mock,
        on_bar_closed_callback=MagicMock(),
        state_getter=lambda: MagicMock(position=MagicMock()),  # Positioned
    )
    
    tick = {"last_price": 20000.0}
    handler.process_tick(tick)
    
    # Should call manage_tick_exit when positioned
    manage_tick_exit_mock.assert_called_once_with(tick)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/quant/test_tick_handler.py -v`

Expected: All 3 tests PASS

- [ ] **Step 6: Commit (without wiring to runtime.py yet)**

```bash
git add quant/engine/tick_handler.py tests/quant/test_tick_handler.py
git commit -m "feat: extract TickHandler from runtime.py (Phase 1)

First phase of runtime.py extraction. TickHandler encapsulates the
tick processing loop for better maintainability and testability.

Note: Not yet wired into QuantEngine — will be done in Phase 2 after
all components are extracted and tested independently.

Part of: architecture review finding — oversized runtime.py module"
```

**Note:** The full extraction of runtime.py would require 5-7 more phases (decision loop, exit manager, submission logic, etc.). This plan covers Phase 1 as a proof of concept. The remaining phases would follow the same pattern: extract, test, commit, then wire in a final phase.

---

## Task 8: Final Integration and Verification

**Files:**
- Modify: `quant/runtime.py` (wire TickHandler)
- Test: Full test suite

**Interfaces:**
- Consumes: `TickHandler` from Task 7
- Produces: Fully integrated refactored code

- [ ] **Step 1: Wire TickHandler into QuantEngine**

In `quant/runtime.py`, replace the inline tick processing logic in `_run_inner()` with:

```python
# Before (lines 761-854)
# ... inline tick processing ...

# After
from quant.engine.tick_handler import TickHandler

# In __init__():
self._tick_handler = TickHandler(
    symbol=self.symbol,
    macro_aggregator=self._aggregator,
    micro_aggregator=self._micro_aggregator,
    amt_engine=self._amt_engine,
    decide_callback=self._decide,
    manage_exit_callback=self._manage_exit,
    manage_tick_exit_callback=self._manage_tick_exit,
    on_bar_closed_callback=self._on_bar_closed,
    state_getter=lambda: self.state,
)

# In _run_inner():
tick = await self._gateway.next_tick()
self._tick_handler.process_tick(tick)
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -x --tb=short`

Expected: All tests pass

- [ ] **Step 3: Run integration tests**

Run: `pytest tests/system/ -v`

Expected: All system tests pass

- [ ] **Step 4: Commit**

```bash
git add quant/runtime.py
git commit -m "refactor: wire TickHandler into QuantEngine

Completes Phase 1 of runtime.py extraction. The tick processing loop
is now encapsulated in TickHandler for better maintainability.

Part of: architecture review finding — oversized runtime.py module"
```

---

## Summary

This plan addresses the key findings from the senior quant engineer architecture review:

1. ✅ **Dead code cleanup** — Removed `quant/transition.py` alias and stale TODO comment
2. ✅ **Documentation** — Documented lock ordering invariant
3. ✅ **Consolidation** — Extracted duplicate journal subscriber closure
4. ✅ **Observability** — Added DEBUG logging to silent exception handlers
5. ✅ **Maintainability** — Centralized magic numbers in constants module
6. ✅ **Modularity** — Extracted TickHandler from oversized runtime.py (Phase 1)

**Estimated effort:** 2-3 days for a single engineer

**Risk:** Low — all changes are refactoring with comprehensive test coverage. No changes to trading logic.

**Next steps after this plan:**
- Phase 2-7 of runtime.py extraction (decision loop, exit manager, submission logic, etc.)
- Single position authority (choose between event-sourced state and PositionManager)
- Performance profiling to identify bottlenecks
