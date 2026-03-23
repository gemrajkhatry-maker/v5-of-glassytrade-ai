# GlassyTrade Backend — Coding Standards Framework

## Overview

This document establishes coding standards and best practices for the GlassyTrade backend to prevent future shotgun surgery code smells and structural inconsistencies. All developers must follow these standards when contributing to the codebase.

---

## 1. File Organization Standards

### 1.1 File Size Limits

| File Type | Maximum Lines | Recommended Lines | Action Required |
|-----------|---------------|-------------------|-----------------|
| Handler | 300 | 150-200 | Split if > 300 |
| Service | 250 | 100-150 | Split if > 250 |
| Utility | 200 | 50-100 | Split if > 200 |
| Model | 150 | 50-100 | Split if > 150 |
| Test | 300 | 100-200 | Split if > 300 |

### 1.2 Single Responsibility Principle

**Rule:** Each file must have exactly one responsibility.

**Examples:**

✅ **Good:**
```python
# entry_gate_coordinator.py — Only gate coordination
class EntryGateCoordinator:
    def check_entry_eligibility(self, ...):
        # Gate checking logic only
```

❌ **Bad:**
```python
# llm_entry_handler.py — Multiple responsibilities
class LLMEntryHandler:
    def check_gates(self, ...):  # Gate logic
    def build_signal(self, ...):  # Signal construction
    def calculate_size(self, ...):  # Position sizing
    def run_llm(self, ...):  # LLM inference
```

### 1.3 Module Naming Convention

**Pattern:** `<component>_<responsibility>.py`

**Examples:**
- `entry_gate_coordinator.py` — Coordinates entry gates
- `signal_constructor.py` — Constructs signals
- `position_sizer.py` — Calculates position sizes
- `session_state_manager.py` — Manages session state

**Avoid:**
- `llm_entry_handler.py` (too broad)
- `trading_session.py` (too broad)
- `utils.py` (too vague)

---

## 2. Code Duplication Standards

### 2.1 DRY Principle (Don't Repeat Yourself)

**Rule:** Never duplicate code across files. Extract common logic to shared utilities.

**Examples:**

✅ **Good:**
```python
# shared/conversion.py
def to_decimal(value: Any) -> Decimal:
    # Single source of truth for decimal conversion
    ...

# entities.py
from shared.conversion import to_decimal

class Signal:
    @classmethod
    def create(cls, price, ...):
        return cls(
            price=to_decimal(price),  # Use shared utility
            ...
        )
```

❌ **Bad:**
```python
# entities.py
def _to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

# database.py
def _to_float(val):
    if val is None:
        return 0.0
    return float(val) if hasattr(val, '__float__') else val

# trade_lifecycle_handler.py
entry_price = float(position.entry_price) if hasattr(position.entry_price, "__float__") else position.entry_price
```

### 2.2 Centralized Services

**Rule:** Common operations must use centralized services.

**Required Centralized Services:**
1. `shared/conversion.py` — Type conversion utilities
2. `shared/session_context.py` — Session information retrieval
3. `shared/error_handling.py` — Error handling patterns
4. `shared/validation.py` — Common validation logic

**Usage:**
```python
# All handlers must use centralized services
from shared.session_context import get_session_info
from shared.conversion import to_decimal, to_float
from shared.error_handling import handle_errors, ErrorContext
```

---

## 3. Error Handling Standards

### 3.1 Consistent Error Handling

**Rule:** All error handling must use standardized patterns.

**Required Patterns:**

#### Pattern 1: Decorator for Non-Critical Operations
```python
from shared.error_handling import handle_errors

@handle_errors(
    error_types=(Exception,),
    default_return=None,
    log_level=logging.WARNING,
)
def non_critical_operation():
    # Implementation
    pass
```

#### Pattern 2: Context Manager for Critical Operations
```python
from shared.error_handling import ErrorContext

def critical_operation():
    with ErrorContext("critical_operation", reraise=True):
        # Critical implementation
        pass
```

#### Pattern 3: Safe Execute for Optional Operations
```python
from shared.error_handling import safe_execute

result = safe_execute(
    risky_function,
    arg1, arg2,
    default_return=fallback_value,
    error_message="Risky operation failed",
)
```

### 3.2 Custom Exception Hierarchy

**Rule:** Use custom exceptions for domain-specific errors.

**Required Exceptions:**
```python
# shared/error_handling.py
class TradingError(Exception):
    """Base exception for trading-related errors."""
    ...

class SignalError(TradingError):
    """Signal construction or validation error."""
    ...

class GateError(TradingError):
    """Entry gate validation error."""
    ...

class LLMError(TradingError):
    """LLM inference error."""
    ...

class StorageError(TradingError):
    """Storage/persistence error."""
    ...

class RiskError(TradingError):
    """Risk management error."""
    ...
```

**Usage:**
```python
# Raise domain-specific exceptions
if not gate_passed:
    raise GateError(
        "Three-Align gate failed",
        gate_name="three_align",
        context={"price": tick.close, "poc": amt_result.poc},
    )
```

### 3.3 No Silent Exception Swallowing

**Rule:** Never silently swallow exceptions. Always log or propagate.

❌ **Bad:**
```python
try:
    risky_operation()
except Exception:
    pass  # Silent swallow — NEVER do this
```

✅ **Good:**
```python
try:
    risky_operation()
except Exception as e:
    logger.warning("Risky operation failed: %s", e, exc_info=True)
    # Or propagate
    raise
```

---

## 4. Type Safety Standards

### 4.1 Type Hints

**Rule:** All function signatures must have type hints.

**Examples:**

✅ **Good:**
```python
def process_signal(
    signal: Signal,
    portfolio: Portfolio,
    symbol: str,
) -> Position | None:
    """Process a trade signal."""
    ...
```

❌ **Bad:**
```python
def process_signal(signal, portfolio, symbol):  # No type hints
    """Process a trade signal."""
    ...
```

### 4.2 Decimal Precision

**Rule:** All financial calculations must use Decimal type.

**Examples:**

✅ **Good:**
```python
from decimal import Decimal

def calculate_pnl(entry_price: Decimal, exit_price: Decimal, size: Decimal) -> Decimal:
    """Calculate PnL with precise decimal arithmetic."""
    return (exit_price - entry_price) * size
```

❌ **Bad:**
```python
def calculate_pnl(entry_price: float, exit_price: float, size: float) -> float:
    """Calculate PnL — may have precision errors."""
    return (exit_price - entry_price) * size
```

### 4.3 Optional Types

**Rule:** Use `Optional[T]` or `T | None` for nullable types.

**Examples:**

✅ **Good:**
```python
def get_position(symbol: str) -> Position | None:
    """Get position for symbol, or None if not found."""
    ...

def process_signal(signal: Signal | None) -> bool:
    """Process signal if present."""
    ...
```

❌ **Bad:**
```python
def get_position(symbol: str):  # Return type unclear
    """Get position for symbol."""
    ...
```

---

## 5. Async/Sync Standards

### 5.1 Clear Async Boundaries

**Rule:** Async functions must be clearly marked and documented.

**Examples:**

✅ **Good:**
```python
async def fetch_market_data(symbol: str) -> list[OHLC]:
    """Fetch market data asynchronously.
    
    This function is async because it performs I/O operations.
    """
    ...

def analyze_data(data: list[OHLC]) -> AMTResult:
    """Analyze data synchronously.
    
    This function is sync because it performs CPU-bound operations.
    """
    ...
```

❌ **Bad:**
```python
def fetch_market_data(symbol: str):  # Unclear if sync or async
    """Fetch market data."""
    ...
```

### 5.2 Thread Safety

**Rule:** Shared mutable state must be protected by locks.

**Examples:**

✅ **Good:**
```python
class SessionStateManager:
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()
    
    def get_or_create_session(self, symbol: str) -> SessionState:
        with self._lock:
            if symbol not in self._sessions:
                self._sessions[symbol] = SessionState(symbol=symbol)
            return self._sessions[symbol]
```

❌ **Bad:**
```python
class SessionStateManager:
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}  # Not thread-safe
    
    def get_or_create_session(self, symbol: str) -> SessionState:
        if symbol not in self._sessions:  # Race condition
            self._sessions[symbol] = SessionState(symbol=symbol)
        return self._sessions[symbol]
```

### 5.3 Lock Ordering

**Rule:** Always acquire locks in the same order to prevent deadlocks.

**Standard Order:**
1. `_session_creation_lock` (outermost)
2. `session._lock` (per-session)
3. `_workers_lock` (handler-specific)

**Example:**
```python
def process_with_multiple_locks():
    with self._session_creation_lock:  # First
        with session._lock:  # Second
            with self._workers_lock:  # Third
                # Processing logic
                pass
```

---

## 6. Documentation Standards

### 6.1 Docstrings

**Rule:** All public functions and classes must have docstrings.

**Format:** Google-style docstrings

**Examples:**

✅ **Good:**
```python
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
    """
    ...
```

❌ **Bad:**
```python
def to_decimal(value):
    # Convert to decimal
    ...
```

### 6.2 Inline Comments

**Rule:** Use inline comments for complex logic only.

**Examples:**

✅ **Good:**
```python
# Calculate dynamic threshold: 50% of VA width, capped at 3% of price
threshold = min(va_range * 0.5, tick.close * 0.03) if va_range > 0 else tick.close * 0.003
```

❌ **Bad:**
```python
# Calculate threshold
threshold = min(va_range * 0.5, tick.close * 0.03) if va_range > 0 else tick.close * 0.003
```

### 6.3 TODO Comments

**Rule:** Use TODO comments for future improvements.

**Format:** `TODO: [Priority] Description`

**Examples:**
```python
# TODO: [HIGH] Extract this logic to shared utility
# TODO: [MEDIUM] Add error handling for edge case
# TODO: [LOW] Optimize performance
```

---

## 7. Testing Standards

### 7.1 Unit Test Coverage

**Rule:** All new code must have unit tests.

**Minimum Coverage:**
- Utility functions: 100%
- Business logic: 90%
- Handlers: 80%
- Services: 80%

### 7.2 Test Naming Convention

**Pattern:** `test_<function_name>_<scenario>`

**Examples:**
```python
def test_to_decimal_with_float():
    """Test decimal conversion with float input."""
    ...

def test_to_decimal_with_string():
    """Test decimal conversion with string input."""
    ...

def test_to_decimal_with_invalid_input():
    """Test decimal conversion with invalid input."""
    ...
```

### 7.3 Test Structure

**Pattern:** Arrange-Act-Assert

**Example:**
```python
def test_signal_creation():
    """Test signal creation from LLM decision."""
    # Arrange
    tick = OHLC(time="2026-03-20", open=100, high=105, low=95, close=102, ...)
    amt_result = AMTResult(poc=100, value_area_high=105, value_area_low=95, ...)
    ai_result = {"direction": "LONG", "rationale": "Test", "confidence": "High"}
    
    # Act
    signal = build_entry_signal(
        direction="LONG",
        tick=tick,
        amt_result=amt_result,
        ai_result=ai_result,
    )
    
    # Assert
    assert signal is not None
    assert signal.type == SignalType.BUY
    assert signal.price == 102
```

---

## 8. Configuration Standards

### 8.1 Centralized Configuration

**Rule:** All configuration must be in centralized config module.

**Required Structure:**
```python
# config/consolidated.py
class ConsolidatedConfig(BaseModel):
    trading: TradingConfig
    llm: LLMConfig
    risk: RiskConfig
    
    @classmethod
    def from_env(cls) -> ConsolidatedConfig:
        """Load configuration from environment variables."""
        ...
```

### 8.2 No Hardcoded Values

**Rule:** Never hardcode values in handlers or services.

❌ **Bad:**
```python
def calculate_size(entry_price, stop_loss):
    max_risk = 0.02  # Hardcoded — NEVER do this
    ...
```

✅ **Good:**
```python
from config.consolidated import get_config

def calculate_size(entry_price, stop_loss):
    config = get_config()
    max_risk = config.trading.max_risk_per_trade
    ...
```

### 8.3 Environment-Based Configuration

**Rule:** Support environment-based configuration.

**Example:**
```python
# config/consolidated.py
class ConsolidatedConfig(BaseModel):
    ...
    
    @classmethod
    def from_env(cls) -> ConsolidatedConfig:
        """Load configuration from environment variables."""
        return cls(
            trading=TradingConfig(
                default_symbol=os.getenv("DEFAULT_SYMBOL", "CRUDEOIL 20 MAR 6500 CALL"),
                ...
            ),
            ...
        )
```

---

## 9. Logging Standards

### 9.1 Structured Logging

**Rule:** Use structured logging with context.

**Examples:**

✅ **Good:**
```python
logger.info(
    "Signal generated: %s @ %.2f (SL=%.2f, TP=%.2f, source=%s)",
    sig.type,
    sig.price,
    sig.stop_loss,
    sig.take_profit,
    sig.source,
)
```

❌ **Bad:**
```python
logger.info("Signal generated")  # No context
```

### 9.2 Log Levels

**Rule:** Use appropriate log levels.

| Level | Usage | Example |
|-------|-------|---------|
| DEBUG | Detailed debugging | `logger.debug("Processing tick %s", tick)` |
| INFO | Normal operations | `logger.info("Signal generated: %s", direction)` |
| WARNING | Potential issues | `logger.warning("LLM timeout, using fallback")` |
| ERROR | Errors | `logger.error("Signal construction failed: %s", e)` |
| CRITICAL | Critical failures | `logger.critical("Trading engine crashed")` |

### 9.3 Exception Logging

**Rule:** Always include exception info when logging errors.

**Examples:**

✅ **Good:**
```python
try:
    risky_operation()
except Exception as e:
    logger.error("Operation failed: %s", e, exc_info=True)
```

❌ **Bad:**
```python
try:
    risky_operation()
except Exception as e:
    logger.error("Operation failed")  # No exception info
```

---

## 10. Performance Standards

### 10.1 Avoid Premature Optimization

**Rule:** Optimize only when necessary. Profile first.

**Process:**
1. Write clear, readable code
2. Profile to identify bottlenecks
3. Optimize only hot paths
4. Document optimization rationale

### 10.2 Caching

**Rule:** Cache expensive operations.

**Example:**
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_calculation(param: str) -> float:
    """Expensive calculation with caching."""
    ...
```

### 10.3 Database Operations

**Rule:** Batch database operations when possible.

**Example:**
```python
# Good: Batch insert
self._conn.executemany(
    "INSERT INTO ticks (symbol, time, ...) VALUES (?, ?, ...)",
    batch_data,
)

# Bad: Individual inserts
for row in batch_data:
    self._conn.execute(
        "INSERT INTO ticks (symbol, time, ...) VALUES (?, ?, ...)",
        row,
    )
```

---

## 11. Code Review Checklist

### Pre-Review Checklist

Before submitting code for review, verify:

- [ ] File size within limits
- [ ] Single responsibility per file
- [ ] No code duplication
- [ ] Type hints on all functions
- [ ] Docstrings on all public functions
- [ ] Error handling standardized
- [ ] Unit tests included
- [ ] No hardcoded values
- [ ] Logging appropriate
- [ ] Thread safety considered

### Review Checklist

During code review, verify:

- [ ] Code follows naming conventions
- [ ] Error handling is consistent
- [ ] No silent exception swallowing
- [ ] Type safety maintained
- [ ] Documentation is clear
- [ ] Tests are comprehensive
- [ ] Performance is acceptable
- [ ] Security considerations addressed

---

## 12. Enforcement

### 12.1 Automated Checks

**Required Automated Checks:**
1. **Linter:** flake8 or ruff for style checking
2. **Type Checker:** mypy for type safety
3. **Formatter:** black for code formatting
4. **Import Sorter:** isort for import organization

**Configuration:**
```yaml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true

[tool.black]
line-length = 100
target-version = ["py311"]
```

### 12.2 CI/CD Integration

**Required CI/CD Checks:**
1. Linting passes
2. Type checking passes
3. All tests pass
4. Code coverage meets minimum
5. No security vulnerabilities

### 12.3 Code Review Process

**Required Process:**
1. All changes require code review
2. At least one approval required
3. All automated checks must pass
4. Documentation must be updated
5. Tests must be included

---

## 13. Migration Guide

### 13.1 Existing Code Migration

**Process for Migrating Existing Code:**

1. **Identify Violations**
   - Run linter to find style violations
   - Run type checker to find type issues
   - Review file sizes and responsibilities

2. **Prioritize Changes**
   - Critical violations first
   - High-impact changes first
   - Low-risk changes first

3. **Incremental Migration**
   - Migrate one file at a time
   - Run tests after each change
   - Update documentation

4. **Validation**
   - Verify all tests pass
   - Verify no regressions
   - Verify performance acceptable

### 13.2 New Code Requirements

**All New Code Must:**
1. Follow all standards in this document
2. Include comprehensive tests
3. Include clear documentation
4. Pass all automated checks
5. Be reviewed by at least one other developer

---

## 14. Quick Reference

### File Size Limits
- Handler: 300 lines max
- Service: 250 lines max
- Utility: 200 lines max
- Model: 150 lines max

### Required Imports
```python
from shared.conversion import to_decimal, to_float
from shared.session_context import get_session_info
from shared.error_handling import handle_errors, ErrorContext
from config.consolidated import get_config
```

### Error Handling Patterns
```python
# Non-critical
@handle_errors(error_types=(Exception,), default_return=None)

# Critical
with ErrorContext("operation", reraise=True):

# Optional
result = safe_execute(func, *args, default_return=fallback)
```

### Type Hints
```python
def function(arg: Type) -> ReturnType:
    """Docstring."""
    ...
```

### Logging
```python
logger.info("Message: %s", context)
logger.error("Error: %s", e, exc_info=True)
```

---

*Document Version: 1.0*
*Last Updated: 2026-03-20*
*Author: Code Analysis System*