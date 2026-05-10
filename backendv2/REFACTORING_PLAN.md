# Architecture Refactoring Implementation Plan
## BackendV2 Structural Modernization

**Source**: `ARCHITECTURE_DEEP_REVIEW.md`  
**Target**: Eliminate god classes, shotgun surgery, layer violations, and duplication  
**Timeline**: 8 weeks (phased)  
**Test Guard**: 2,269 tests must pass after every phase  

---

## Guiding Principles

1. **Tests First**: Every refactoring is preceded by characterization tests
2. **Additive Changes**: New code is added; old code is deprecated, then deleted
3. **Zero Regressions**: Full suite (2,269 tests) must pass at every commit
4. **Vertical Slices**: Each phase delivers end-to-end value
5. **Feature Flags**: High-risk changes are toggleable

---

## Phase Overview

| Phase | Duration | Focus | Risk | Tests Added |
|-------|----------|-------|------|-------------|
| **Phase 0** | Week 1 | Quick wins: duplicates, config, events | Low | +20 |
| **Phase 1** | Weeks 2-3 | Canonical objects: TradingSignal, VWAPProfile | Medium | +40 |
| **Phase 2** | Weeks 4-5 | Split god classes: LLMEntryHandler, SessionRuntime | High | +60 |
| **Phase 3** | Week 6 | Layer violations + Unified risk | Medium | +30 |
| **Phase 4** | Week 7 | Repository pattern + Adapter splits | Medium | +40 |
| **Phase 5** | Week 8 | Cleanup: delete deprecated, final verify | Low | +20 |

---

## Phase 0: Quick Wins (Week 1)

### Goal
Eliminate low-risk duplication and structural inconsistencies. Build confidence in the refactoring process.

### Deliverables
1. **Merge duplicate InitialBalanceEngine**
2. **Unify config loading**
3. **Unify event taxonomy**
4. **Create LLM adapter base class**
5. **Add per-symbol state pruning**

### 0.1 Merge Duplicate InitialBalanceEngine

**Files**:
- `app/domain/services/initial_balance_engine.py` (DELETE)
- `app/domain/amt/service/initial_balance_engine.py` (KEEP)

**Steps**:
1. Compare implementations
   - `domain/services/`: Legacy IB engine, 112 lines, uses OHLC candles
   - `domain/amt/service/`: AMT IB engine, 112 lines, uses raw ticks/bars
2. Determine which is used by runtime pipeline
   - Search imports: `grep -r "from app.domain.services.initial_balance_engine" app/`
   - Search imports: `grep -r "from app.domain.amt.service.initial_balance_engine" app/`
3. If both are used:
   - Rename AMT version to `AmtInitialBalanceEngine`
   - Update imports
4. If only one is used:
   - Delete the unused one
   - Update imports

**Verification**:
```bash
cd backendv2 && python -m pytest tests/ -q
# Expected: 2269 passed, 0 failed
```

**Risk**: Low (mechanical, no behavior change)

---

### 0.2 Unify Config Loading

**Files**:
- `app/infrastructure/config/config_adapter.py` (DEPRECATE)
- `app/infrastructure/config/settings.py` (KEEP)
- `app/infrastructure/config/loader.py` (NEW)

**Steps**:
1. Create `loader.py` with unified functions:
   - `_deep_merge(base, override)`
   - `_read_yaml(path)`
   - `resolve_environment()`
   - `load_settings_from_yaml(path)`
2. Copy logic from `config_adapter.py` into `loader.py`
3. Update `config_adapter.py` to re-export from `loader.py` with deprecation warnings
4. Update `settings.py` to import from `loader.py` instead of duplicating
5. Update `bootstrap/infrastructure.py` to use `loader.py`

**New file**: `app/infrastructure/config/loader.py`
```python
"""Unified configuration loading."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read YAML file safely."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def resolve_environment() -> str:
    """Resolve environment from env vars."""
    env = os.getenv("GLASSYTRADE_ENV", "development").lower()
    aliases = {"dev": "development", "prod": "production", "live": "production"}
    return aliases.get(env, env)


def load_settings_from_yaml(base_path: Path, env: str | None = None) -> dict[str, Any]:
    """Load settings from base.yaml + environment-specific override."""
    env = env or resolve_environment()
    base = _read_yaml(base_path / "base.yaml")
    override = _read_yaml(base_path / f"{env}.yaml")
    return _deep_merge(base, override)
```

**Verification**:
```bash
cd backendv2 && python -m pytest tests/unit/infrastructure/config/ -v
```

**Risk**: Low (refactoring, no behavior change)

---

### 0.3 Unify Event Taxonomy

**Files**:
- `app/runtime/pipeline/events.py` (DEPRECATE → DELETE after Phase 1)
- `app/domain/shared/event/` (KEEP, EXPAND)

**Steps**:
1. Map all event types in `runtime/pipeline/events.py`:
   - `Signal`
   - `Tick`
   - `OHLC`
   - `PositionEvent`
   - `OrderStatusEvent`
   - `ExitDecision`
   - `AMTResultEvent`
2. For each event, check if equivalent exists in `domain/shared/event/`:
   - `Signal` → `domain/shared/event/signal.py:SignalGenerated`
   - `PositionEvent` → `domain/shared/event/position.py:PositionOpened/PositionClosed`
   - `ExitDecision` → MISSING (needs to be added)
   - `Tick` → `domain/shared/event/market.py:TickReceived`
   - `OHLC` → MISSING (needs to be added)
3. Add missing events to `domain/shared/event/`:
   - Add `ExitDecision` to `domain/shared/event/position.py`
   - Add `OHLCEvent` to `domain/shared/event/market.py`
4. Update `runtime/pipeline/events.py` to re-export from `domain/shared/event/`
   - Add deprecation warnings
5. Update consumers to import from `domain/shared/event/`

**New event classes**:
```python
# domain/shared/event/position.py
@dataclass(frozen=True)
class ExitDecisionEvent(DomainEvent):
    """Emitted when an exit decision is made."""
    position_id: str
    decision: str  # "STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP", etc.
    price: float
    reason: str
    timestamp: datetime

# domain/shared/event/market.py
@dataclass(frozen=True)
class OHLCEvent(DomainEvent):
    """Emitted when a new OHLC candle is formed."""
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime
```

**Verification**:
```bash
cd backendv2 && python -m pytest tests/unit/domain/shared/event/ -v
cd backendv2 && python -m pytest tests/unit/runtime/pipeline/ -v
```

**Risk**: Medium (touches runtime pipeline)

---

### 0.4 Create LLM Adapter Base Class

**Files**:
- `app/infrastructure/adapters/mlx_inference_adapter.py` (REFACTOR)
- `app/infrastructure/adapters/gguf_inference_adapter.py` (REFACTOR)
- `app/infrastructure/adapters/llm_adapter_base.py` (NEW)

**Steps**:
1. Extract shared patterns into `llm_adapter_base.py`:
   - `BaseLLMInferenceAdapter` class
   - `_extract_json_candidate` static method
   - `wait_until_ready` polling loop
   - `ENTRY_JSON_RUNTIME_REMINDER` constant
   - Singleton management mixin
2. Update `MLXInferenceAdapter` to inherit from `BaseLLMInferenceAdapter`
3. Update `GGUFInferenceAdapter` to inherit from `BaseLLMInferenceAdapter`
4. Remove duplicate code from both adapters

**New file**: `app/infrastructure/adapters/llm_adapter_base.py`
```python
"""Base class for LLM inference adapters."""
from __future__ import annotations

import json
import logging
import time
from abc import ABC
from typing import Any

logger = logging.getLogger(__name__)

ENTRY_JSON_RUNTIME_REMINDER = (
    "Return ONLY a JSON object with 'direction' and 'confidence'."
)


class SingletonMixin:
    """Thread-safe singleton mixin."""
    _instance: Any | None = None
    _init_lock: Any | None = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            import threading
            if cls._init_lock is None:
                cls._init_lock = threading.Lock()
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance


class BaseLLMInferenceAdapter(ABC, SingletonMixin):
    """Base adapter with shared LLM inference utilities."""

    @staticmethod
    def _extract_json_candidate(text: str) -> dict[str, Any] | None:
        """Extract JSON object from text."""
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            return None

    def wait_until_ready(self, timeout: float = 300.0, poll_interval: float = 1.0) -> bool:
        """Poll until adapter is ready."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_ready():
                return True
            time.sleep(poll_interval)
        return False
```

**Verification**:
```bash
cd backendv2 && python -m pytest tests/unit/infrastructure/adapters/test_mlx_inference_adapter.py -v
cd backendv2 && python -m pytest tests/unit/infrastructure/adapters/test_gguf_inference_adapter.py -v
```

**Risk**: Low (refactoring, no behavior change)

---

### 0.5 Add Per-Symbol State Pruning

**Files**:
- `app/runtime/pipeline/risk.py` (MODIFY)
- `app/runtime/pipeline/gates.py` (MODIFY)
- `app/runtime/pipeline/orderflow.py` (MODIFY)

**Steps**:
1. Create `SymbolStateMixin` in `runtime/pipeline/base.py`:
   - `__init__(max_symbols=500, ttl_seconds=86400)`
   - `get_state(symbol)`
   - `set_state(symbol, state)`
   - `_prune()` (evict old entries)
2. Update `RiskEvaluation`, `GateEvaluation`, `OrderFlowPipeline` to inherit from `SymbolStateMixin`
3. Call `_prune()` on every Nth operation (e.g., every 100 calls)

**New mixin**: `app/runtime/pipeline/base.py`
```python
class SymbolStateMixin:
    """Mixin for pipeline stages that maintain per-symbol state."""

    def __init__(self, max_symbols: int = 500, ttl_seconds: float = 86400.0) -> None:
        self._max_symbols = max_symbols
        self._ttl_seconds = ttl_seconds
        self._state: dict[str, tuple[Any, float]] = {}
        self._call_count = 0

    def get_state(self, symbol: str) -> Any | None:
        self._prune()
        entry = self._state.get(symbol)
        if entry is None:
            return None
        state, ts = entry
        if time.monotonic() - ts > self._ttl_seconds:
            del self._state[symbol]
            return None
        return state

    def set_state(self, symbol: str, state: Any) -> None:
        self._state[symbol] = (state, time.monotonic())
        if len(self._state) > self._max_symbols:
            self._prune()

    def _prune(self) -> None:
        self._call_count += 1
        if self._call_count % 100 != 0:
            return
        now = time.monotonic()
        expired = [
            s for s, (_, ts) in self._state.items()
            if now - ts > self._ttl_seconds
        ]
        for s in expired:
            del self._state[s]
```

**Verification**:
```bash
cd backendv2 && python -m pytest tests/unit/runtime/pipeline/test_risk.py -v
cd backendv2 && python -m pytest tests/unit/runtime/pipeline/test_gates.py -v
```

**Risk**: Low (behavioral change: memory improvement)

---

## Phase 1: Canonical Value Objects (Weeks 2-3)

### Goal
Create single canonical objects for signal, VWAP, and tick context to eliminate shotgun surgery.

### Deliverables
1. **TradingSignal** value object
2. **VWAPProfile** value object
3. **TickContext** value object
4. **Refactor pipeline stages** to use canonical objects

### 1.1 Create TradingSignal Value Object

**Files**:
- `app/domain/trading/model/canonical_objects.py` (NEW)
- `app/domain/trading/model/value_objects.py` (REFERENCE)
- `app/runtime/pipeline/signal.py` (REFACTOR)
- `app/runtime/pipeline/gates.py` (REFACTOR)
- `app/runtime/pipeline/risk.py` (REFACTOR)
- `app/application/handlers/llm_entry_handler.py` (REFACTOR)
- `app/infrastructure/serialization/schemas.py` (REFACTOR)

**Steps**:
1. Create `canonical_objects.py` with `TradingSignal`
2. Include all fields currently scattered across runtime and domain:
   - `direction`, `confidence`, `grade`, `aggression_score`
   - `session_phase`, `vwap_bias`, `entry_price`, `stop_loss`, `take_profit`
   - `setup_type`, `absorption_strength`, `footprint_alignment`
3. Add factory methods:
   - `from_amt_result(amt_result)`
   - `from_llm_response(response)`
4. Refactor `runtime/pipeline/signal.py` to return `TradingSignal`
5. Refactor `runtime/pipeline/gates.py` to accept `TradingSignal`
6. Refactor `runtime/pipeline/risk.py` to accept `TradingSignal`
7. Update `llm_entry_handler.py` to build `TradingSignal`
8. Update schemas to serialize `TradingSignal`

**New file**: `app/domain/trading/model/canonical_objects.py`
```python
"""Canonical value objects passed through the pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VWAPBias(str, Enum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    AT = "AT"


class SetupType(str, Enum):
    AAA = "AAA"
    VA_FADE = "VA_FADE"
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"


@dataclass(frozen=True)
class TradingSignal:
    """Canonical signal object passed through all pipeline stages."""
    symbol: str
    direction: SignalDirection
    confidence: ConfidenceLevel
    grade: int  # 0-10
    aggression_score: float  # 0.0-5.0
    session_phase: str
    vwap_bias: VWAPBias
    entry_price: float
    stop_loss: float
    take_profit: float
    setup_type: SetupType
    absorption_strength: float = 0.0
    footprint_alignment: str = ""
    risk_reward_ratio: float = 0.0
    timestamp: datetime | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_amt_result(cls, symbol: str, amt_result: dict[str, Any]) -> TradingSignal:
        """Build signal from AMT analyzer result."""
        return cls(
            symbol=symbol,
            direction=SignalDirection(amt_result.get("direction", "NEUTRAL")),
            confidence=ConfidenceLevel(amt_result.get("confidence", "LOW")),
            grade=int(amt_result.get("grade", 0)),
            aggression_score=float(amt_result.get("aggression_score", 0.0)),
            session_phase=amt_result.get("session_phase", "UNKNOWN"),
            vwap_bias=VWAPBias(amt_result.get("vwap_bias", "AT")),
            entry_price=float(amt_result.get("entry_price", 0.0)),
            stop_loss=float(amt_result.get("stop_loss", 0.0)),
            take_profit=float(amt_result.get("take_profit", 0.0)),
            setup_type=SetupType(amt_result.get("setup_type", "AAA")),
            absorption_strength=float(amt_result.get("absorption_strength", 0.0)),
            footprint_alignment=amt_result.get("footprint_alignment", ""),
            risk_reward_ratio=float(amt_result.get("risk_reward_ratio", 0.0)),
        )

    def is_valid(self) -> bool:
        """Check if signal meets minimum validity criteria."""
        return (
            self.direction != SignalDirection.NEUTRAL
            and self.grade >= 5
            and self.risk_reward_ratio >= 1.5
            and self.entry_price > 0
        )
```

**Tests**: `tests/unit/domain/trading/model/test_canonical_objects.py`
- Test factory methods
- Test validation logic
- Test immutability

**Risk**: Medium (touches runtime pipeline)

---

### 1.2 Create VWAPProfile Value Object

**Steps**:
1. Add `VWAPProfile` and `VWAPBand` to `canonical_objects.py`
2. Refactor `vwap_service.py` to return `VWAPProfile`
3. Refactor `volume_profile.py` to use `VWAPProfile`
4. Update all 48 consumers to query `VWAPProfile` methods instead of raw fields

**New classes**:
```python
@dataclass(frozen=True)
class VWAPBand:
    sigma: int
    upper: float
    lower: float


@dataclass(frozen=True)
class VWAPProfile:
    price: float
    bands: tuple[VWAPBand, ...]
    bias: VWAPBias

    def band(self, sigma: int) -> VWAPBand | None:
        for b in self.bands:
            if b.sigma == sigma:
                return b
        return None

    def is_price_above(self, sigma: int) -> bool:
        b = self.band(sigma)
        return b is not None and self.price > b.upper

    def is_price_below(self, sigma: int) -> bool:
        b = self.band(sigma)
        return b is not None and self.price < b.lower

    def distance_from_band(self, sigma: int) -> float:
        b = self.band(sigma)
        if b is None:
            return 0.0
        if self.price > b.upper:
            return self.price - b.upper
        if self.price < b.lower:
            return b.lower - self.price
        return 0.0
```

**Risk**: Medium (touches 48 files)

---

### 1.3 Create TickContext Value Object

**Steps**:
1. Add `TickContext` to `canonical_objects.py`
2. Refactor all pipeline stages to accept/return `TickContext`
3. Each stage reads from `ctx` and writes back to `ctx`

**New class**:
```python
@dataclass
class TickContext:
    """Accumulates computed state as a tick flows through the pipeline."""
    tick: dict[str, Any]
    symbol: str
    sequence: int
    timestamp: datetime

    # Computed state (stages fill these in)
    candle: dict[str, Any] | None = None
    vwap_profile: VWAPProfile | None = None
    market_structure: dict[str, Any] | None = None
    signal: TradingSignal | None = None
    exit_decision: dict[str, Any] | None = None
    order_status: dict[str, Any] | None = None

    def with_candle(self, candle: dict[str, Any]) -> TickContext:
        return TickContext(
            tick=self.tick,
            symbol=self.symbol,
            sequence=self.sequence,
            timestamp=self.timestamp,
            candle=candle,
            vwap_profile=self.vwap_profile,
            market_structure=self.market_structure,
            signal=self.signal,
        )

    def with_signal(self, signal: TradingSignal) -> TickContext:
        return TickContext(
            tick=self.tick,
            symbol=self.symbol,
            sequence=self.sequence,
            timestamp=self.timestamp,
            candle=self.candle,
            vwap_profile=self.vwap_profile,
            market_structure=self.market_structure,
            signal=signal,
        )
```

**Risk**: High (touches all pipeline stages)

---

## Phase 2: Split God Classes (Weeks 4-5)

### Goal
Break `LLMEntryHandler` (1,072L) and `SessionRuntime` (761L) into focused, testable modules.

### 2.1 Split LLMEntryHandler

**Files**:
- `app/application/handlers/llm_entry_handler.py` (SLIM from 1,072L to ~150L)
- `app/domain/fabio_ai/services/llm_orchestrator.py` (NEW, ~200L)
- `app/domain/fabio_ai/services/llm_request_builder.py` (NEW, ~250L)
- `app/domain/fabio_ai/services/session_phase_resolver.py` (NEW, ~100L)
- `app/domain/fabio_ai/services/llm_response_normalizer.py` (NEW, ~150L)

**Steps**:
1. Extract `LLMOrchestrator`:
   - Worker thread management
   - Per-symbol queueing
   - Rate limiting
2. Extract `LLMRequestBuilder`:
   - Prompt building
   - Context assembly
   - JSON context construction
3. Extract `SessionPhaseResolver`:
   - NSE phase computation
   - MCX phase computation
   - Phase mapping
4. Extract `LLMResponseNormalizer`:
   - JSON extraction
   - Response validation
   - Normalization to `TradingSignal`
5. Slim `LLMEntryHandler` to thin orchestrator

**New file**: `app/domain/fabio_ai/services/llm_orchestrator.py`
```python
"""Orchestrates LLM inference with worker threads and rate limiting."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from app.domain.shared.port.llm_inference import ILLMInference

logger = logging.getLogger(__name__)


class LLMOrchestrator:
    """Manages per-symbol LLM request queues and worker threads."""

    def __init__(
        self,
        llm: ILLMInference,
        max_workers: int = 4,
        queue_size: int = 10,
    ) -> None:
        self._llm = llm
        self._max_workers = max_workers
        self._queues: dict[str, queue.Queue] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def enqueue(self, symbol: str, request: dict[str, Any]) -> None:
        """Queue an LLM request for a symbol."""
        with self._lock:
            if symbol not in self._queues:
                self._queues[symbol] = queue.Queue(maxsize=self._queue_size)
                self._start_worker(symbol)
            self._queues[symbol].put(request)

    def _start_worker(self, symbol: str) -> None:
        """Start a worker thread for a symbol."""
        thread = threading.Thread(
            target=self._worker_loop,
            args=(symbol,),
            daemon=True,
        )
        thread.start()
        self._threads[symbol] = thread

    def _worker_loop(self, symbol: str) -> None:
        """Process requests for a symbol."""
        q = self._queues[symbol]
        while True:
            try:
                request = q.get(timeout=1.0)
                self._process_request(request)
            except queue.Empty:
                continue

    def _process_request(self, request: dict[str, Any]) -> None:
        """Process a single LLM request."""
        prompt = request["prompt"]
        temperature = request.get("temperature", 0.4)
        response = self._llm.predict(prompt, temperature=temperature)
        callback = request.get("callback")
        if callback:
            callback(response)
```

**Tests**:
- `tests/unit/domain/fabio_ai/services/test_llm_orchestrator.py`
- `tests/unit/domain/fabio_ai/services/test_llm_request_builder.py`
- `tests/unit/domain/fabio_ai/services/test_session_phase_resolver.py`
- `tests/unit/domain/fabio_ai/services/test_llm_response_normalizer.py`

**Risk**: High (business logic extraction)

---

### 2.2 Split SessionRuntime with PipelineBuilder

**Files**:
- `app/runtime/orchestrator/session.py` (SLIM from 761L to ~200L)
- `app/runtime/pipeline/registry.py` (NEW, ~100L)
- `app/runtime/pipeline/builder.py` (NEW, ~150L)

**Steps**:
1. Create `PipelineStageRegistry`:
   - `register(name, stage)`
   - `get(name)`
   - `list_stages()`
2. Create `PipelineBuilder`:
   - `from_registry(registry, config)`
   - Returns ordered list of stages
3. Extract from `SessionRuntime`:
   - Stage instantiation → `PipelineBuilder`
   - Stage wiring → `PipelineBuilder`
   - AAA evaluation → `runtime/pipeline/aaa_evaluation.py`
   - Phase gating → `runtime/pipeline/phase_gating.py`
4. Slim `SessionRuntime` to:
   - `__init__(builder: PipelineBuilder)`
   - `run_once(ctx: TickContext)`
   - `_process_tick(tick)`

**New file**: `app/runtime/pipeline/registry.py`
```python
"""Pipeline stage plugin registry."""
from __future__ import annotations

from typing import Any

from app.runtime.pipeline.base import PipelineStageBase


class PipelineStageRegistry:
    """Registry for pipeline stages. New stages are registered here."""

    def __init__(self) -> None:
        self._stages: dict[str, PipelineStageBase] = {}

    def register(self, name: str, stage: PipelineStageBase) -> None:
        """Register a pipeline stage."""
        if name in self._stages:
            raise ValueError(f"Stage '{name}' already registered")
        self._stages[name] = stage

    def get(self, name: str) -> PipelineStageBase:
        """Get a registered stage."""
        if name not in self._stages:
            raise KeyError(f"Stage '{name}' not found")
        return self._stages[name]

    def list_stages(self) -> list[tuple[str, PipelineStageBase]]:
        """List all registered stages."""
        return list(self._stages.items())

    def build_pipeline(self, stage_names: list[str]) -> list[PipelineStageBase]:
        """Build a pipeline from a list of stage names."""
        return [self.get(name) for name in stage_names]
```

**New file**: `app/runtime/pipeline/builder.py`
```python
"""Pipeline builder with default stage ordering."""
from __future__ import annotations

from app.runtime.pipeline.registry import PipelineStageRegistry

DEFAULT_PIPELINE = [
    "sequencer",
    "normalizer",
    "candle_builder",
    "orderflow",
    "microstructure",
    "market_structure",
    "features",
    "signal_generation",
    "gate_evaluation",
    "risk_evaluation",
    "position_lifecycle",
    "execution",
    "broker_sync",
    "persistence",
]


class PipelineBuilder:
    """Builds pipeline stages from registry."""

    def __init__(self, registry: PipelineStageRegistry) -> None:
        self._registry = registry

    def build(self, stage_names: list[str] | None = None) -> list:
        """Build pipeline with specified or default stages."""
        names = stage_names or DEFAULT_PIPELINE
        return self._registry.build_pipeline(names)
```

**Risk**: High (core orchestration change)

---

## Phase 3: Layer Violations & Unified Risk (Week 6)

### 3.1 Fix Layer Violations

**Files**:
- `app/domain/exit/service/exit_engine.py` (FIX import)
- `app/application/handlers/llm_entry_handler.py` (FIX import)
- `app/application/handlers/check_exit_handler.py` (FIX import)
- `app/application/handlers/evaluate_entry_handler.py` (FIX import)
- `app/application/handlers/update_tick_handler.py` (FIX import)
- `app/runtime/pipeline/persistence.py` (FIX import)

**Steps**:
1. Move `ExitDecision` from `runtime/pipeline/events.py` to `domain/shared/event/position.py`
2. Update `exit_engine.py` to import from `domain/shared/event/position.py`
3. Move `Signal` from `runtime/pipeline/events.py` to `domain/shared/event/signal.py`
4. Update all handlers to import `Signal` from `domain/shared/event/signal.py`
5. Create `IEventBus` port in `domain/shared/port/event_bus.py`
6. Update `infrastructure/messaging/event_bus.py` to implement `IEventBus`
7. Update handlers to import `IEventBus` instead of concrete `EventBus`
8. Update `runtime/pipeline/persistence.py` to use `IStorage` port instead of `SQLiteStorageAdapter`

**New file**: `app/domain/shared/port/event_bus.py`
```python
"""Event bus port for decoupled messaging."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class IEventBus(ABC):
    """Port for event bus implementations."""

    @abstractmethod
    def publish(self, event_type: str, payload: Any) -> None:
        """Publish an event."""
        ...

    @abstractmethod
    def subscribe(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """Subscribe to an event type."""
        ...

    @abstractmethod
    def unsubscribe(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """Unsubscribe from an event type."""
        ...
```

**Risk**: Medium (import changes)

---

### 3.2 Create Unified Risk Policy

**Files**:
- `app/domain/risk/service/risk_policy.py` (NEW)
- `app/domain/risk/service/circuit_breakers.py` (REFACTOR)
- `app/domain/trading/service/risk_manager.py` (REFACTOR)
- `app/runtime/pipeline/risk.py` (REFACTOR)
- `app/domain/exit/service/loss_tracker.py` (REFACTOR)

**Steps**:
1. Create `RiskPolicy` value object with all thresholds
2. Extract hardcoded thresholds from all risk services
3. Inject `RiskPolicy` at bootstrap
4. Update all risk services to query `RiskPolicy`

**New file**: `app/domain/risk/service/risk_policy.py`
```python
"""Unified risk policy — single source of truth for all risk thresholds."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskPolicy:
    """All risk thresholds in one place. Injected at bootstrap."""
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 3
    max_concurrent_positions: int = 5
    max_portfolio_notional_pct: float = 0.60
    max_per_symbol_notional_pct: float = 0.20
    spread_blowout_threshold: float = 0.03
    hard_max_hold_seconds: float = 7200.0
    breakeven_at_r_multiple: float = 1.0
    trail_activation_r_multiple: float = 1.0
    kill_switch_drawdown_pct: float = 0.05
    session_time_stop_balanced: float = 1200.0
    session_time_stop_imbalanced: float = 1800.0
    session_time_stop_expiry: float = 600.0

    def is_daily_loss_acceptable(self, daily_loss_pct: float) -> bool:
        return daily_loss_pct < self.max_daily_loss_pct

    def is_portfolio_exposure_acceptable(
        self, portfolio_notional: float, equity: float
    ) -> bool:
        return portfolio_notional < equity * self.max_portfolio_notional_pct
```

**Risk**: Medium (behavioral change if thresholds differ)

---

## Phase 4: Repository Pattern & Adapter Splits (Week 7)

### 4.1 Extract Repository Pattern

**Files**:
- `app/infrastructure/storage/database.py` (SLIM)
- `app/infrastructure/storage/repositories/` (NEW package)

**New files**:
- `app/infrastructure/storage/repositories/base.py` — `BaseRepository`
- `app/infrastructure/storage/repositories/tick_repository.py`
- `app/infrastructure/storage/repositories/trade_repository.py`
- `app/infrastructure/storage/repositories/position_repository.py`
- `app/infrastructure/storage/repositories/session_repository.py`
- `app/infrastructure/storage/repositories/event_repository.py`

**New file**: `app/infrastructure/storage/repositories/base.py`
```python
"""Base repository with common CRUD operations."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    """Base repository with common CRUD pattern."""

    @abstractmethod
    def save(self, entity: T) -> None:
        ...

    @abstractmethod
    def get(self, id: str) -> T | None:
        ...

    @abstractmethod
    def list(self, **filters: Any) -> list[T]:
        ...

    @abstractmethod
    def delete(self, id: str) -> bool:
        ...
```

**Risk**: Medium (structural change)

---

### 4.2 Split DhanAdapter

**Files**:
- `app/infrastructure/adapters/dhan_adapter.py` (SPLIT)
- `app/infrastructure/adapters/dhan/` (NEW package)

**New files**:
- `app/infrastructure/adapters/dhan/__init__.py`
- `app/infrastructure/adapters/dhan/market_data.py` — `DhanMarketDataAdapter`
- `app/infrastructure/adapters/dhan/streaming.py` — `DhanStreamingAdapter`
- `app/infrastructure/adapters/dhan/option_chain.py` — `DhanOptionChainAdapter`
- `app/infrastructure/adapters/dhan/lot_sizes.py` — `DhanLotSizeAdapter`
- `app/infrastructure/adapters/dhan/base.py` — `DhanBaseAdapter` (shared HTTP client)

**New file**: `app/infrastructure/adapters/dhan/base.py`
```python
"""Base Dhan adapter with shared HTTP client."""
from __future__ import annotations

import httpx

_DEFAULT_BASE_URL = "https://api.dhan.co"


class DhanBaseAdapter:
    """Shared HTTP client for all Dhan adapters."""

    def __init__(
        self,
        client_id: str | None = None,
        access_token: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._client_id = client_id
        self._access_token = access_token
        self._base_url = base_url or _DEFAULT_BASE_URL
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "access-token": str(access_token or ""),
                "x-client-id": str(client_id or ""),
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()
```

**Risk**: Low (mechanical split)

---

## Phase 5: Cleanup & Final Verification (Week 8)

### 5.1 Delete Deprecated Files

**Files to delete**:
- `app/runtime/pipeline/events.py` (after all consumers migrated)
- `app/domain/services/initial_balance_engine.py` (after merge)
- `app/application/di/container.py` (after merge into bootstrap)
- `app/core/metrics_collector.py` (after merge into metrics.py)
- `app/infrastructure/config/config_adapter.py` (after deprecation period)

### 5.2 Final Verification

**Full test suite**:
```bash
cd backendv2 && python -m pytest tests/ -q --tb=short
# Expected: 2269+ passed, 0 failed
```

**Import linting**:
```bash
# Check for layer violations
grep -r "from app.runtime" app/domain/ --include="*.py"
grep -r "from app.infrastructure" app/application/ --include="*.py" | grep -v "port/"
grep -r "from app.infrastructure" app/runtime/ --include="*.py"
# Expected: 0 matches
```

**God class check**:
```bash
find app -name "*.py" -not -path "*/tests/*" -exec wc -l {} + | sort -n | tail -10
# Expected: No file >500 lines
```

---

## Dependency Graph

```
Phase 0 (Quick Wins)
├── 0.1 Merge IB Engine ──────┐
├── 0.2 Unify Config ─────────┤
├── 0.3 Unify Events ─────────┼──→ Phase 1 (Canonical Objects)
├── 0.4 LLM Base Class ───────┤      ├── 1.1 TradingSignal
└── 0.5 State Pruning ────────┘      ├── 1.2 VWAPProfile
                                      └── 1.3 TickContext
                                             │
                                             ▼
                                      Phase 2 (God Classes)
                                      ├── 2.1 Split LLMEntryHandler
                                      └── 2.2 Split SessionRuntime
                                             │
                                             ▼
                                      Phase 3 (Violations + Risk)
                                      ├── 3.1 Fix Layer Violations
                                      └── 3.2 Unified Risk Policy
                                             │
                                             ▼
                                      Phase 4 (Repositories + Adapters)
                                      ├── 4.1 Repository Pattern
                                      └── 4.2 Split DhanAdapter
                                             │
                                             ▼
                                      Phase 5 (Cleanup)
                                      ├── 5.1 Delete Deprecated
                                      └── 5.2 Final Verify
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Test regressions | Full suite run after every sub-task; never commit with failures |
| Behavioral changes | Characterization tests before refactoring; compare outputs |
| Import cycles | Import-linter pre-commit hook; CI enforcement |
| Performance regression | Benchmark tick-to-position latency before/after |
| Merge conflicts | Small, frequent PRs; one phase per PR |
| Knowledge loss | Document every new module; update CONTEXT.md |

---

## Success Metrics

| Metric | Before | After (Target) |
|--------|--------|----------------|
| God classes (>500L) | 7 | 0 |
| Layer violations | 4 | 0 |
| Global singletons | 4 | 0 |
| Files per signal change | 9 | 2 |
| Files per VWAP change | 12 | 2 |
| Files per risk threshold change | 7 | 2 |
| Duplicate class names | 5 | 0 |
| Test count | 2,269 | 2,400+ |
| Test coverage (by file) | ~58% | >70% |

---

*End of Implementation Plan*
