# GlassyTrade Backend — Refactoring Implementation Plan

## Overview

This document provides detailed, actionable refactoring instructions for addressing the structural inconsistencies and shotgun surgery code smells identified in the analysis. Each refactoring step includes specific file changes, code examples, and validation criteria.

---

## Phase 1: Extract Shared Utilities (Week 1-2)

### 1.1 Create Unified Conversion Utilities

**File:** `shared/conversion.py`

```python
"""Unified decimal/float conversion utilities for financial calculations.

This module provides consistent type conversion across the codebase,
preventing precision errors in financial calculations.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Union


def to_decimal(value: Any) -> Decimal:
    """Convert any numeric type to Decimal for precise financial calculations.
    
    Args:
        value: Input value (float, int, str, or Decimal)
    
    Returns:
        Decimal representation of the value
    
    Raises:
        ValueError: If value cannot be converted to Decimal
    
    Examples:
        >>> to_decimal(123.45)
        Decimal('123.45')
        >>> to_decimal("123.45")
        Decimal('123.45')
        >>> to_decimal(Decimal("123.45"))
        Decimal('123.45')
    """
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
    """Convert any numeric type to float.
    
    Args:
        value: Input value (float, int, str, or Decimal)
        default: Default value if conversion fails
    
    Returns:
        Float representation of the value
    
    Examples:
        >>> to_float(Decimal("123.45"))
        123.45
        >>> to_float("123.45")
        123.45
        >>> to_float(None)
        0.0
    """
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
    
    if hasattr(value, '__float__'):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    
    return default


def safe_decimal_operation(
    a: Any,
    b: Any,
    operation: str = "add"
) -> Decimal:
    """Perform safe decimal operations with automatic conversion.
    
    Args:
        a: First operand
        b: Second operand
        operation: Operation type ("add", "subtract", "multiply", "divide")
    
    Returns:
        Result of the operation as Decimal
    
    Raises:
        ValueError: If operation is not supported
        ZeroDivisionError: If division by zero
    """
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
    else:
        raise ValueError(f"Unsupported operation: {operation}")


# Convenience functions for common operations
def decimal_add(a: Any, b: Any) -> Decimal:
    """Add two values as Decimals."""
    return safe_decimal_operation(a, b, "add")


def decimal_subtract(a: Any, b: Any) -> Decimal:
    """Subtract two values as Decimals."""
    return safe_decimal_operation(a, b, "subtract")


def decimal_multiply(a: Any, b: Any) -> Decimal:
    """Multiply two values as Decimals."""
    return safe_decimal_operation(a, b, "multiply")


def decimal_divide(a: Any, b: Any) -> Decimal:
    """Divide two values as Decimals."""
    return safe_decimal_operation(a, b, "divide")
```

**Migration Steps:**
1. Create `shared/conversion.py` with the above content
2. Update `app/domain/trading/models/entities.py`:
   - Remove `_to_decimal()` function
   - Import `to_decimal` from `shared.conversion`
   - Update `Signal.create()` and `Position.update_pnl()` to use `to_decimal()`
3. Update `app/infrastructure/storage/database.py`:
   - Remove `_to_float()` helper
   - Import `to_float` from `shared.conversion`
   - Update all conversion calls
4. Update `app/application/handlers/trade_lifecycle_handler.py`:
   - Remove inline conversion logic
   - Import conversion utilities
5. Update `app/application/services/trading_session.py`:
   - Remove scattered conversion calls
   - Use unified conversion utilities

**Validation:**
- [ ] All decimal conversions use `to_decimal()`
- [ ] All float conversions use `to_float()`
- [ ] No duplicate conversion logic remains
- [ ] Financial calculations maintain precision
- [ ] Unit tests pass for conversion utilities

---

### 1.2 Create Session Context Service

**File:** `shared/session_context.py`

```python
"""Session context service for consistent session info retrieval.

This module centralizes session information retrieval, eliminating
duplication across handlers and services.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# IST timezone constant
IST = timezone(timedelta(hours=5, minutes=30))


class SessionContext:
    """Centralized session context provider.
    
    Provides consistent session information across all handlers and services.
    """
    
    def __init__(self, market: str = "NSE"):
        self._market = market
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 60  # Cache for 60 seconds
        self._last_update = 0
    
    def get_session_info(
        self,
        timestamp: str | datetime | None = None,
        open_price: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
    ) -> Dict[str, Any]:
        """Get session information for the given timestamp.
        
        Args:
            timestamp: Current timestamp (ISO string or datetime)
            open_price: Current session open price
            prior_vah: Prior session VAH
            prior_val: Prior session VAL
        
        Returns:
            Dictionary containing session information
        """
        # Normalize timestamp
        if timestamp is None:
            dt = datetime.now(IST)
        elif isinstance(timestamp, str):
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.now(IST)
        else:
            dt = timestamp
        
        # Convert to IST if needed
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_ist = dt.astimezone(IST)
        
        # Determine session phase
        session_phase = self._get_session_phase(dt_ist)
        
        # Get strategy hints
        strategy_hints = self._get_strategy_hints(session_phase)
        
        return {
            "session": session_phase,
            "timestamp": dt_ist.isoformat(),
            "market": self._market,
            "open_price": open_price,
            "prior_vah": prior_vah,
            "prior_val": prior_val,
            "allow_entry": strategy_hints["allow_entry"],
            "allow_trend": strategy_hints["allow_trend"],
            "allow_reversion": strategy_hints["allow_reversion"],
            "favor_strategy": strategy_hints["favor_strategy"],
            "opening_relation": self._get_opening_relation(
                open_price, prior_vah, prior_val
            ),
        }
    
    def _get_session_phase(self, dt: datetime) -> str:
        """Determine session phase based on time.
        
        NSE Session Phases (IST):
        - 09:15-09:30: Opening Auction
        - 09:30-11:30: Primary Setup Window
        - 11:30-14:00: Midday Consolidation
        - 14:00-15:15: Power Hour
        - 15:15-15:30: Closing Auction
        """
        hour = dt.hour
        minute = dt.minute
        
        # Convert to minutes since midnight
        time_minutes = hour * 60 + minute
        
        # NSE timings (in minutes)
        if time_minutes < 555:  # Before 09:15
            return "PRE_MARKET"
        elif time_minutes < 570:  # 09:15-09:30
            return "OPENING_AUCTION"
        elif time_minutes < 690:  # 09:30-11:30
            return "PRIMARY_WINDOW"
        elif time_minutes < 840:  # 11:30-14:00
            return "MIDDAY_CONSOLIDATION"
        elif time_minutes < 915:  # 14:00-15:15
            return "POWER_HOUR"
        elif time_minutes < 930:  # 15:15-15:30
            return "CLOSING_AUCTION"
        else:
            return "POST_MARKET"
    
    def _get_strategy_hints(self, session_phase: str) -> Dict[str, Any]:
        """Get strategy hints based on session phase."""
        hints = {
            "PRE_MARKET": {
                "allow_entry": False,
                "allow_trend": False,
                "allow_reversion": False,
                "favor_strategy": "NONE",
            },
            "OPENING_AUCTION": {
                "allow_entry": False,
                "allow_trend": False,
                "allow_reversion": False,
                "favor_strategy": "NONE",
            },
            "PRIMARY_WINDOW": {
                "allow_entry": True,
                "allow_trend": True,
                "allow_reversion": True,
                "favor_strategy": "TREND_CONTINUATION",
            },
            "MIDDAY_CONSOLIDATION": {
                "allow_entry": True,
                "allow_trend": False,
                "allow_reversion": True,
                "favor_strategy": "MEAN_REVERSION",
            },
            "POWER_HOUR": {
                "allow_entry": True,
                "allow_trend": True,
                "allow_reversion": True,
                "favor_strategy": "TREND_CONTINUATION",
            },
            "CLOSING_AUCTION": {
                "allow_entry": False,
                "allow_trend": False,
                "allow_reversion": False,
                "favor_strategy": "NONE",
            },
            "POST_MARKET": {
                "allow_entry": False,
                "allow_trend": False,
                "allow_reversion": False,
                "favor_strategy": "NONE",
            },
        }
        return hints.get(session_phase, hints["POST_MARKET"])
    
    def _get_opening_relation(
        self,
        open_price: float,
        prior_vah: float,
        prior_val: float,
    ) -> str:
        """Determine opening relation to prior session value area."""
        if open_price <= 0 or prior_vah <= 0 or prior_val <= 0:
            return "UNKNOWN"
        
        if open_price > prior_vah:
            return "ABOVE_VAH"
        elif open_price < prior_val:
            return "BELOW_VAL"
        else:
            return "INSIDE_VA"


# Singleton instance
_session_context = SessionContext()


def get_session_info(
    timestamp: str | datetime | None = None,
    market: str = "NSE",
    open_price: float = 0.0,
    prior_vah: float = 0.0,
    prior_val: float = 0.0,
) -> Dict[str, Any]:
    """Get session information (convenience function).
    
    This is the primary interface for session info retrieval.
    All handlers should use this function instead of implementing
    their own session logic.
    """
    if market != _session_context._market:
        context = SessionContext(market)
    else:
        context = _session_context
    
    return context.get_session_info(
        timestamp=timestamp,
        open_price=open_price,
        prior_vah=prior_vah,
        prior_val=prior_val,
    )
```

**Migration Steps:**
1. Create `shared/session_context.py` with the above content
2. Update `app/application/handlers/llm_entry_handler.py`:
   - Remove duplicate session info logic
   - Import `get_session_info` from `shared.session_context`
3. Update `app/application/services/trading_session.py`:
   - Remove duplicate session info logic
   - Use centralized session context
4. Update `app/application/engine.py`:
   - Remove duplicate session info logic
   - Use centralized session context

**Validation:**
- [ ] All session info retrieval uses centralized service
- [ ] No duplicate session phase logic remains
- [ ] Session hints are consistent across handlers
- [ ] Unit tests pass for session context

---

### 1.3 Create Error Handling Utilities

**File:** `shared/error_handling.py`

```python
"""Standardized error handling utilities.

This module provides consistent error handling patterns across
the codebase, improving debugging and error propagation.
"""

from __future__ import annotations

import functools
import logging
import traceback
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])


class TradingError(Exception):
    """Base exception for trading-related errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "TRADING_ERROR",
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.context = context or {}
        self.message = message


class SignalError(TradingError):
    """Signal construction or validation error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, "SIGNAL_ERROR", context)


class GateError(TradingError):
    """Entry gate validation error."""
    
    def __init__(self, message: str, gate_name: str, context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        ctx["gate_name"] = gate_name
        super().__init__(message, "GATE_ERROR", ctx)


class LLMError(TradingError):
    """LLM inference error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, "LLM_ERROR", context)


class StorageError(TradingError):
    """Storage/persistence error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, "STORAGE_ERROR", context)


class RiskError(TradingError):
    """Risk management error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, "RISK_ERROR", context)


def handle_errors(
    error_types: tuple[type[Exception], ...] = (Exception,),
    default_return: Any = None,
    log_level: int = logging.ERROR,
    reraise: bool = False,
) -> Callable[[F], F]:
    """Decorator for standardized error handling.
    
    Args:
        error_types: Tuple of exception types to catch
        default_return: Default value to return on error
        log_level: Logging level for errors
        reraise: Whether to reraise the exception after logging
    
    Returns:
        Decorated function with error handling
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except error_types as e:
                # Build context
                context = {
                    "function": func.__name__,
                    "module": func.__module__,
                    "args": str(args)[:200],  # Truncate for logging
                    "kwargs": str(kwargs)[:200],
                }
                
                # Log error
                logger.log(
                    log_level,
                    "Error in %s.%s: %s",
                    func.__module__,
                    func.__name__,
                    str(e),
                    exc_info=True,
                    extra={"context": context},
                )
                
                if reraise:
                    raise
                
                return default_return
        
        return wrapper  # type: ignore
    return decorator


def log_and_continue(
    message: str,
    level: int = logging.WARNING,
    exc_info: bool = True,
    **extra_context,
) -> None:
    """Log an error and continue execution.
    
    Use this for non-critical errors where execution should continue.
    """
    logger.log(
        level,
        message,
        exc_info=exc_info,
        extra={"context": extra_context},
    )


def safe_execute(
    func: Callable[..., Any],
    *args,
    default_return: Any = None,
    error_message: str = "Operation failed",
    **kwargs,
) -> Any:
    """Safely execute a function with error handling.
    
    Args:
        func: Function to execute
        *args: Positional arguments for function
        default_return: Default value on error
        error_message: Message to log on error
        **kwargs: Keyword arguments for function
    
    Returns:
        Function result or default_return on error
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(
            "%s: %s",
            error_message,
            str(e),
            exc_info=True,
            extra={
                "function": func.__name__,
                "args": str(args)[:200],
                "kwargs": str(kwargs)[:200],
            },
        )
        return default_return


class ErrorContext:
    """Context manager for error handling with automatic logging."""
    
    def __init__(
        self,
        operation: str,
        reraise: bool = False,
        default_return: Any = None,
    ):
        self.operation = operation
        self.reraise = reraise
        self.default_return = default_return
        self.error: Exception | None = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error = exc_val
            logger.error(
                "Error during %s: %s",
                self.operation,
                str(exc_val),
                exc_info=True,
            )
            return not self.reraise  # Suppress if not reraising
        return False
```

**Migration Steps:**
1. Create `shared/error_handling.py` with the above content
2. Update critical handlers to use standardized error handling:
   - `llm_entry_handler.py`: Use `@handle_errors()` decorator
   - `trading_session.py`: Use `ErrorContext` for critical operations
   - `engine.py`: Use `safe_execute()` for non-critical operations
3. Replace inconsistent error handling patterns throughout codebase

**Validation:**
- [ ] All critical operations use standardized error handling
- [ ] Error messages are consistent and informative
- [ ] Error context is preserved for debugging
- [ ] No silent exception swallowing

---

## Phase 2: Split Monolithic Handlers (Week 3-4)

### 2.1 Split `llm_entry_handler.py`

**Current State:** ~700 lines, 8+ responsibilities

**Target State:** 4 focused modules, ~600 lines total

#### Module 1: `llm_entry_handler.py` (Core LLM Coordination)

```python
"""LLM Entry Handler — LLM inference coordination only.

Responsibilities:
- LLM inference triggering
- Queue management
- Thread pool coordination
- Inference result caching
"""

from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    from app.domain.ports.event_bus import EventBusPort
    from app.domain.ports.storage import StoragePort

logger = logging.getLogger(__name__)


class LLMEntryHandler:
    """Handles LLM inference coordination only."""

    def __init__(
        self,
        gen_ai_service: GenerativeAIService,
        event_bus: EventBusPort,
        storage: StoragePort | None = None,
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._event_bus = event_bus
        self._storage = storage
        
        # Thread pools
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._predict_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        
        # Per-symbol queues
        self._llm_queues: dict[str, queue.Queue] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

    def should_run(self, **kwargs) -> bool:
        """Check if LLM inference should run."""
        # Simplified check — delegates to gate coordinator
        return self._gen_ai_service.is_ready()

    def run_entry(self, session, symbol: str, tick, amt_result) -> None:
        """Queue LLM inference for background processing."""
        # Implementation delegated to gate coordinator
        pass

    def cleanup(self) -> None:
        """Shutdown thread pools."""
        for pool in (self._executor, self._predict_executor):
            if pool:
                pool.shutdown(wait=False)
```

#### Module 2: `entry_gate_coordinator.py` (Gate Orchestration)

```python
"""Entry Gate Coordinator — Orchestrates gate checking.

Responsibilities:
- Three-Align gate coordination
- Confirmation bundle validation
- Gate pipeline execution
- Entry eligibility determination
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


class EntryGateCoordinator:
    """Coordinates entry gate checking."""

    def check_entry_eligibility(
        self,
        data: list[OHLC],
        amt_result: AMTResult,
        tick: OHLC,
        order_book=None,
        **kwargs,
    ) -> tuple[bool, str]:
        """Check if entry is eligible through all gates.
        
        Returns:
            Tuple of (eligible: bool, reason: str)
        """
        from app.domain.fabio_ai.services.entry_gate import (
            three_align_check,
            check_momentum_fade,
            run_gate_pipeline,
        )
        
        # Three-Align gate
        gate_passed, confirmation_strong, is_second_drive = three_align_check(
            data=data,
            amt_result=amt_result,
            tick=tick,
            order_book=order_book,
            **kwargs,
        )
        
        if not gate_passed:
            return False, "Three-Align gate failed"
        
        # Momentum fade gate
        if check_momentum_fade(data, tick, kwargs.get("direction", "LONG")):
            return False, "Momentum fade detected"
        
        # Gate pipeline
        gate_passed, gate_reason, gate_detail = run_gate_pipeline(
            data=data,
            amt_result=amt_result,
            tick=tick,
            **kwargs,
        )
        
        if not gate_passed:
            return False, f"Gate pipeline: {gate_reason}"
        
        return True, "All gates passed"
```

#### Module 3: `signal_constructor.py` (Signal Building)

```python
"""Signal Constructor — Builds trade signals.

Responsibilities:
- Signal construction from LLM output
- Signal validation
- Signal metadata enrichment
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Signal
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


class SignalConstructor:
    """Constructs trade signals from LLM decisions."""

    def construct_signal(
        self,
        direction: str,
        tick: OHLC,
        amt_result: AMTResult,
        ai_result: dict,
        **kwargs,
    ) -> Signal | None:
        """Construct a trade signal.
        
        Returns:
            Signal object or None if construction fails
        """
        from app.domain.fabio_ai.services.entry_gate import build_entry_signal
        
        try:
            signal = build_entry_signal(
                direction=direction,
                tick=tick,
                amt_result=amt_result,
                ai_result=ai_result,
                **kwargs,
            )
            return signal
        except Exception as e:
            logger.error("Signal construction failed: %s", e, exc_info=True)
            return None
```

#### Module 4: `position_sizer.py` (Position Sizing)

```python
"""Position Sizer — Calculates position sizes.

Responsibilities:
- Position size calculation
- Risk-based sizing
- Confidence-based adjustments
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


class PositionSizer:
    """Calculates position sizes based on risk and confidence."""

    def calculate_size(
        self,
        entry_price: float,
        stop_loss: float,
        equity: float,
        confidence: str = "Medium",
        **kwargs,
    ) -> tuple[float, float]:
        """Calculate position size.
        
        Returns:
            Tuple of (size, risk_amount)
        """
        from app.domain.constants import MAX_RISK_PER_TRADE
        
        risk_per_trade = equity * MAX_RISK_PER_TRADE
        risk_per_unit = abs(entry_price - stop_loss)
        
        if risk_per_unit <= 0:
            return 0.0, 0.0
        
        # Base size
        base_size = risk_per_trade / risk_per_unit
        
        # Confidence adjustment
        confidence_multiplier = {
            "High": 1.0,
            "Medium": 0.75,
            "Low": 0.5,
        }.get(confidence, 0.5)
        
        final_size = base_size * confidence_multiplier
        
        return final_size, risk_per_trade
```

**Migration Steps:**
1. Create the 4 new modules with the above content
2. Extract relevant logic from `llm_entry_handler.py` into each module
3. Update `llm_entry_handler.py` to delegate to new modules
4. Update imports in dependent files
5. Run tests to verify functionality

**Validation:**
- [ ] Each module has single responsibility
- [ ] No duplicate logic across modules
- [ ] All existing functionality preserved
- [ ] Unit tests pass for each module
- [ ] Integration tests pass for entry flow

---

### 2.2 Split `trading_session.py`

**Current State:** ~1000 lines, 10+ responsibilities

**Target State:** 4 focused modules, ~750 lines total

#### Module 1: `trading_session.py` (Core Coordination)

```python
"""Trading Session — Core session coordination.

Responsibilities:
- Session lifecycle management
- Handler coordination
- Event publishing
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.ports.event_bus import EventBusPort

logger = logging.getLogger(__name__)


class TradingSessionService:
    """Core trading session coordinator."""

    def __init__(self, event_bus: EventBusPort, **kwargs):
        self._event_bus = event_bus
        # Delegate to specialized managers
        self._state_manager = SessionStateManager()
        self._risk_coordinator = SessionRiskCoordinator()
        self._event_logger = SessionEventLogger()

    def process_tick(self, symbol: str, tick, order_book=None, oi_data=None) -> dict:
        """Process a new tick."""
        # Delegate to specialized managers
        session = self._state_manager.get_or_create_session(symbol)
        
        # Publish tick event
        self._event_bus.publish(TickReceived(
            symbol=symbol,
            tick=tick,
            order_book=order_book,
            data=tuple(session.data),
        ))
        
        return self._build_state_snapshot(session)
```

#### Module 2: `session_state_manager.py` (State Management)

```python
"""Session State Manager — Manages per-symbol session state.

Responsibilities:
- Session creation and retrieval
- State persistence
- Session cleanup
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.aggregates import Portfolio

logger = logging.getLogger(__name__)


class SessionStateManager:
    """Manages per-symbol session state."""

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def get_or_create_session(self, symbol: str) -> SessionState:
        """Get or create a session for the symbol."""
        with self._lock:
            if symbol not in self._sessions:
                self._sessions[symbol] = SessionState(symbol=symbol)
            return self._sessions[symbol]
```

#### Module 3: `session_risk_coordinator.py` (Risk Management)

```python
"""Session Risk Coordinator — Manages session-level risk.

Responsibilities:
- Session risk manager integration
- Risk state tracking
- Risk-based decisions
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Position

logger = logging.getLogger(__name__)


class SessionRiskCoordinator:
    """Coordinates session-level risk management."""

    def __init__(self):
        self._risk_managers: dict[str, RiskManager] = {}

    def validate_entry(self, symbol: str, signal) -> bool:
        """Validate entry against risk limits."""
        risk_manager = self._risk_managers.get(symbol)
        if risk_manager:
            return risk_manager.validate(signal)
        return True
```

#### Module 4: `session_event_logger.py` (Event Logging)

```python
"""Session Event Logger — Handles event logging.

Responsibilities:
- Position event logging
- Trade journal logging
- Explainability tracking
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Position

logger = logging.getLogger(__name__)


class SessionEventLogger:
    """Handles session event logging."""

    def __init__(self):
        self._journal = None  # Initialized separately

    def log_entry(self, symbol: str, position: Position, signal) -> None:
        """Log a position entry."""
        if self._journal:
            self._journal.log_entry(symbol=symbol, position=position, signal=signal)
```

**Migration Steps:**
1. Create the 4 new modules with the above content
2. Extract relevant logic from `trading_session.py` into each module
3. Update `trading_session.py` to delegate to new modules
4. Update imports in dependent files
5. Run tests to verify functionality

**Validation:**
- [ ] Each module has single responsibility
- [ ] No duplicate logic across modules
- [ ] All existing functionality preserved
- [ ] Unit tests pass for each module
- [ ] Integration tests pass for session flow

---

## Phase 3: Strengthen Domain Boundaries (Week 5-8)

### 3.1 Clean Domain Layer

**Goal:** Remove all infrastructure concerns from domain layer.

**Changes:**
1. Move thread pool management from `entry_gate.py` to infrastructure
2. Move LLM inference queuing from `llm_entry_handler.py` to infrastructure
3. Move database persistence from `trading_session.py` to infrastructure
4. Create clear domain events for all state changes

**Validation:**
- [ ] Domain layer has no infrastructure imports
- [ ] Domain logic is testable without infrastructure
- [ ] All I/O operations are in infrastructure layer
- [ ] Domain events capture all state changes

### 3.2 Refine Application Layer

**Goal:** Thin application services (coordination only).

**Changes:**
1. Application services delegate to domain services
2. Application services handle orchestration only
3. Clear input/output boundaries for each service
4. Consistent error handling across services

**Validation:**
- [ ] Application services are thin (< 200 lines each)
- [ ] No business logic in application layer
- [ ] Clear boundaries between layers
- [ ] Consistent error propagation

### 3.3 Isolate Infrastructure Layer

**Goal:** All I/O operations in infrastructure layer.

**Changes:**
1. All database operations in infrastructure
2. All external API calls in infrastructure
3. All file operations in infrastructure
4. Clear adapter interfaces for all external dependencies

**Validation:**
- [ ] No I/O operations in domain layer
- [ ] No I/O operations in application layer
- [ ] All external dependencies have adapters
- [ ] Infrastructure layer is independently testable

---

## Phase 4: Configuration Consolidation (Week 9-10)

### 4.1 Create Consolidated Configuration

**File:** `config/consolidated.py`

```python
"""Consolidated configuration management.

This module provides a single source of truth for all configuration,
eliminating scattered configuration across multiple files.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import yaml
from pydantic import BaseModel, Field


class TradingConfig(BaseModel):
    """Trading-specific configuration."""
    
    default_symbol: str = Field(default="CRUDEOIL 20 MAR 6500 CALL")
    stream_interval: str = Field(default="5m")
    tick_poll_seconds: float = Field(default=5.0)
    allow_short: bool = Field(default=False)
    max_risk_per_trade: float = Field(default=0.02)


class LLMConfig(BaseModel):
    """LLM inference configuration."""
    
    backend: str = Field(default="mlx")
    temperature: float = Field(default=0.3)
    max_new_tokens: int = Field(default=120)
    timeout_seconds: float = Field(default=15.0)


class RiskConfig(BaseModel):
    """Risk management configuration."""
    
    max_daily_drawdown: float = Field(default=0.05)
    max_consecutive_losses: int = Field(default=3)
    cooldown_seconds: int = Field(default=300)


class ConsolidatedConfig(BaseModel):
    """Consolidated application configuration."""
    
    trading: TradingConfig = Field(default_factory=TradingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    
    @classmethod
    def from_env(cls) -> ConsolidatedConfig:
        """Load configuration from environment variables."""
        # Implementation for environment-based loading
        return cls()


# Singleton instance
_config = ConsolidatedConfig.from_env()


def get_config() -> ConsolidatedConfig:
    """Get the consolidated configuration."""
    return _config
```

**Migration Steps:**
1. Create `config/consolidated.py` with the above content
2. Migrate configuration from `config.py` to consolidated config
3. Remove hardcoded values from handlers
4. Update all config access to use consolidated config

**Validation:**
- [ ] All configuration is in consolidated config
- [ ] No hardcoded values in handlers
- [ ] Configuration is validated
- [ ] Environment-based configuration works

---

## Phase 5: Error Handling Standardization (Week 11-12)

### 5.1 Implement Standardized Error Handling

**Changes:**
1. All handlers use `@handle_errors()` decorator
2. All critical operations use `ErrorContext`
3. All non-critical operations use `safe_execute()`
4. Error messages are consistent and informative

**Validation:**
- [ ] All error handling is standardized
- [ ] Error messages are consistent
- [ ] Error context is preserved
- [ ] No silent exception swallowing

---

## Implementation Checklist

### Phase 1: Shared Utilities
- [ ] Create `shared/conversion.py`
- [ ] Create `shared/session_context.py`
- [ ] Create `shared/error_handling.py`
- [ ] Migrate all conversion logic
- [ ] Migrate all session context logic
- [ ] Migrate error handling patterns

### Phase 2: Split Handlers
- [ ] Split `llm_entry_handler.py` into 4 modules
- [ ] Split `trading_session.py` into 4 modules
- [ ] Split `engine.py` into 4 modules
- [ ] Update all imports
- [ ] Run all tests

### Phase 3: Domain Boundaries
- [ ] Clean domain layer
- [ ] Refine application layer
- [ ] Isolate infrastructure layer
- [ ] Verify layer separation

### Phase 4: Configuration
- [ ] Create consolidated config
- [ ] Migrate all configuration
- [ ] Remove hardcoded values
- [ ] Test configuration loading

### Phase 5: Error Handling
- [ ] Implement standardized error handling
- [ ] Update all handlers
- [ ] Verify error propagation
- [ ] Test error scenarios

---

## Testing Strategy

### Unit Tests
- Test each extracted module independently
- Test conversion utilities with edge cases
- Test session context with various timestamps
- Test error handling with various exceptions

### Integration Tests
- Test entry flow with all gates
- Test session flow with all handlers
- Test error propagation across layers
- Test configuration loading

### Regression Tests
- Verify all existing functionality preserved
- Verify no performance degradation
- Verify no new bugs introduced

---

## Rollback Strategy

### Phase 1 Rollback
- Keep original conversion logic in place
- Keep original session context logic in place
- Keep original error handling in place

### Phase 2 Rollback
- Keep original monolithic handlers
- Update imports to use original handlers

### Phase 3 Rollback
- Keep original domain boundaries
- Accept mixed concerns temporarily

### Phase 4 Rollback
- Keep original configuration
- Accept scattered configuration temporarily

### Phase 5 Rollback
- Keep original error handling
- Accept inconsistent error handling temporarily

---

## Success Criteria

### Code Quality
- [ ] Average file size < 300 lines
- [ ] Code duplication < 5%
- [ ] Cyclomatic complexity < 10

### Maintainability
- [ ] Time to add feature reduced by 40%
- [ ] Bug fix time reduced by 30%
- [ ] Code review time reduced by 50%

### Testing
- [ ] Unit test coverage > 80%
- [ ] Integration test coverage > 60%
- [ ] All tests passing

---

*Document Version: 1.0*
*Last Updated: 2026-03-20*
*Author: Code Analysis System*