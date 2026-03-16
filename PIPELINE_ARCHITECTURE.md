# Modular Pluggable Pipeline Architecture
## GlassyTrade AI — Industry-Standard Design

**Version:** 1.0
**Date:** 2026-03-13
**Status:** Design Document (no code changes)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Design Principles](#2-design-principles)
3. [Core Abstractions](#3-core-abstractions)
4. [Component Taxonomy with Interface Signatures](#4-component-taxonomy-with-interface-signatures)
5. [Message and Event Schema](#5-message-and-event-schema)
6. [Pipeline Configuration Format (YAML)](#6-pipeline-configuration-format-yaml)
7. [Dependency Graph](#7-dependency-graph)
8. [Testing Strategy per Layer](#8-testing-strategy-per-layer)
9. [A/B Testing Support](#9-ab-testing-support)
10. [Migration Path from Current Codebase](#10-migration-path-from-current-codebase)
11. [Folder Structure](#11-folder-structure)
12. [Patterns Reference](#12-patterns-reference)

---

## 1. Executive Summary

The current system is functional but has a critical architectural property: its 12 concerns are wired together inside `TradingEngine`, `TradingSessionService`, and a chain of handlers that all know about each other. Swapping the Dhan adapter for a file replay source today requires touching multiple files. Running the same signal gate against two different data sources requires forking the engine.

This document designs a **Processor Pipeline** where every concern becomes an independent unit that:
- Declares exactly what message types it consumes and what it produces
- Communicates exclusively via typed channels (no direct method calls across boundaries)
- Can be replaced, duplicated, or reordered in a YAML config file without any code change
- Is independently unit-testable with a mock channel

The design draws from:
- **Apache NiFi** — Processor abstraction, FlowFile routing, typed connections
- **Hexagonal Architecture** — ports/adapters pattern (already partially present)
- **LMAX Disruptor** — ring-buffer sequencing for lock-free tick dispatch at low latency
- **Event Sourcing** — every signal, decision, and exit recorded as an immutable domain event
- **Python asyncio** — structured concurrency for pipeline stages

---

## 2. Design Principles

### P1 — One Processor, One Concern
Each processor does exactly one thing. It reads messages from an input channel, performs its transformation, and writes to an output channel. It has no knowledge of what produced its input or what consumes its output.

### P2 — Messages are the Contract
Two processors are coupled only by the schema of the message they exchange. If `MarketAnalysisProcessor` outputs `AMTResultMessage`, then any processor that replaces it only has to produce the same `AMTResultMessage`. Neither processor knows the name of the other.

### P3 — Configuration over Code Wiring
The pipeline topology — which processors exist, how they are chained, which adapters are loaded — is expressed in a YAML file. The runtime reads this config to instantiate and connect processors. Adding a notification channel means adding one entry to the YAML, not touching Python.

### P4 — Identical Results from Identical Input
Whether the data source is a live Dhan WebSocket or a recorded file replay, the signal gate and LLM processors receive identical `AMTResultMessage` objects. The pipeline is deterministic: replaying the same tick file must produce the same decisions.

### P5 — Backpressure by Design
Every channel has a bounded capacity. If a downstream processor falls behind (e.g., LLM inference is slow), the upstream processor blocks rather than accumulating unbounded state. This surfaces throughput problems at development time, not in production.

### P6 — No Shared Mutable State Across Processors
Processors communicate only through channels. A processor may maintain internal state (e.g., the candle builder's current candle under construction), but that state is private. The `SessionState` dict today crosses processor boundaries — that coupling is eliminated.

### P7 — Fail-Safe Isolation
An exception inside any processor is caught at the channel boundary. It is logged, optionally dead-lettered, and processing continues. One failing processor does not crash adjacent processors.

---

## 3. Core Abstractions

### 3.1 Message (the "FlowFile")

Every object that flows through the pipeline is a `Message`. Messages are immutable dataclasses. The body is a typed payload; the envelope carries routing metadata.

```
Message[T]
  ├── message_id: str          # UUID, for deduplication and tracing
  ├── correlation_id: str      # Ties tick → candle → signal → order
  ├── symbol: str              # e.g. "NIFTY2426525000CE"
  ├── timestamp: datetime      # When the event occurred (market time, IST)
  ├── produced_at: datetime    # When this message was created (wall clock, UTC)
  ├── source_processor: str    # Name of the processor that created it
  ├── pipeline_id: str         # Which pipeline run this belongs to
  └── payload: T               # Typed dataclass specific to message type
```

### 3.2 Channel (the "Connection")

A `Channel[T]` is a bounded async queue. Producers call `await channel.send(msg)`. Consumers call `async for msg in channel`. Every connection between two processors is represented as a channel.

```
Channel[T]
  ├── name: str                # Human-readable label for observability
  ├── capacity: int            # Bounded — enforces backpressure
  ├── message_type: type[T]    # Runtime type enforcement
  ├── send(msg: T) -> None     # Blocks when full (backpressure)
  ├── receive() -> T           # Blocks when empty
  └── __aiter__()              # Supports "async for msg in channel"
```

### 3.3 Processor (the "NiFi Processor")

Every component in the system is a `Processor`. The contract is minimal:

```
class Processor(Protocol):
    name: str
    input_types: tuple[type[Message], ...]
    output_types: tuple[type[Message], ...]

    async def setup(self, config: ProcessorConfig) -> None:
        """Called once at startup. Load models, open connections."""

    async def process(
        self,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None:
        """Main processing loop. Runs until cancelled."""

    async def teardown(self) -> None:
        """Called on graceful shutdown."""
```

`inbox` and `outbox` are dicts keyed by the channel name declared in YAML config. A processor that needs the `candles` channel reads `inbox["candles"]`. The processor has no import of any other processor class.

### 3.4 Pipeline

A `Pipeline` is an ordered collection of processors with their wired channels. The `PipelineRunner` reads the YAML config, instantiates the processors (using a registry), connects channels, and calls `asyncio.gather()` on all `processor.process()` coroutines.

```
Pipeline
  ├── id: str
  ├── processors: list[ProcessorNode]
  └── channels: list[ChannelSpec]

PipelineRunner
  ├── load_config(path: str) -> Pipeline
  ├── start() -> None           # Creates tasks, starts all processors
  ├── stop() -> None            # Cancels all tasks gracefully
  └── get_metrics() -> dict     # Channel depths, processor lag, error counts
```

### 3.5 ProcessorRegistry

A module-level dict maps string processor type names (used in YAML) to Python classes. Registration happens via decorator:

```
@register_processor("DhanIngestionProcessor")
class DhanIngestionProcessor(BaseProcessor): ...
```

This means the YAML config can reference any processor by string name. New processors are available by decorating the class — no changes to the runner.

---

## 4. Component Taxonomy with Interface Signatures

Each processor is described with its input type(s), output type(s), configuration contract, and the precise semantics of what it guarantees. This section is the binding contract — implementations must conform to it.

---

### 4.1 DATA INGESTION PROCESSORS

**Purpose:** Normalize raw broker or file data into `RawTickMessage`. This is the only place where broker-specific code lives.

---

#### `DhanIngestionProcessor`
- **Input:** None (source — produces from external WS)
- **Output:** `RawTickMessage` on channel `raw_ticks`
- **Config:**
  ```yaml
  client_id: ${DHAN_CLIENT_ID}
  access_token: ${DHAN_ACCESS_TOKEN}
  symbols: ["NIFTY2426525000CE"]
  exchange: NSE_FO
  reconnect_cooldown_secs: 5.0
  max_retries: 10
  ```
- **Guarantees:**
  - Emits one `RawTickMessage` per live tick received
  - Handles reconnect internally; emits `StreamHealthMessage` on connect/disconnect
  - Validates ltp > 0 before emitting
  - Attaches `total_buy_qty`, `total_sell_qty`, `depth_bids`, `depth_asks` when available

---

#### `FileReplayIngestionProcessor`
- **Input:** None (source — reads from file)
- **Output:** `RawTickMessage` on channel `raw_ticks`
- **Config:**
  ```yaml
  file_path: data/replay/nifty_20240115.jsonl
  speed_multiplier: 1.0          # 1.0 = real-time, 0.0 = max speed
  loop: false
  start_offset_seconds: 0
  ```
- **Guarantees:**
  - Emits ticks in chronological order
  - At `speed_multiplier: 0.0`, emits as fast as consumer can consume
  - Emits `StreamHealthMessage(status="REPLAY_COMPLETE")` on file exhaustion
  - Tick timestamps come from the file, not wall clock — ensures determinism

---

#### `SyntheticDataIngestionProcessor`
- **Input:** None (source — generates synthetic ticks)
- **Output:** `RawTickMessage` on channel `raw_ticks`
- **Config:**
  ```yaml
  symbol: NIFTY_SYNTH
  base_price: 25000.0
  volatility: 0.002
  tick_interval_ms: 100
  scenario: trending_up   # trending_up | trending_down | ranging | volatile
  ```
- **Use case:** Local development and automated testing without broker credentials

---

#### `RESTPollingIngestionProcessor`
- **Input:** None (source — polls REST API on interval)
- **Output:** `RawTickMessage` on channel `raw_ticks`
- **Config:**
  ```yaml
  endpoint: https://api.example.com/ltp
  poll_interval_secs: 1.0
  symbol_map:
    NIFTY25JANFUT: "NIFTY January Future"
  ```
- **Use case:** Fallback when WebSocket is unavailable; lower-frequency instruments

---

### 4.2 CANDLE BUILDING PROCESSOR

**Purpose:** Aggregate raw ticks into OHLCV candles at the configured interval. Emits one candle update per tick during formation; emits a `CandleClosedMessage` when the bar finalises.

---

#### `CandleBuilderProcessor`
- **Input:** `RawTickMessage` from channel `raw_ticks`
- **Output:**
  - `CandleUpdateMessage` on channel `candle_updates` (every tick, partial candle)
  - `CandleClosedMessage` on channel `closed_candles` (once per completed bar)
  - `FootprintUpdateMessage` on channel `footprint_updates` (per tick, footprint cell)
- **Config:**
  ```yaml
  interval: "5m"           # Any of: 1m, 3m, 5m, 15m, 1h, 1d
  timezone: "Asia/Kolkata"
  cumulative_vol_reset_threshold: 0.05  # 5% spike = session reset guard
  min_ltp: 0.01
  ```
- **Guarantees:**
  - `CandleClosedMessage` for a given `(symbol, bar_start)` is emitted exactly once
  - Candle start time is floor-divided to `interval` boundary in IST
  - Delta computed from `total_buy_qty - total_sell_qty`; falls back to body-ratio proxy
  - Cumulative volume spike cap prevents session-reset artefacts
  - Buy/sell cumulative reset handled: if `cum_buy < prev_cum_buy`, treat as reset
  - Output OHLC carries identical schema to current `OHLC` value object

---

### 4.3 MARKET ANALYSIS PROCESSORS

**Purpose:** Derive market structure, volume profile, CVD, and regime state from closed candles and the current partial candle. These are pure, stateless-per-call analyses.

---

#### `AMTAnalysisProcessor`
- **Input:**
  - `CandleClosedMessage` from channel `closed_candles`
  - `CandleUpdateMessage` from channel `candle_updates` (partial candle for real-time profile)
- **Output:** `AMTResultMessage` on channel `amt_results`
- **Config:**
  ```yaml
  lookback_candles: 200
  lvn_threshold: 0.40
  hvn_threshold: 0.40
  aggression_sigma: 2.5
  ema_period: 20
  profile_bins: 50
  session_vwap_reset: daily    # daily | weekly | manual
  ```
- **Guarantees:**
  - Output carries full `AMTResult` equivalent: POC, VAH, VAL, LVNs, HVNs, profile shape (P/b/D), CVD slope/divergence, session VWAP + bands, aggressive prints, market state, structure confidence, IB high/low
  - Processes only closed candles for volume profile; partial candle used for live CVD only
  - Stateful internally (history buffer, CVD tracker, profile) — not exposed to other processors

---

#### `RegimeDetectionProcessor`
- **Input:** `AMTResultMessage` from channel `amt_results`
- **Output:** `RegimeMessage` on channel `regime_updates`
- **Config:**
  ```yaml
  squeeze_threshold_atr_mult: 0.3
  second_drive_lookback: 10
  structure_change_confidence_min: 60
  ```
- **Guarantees:**
  - Detects regime changes (Balance → Trend, Trend → Reversal, etc.)
  - Tracks squeeze detection and second-drive patterns
  - Emits `RegimeMessage` on every AMT update regardless of regime change (consumers filter)
  - A `regime_changed: bool` field signals transitions that should trigger LLM re-evaluation

---

### 4.4 SIGNAL GATE PROCESSOR

**Purpose:** Apply the Three-Align gate, confirmation bundle, and volatility filter. Does not call the LLM. Returns PASS or BLOCK with a reason.

---

#### `SignalGateProcessor`
- **Input:**
  - `AMTResultMessage` from channel `amt_results`
  - `RegimeMessage` from channel `regime_updates`
- **Output:**
  - `GatePassMessage` on channel `gate_pass` — proceed to LLM
  - `GateBlockMessage` on channel `gate_block` — logged, not forwarded
- **Config:**
  ```yaml
  three_align_required: true
  confirmation_bundle_min: 2       # 2 of 3 confirmations required
  volatility_filter_atr_percentile: 40
  min_candles_before_entry: 6
  momentum_fade_lookback: 3
  ```
- **Guarantees:**
  - Stateless per call — all inputs contained in the incoming messages
  - Never calls LLM, storage, or broker
  - All gate logic is the Three-Align, confirmation-bundle, and volatility-filter functions that already exist in `entry_gate.py`
  - `GatePassMessage` carries the full `AMTResultMessage` payload plus a `gate_score: float` for logging
  - Gate results are logged to storage via dead-letter channel if blocked

---

### 4.5 LLM INFERENCE PROCESSOR

**Purpose:** Build the entry prompt from gate-passed market state, call the LLM, parse the response, and emit a typed `LLMDecisionMessage`.

---

#### `LLMEntryProcessor`
- **Input:** `GatePassMessage` from channel `gate_pass`
- **Output:**
  - `LLMDecisionMessage` on channel `llm_decisions`
  - `LLMDecisionMessage` with `action: FLAT` if model not ready, probability too low, or timeout
- **Config:**
  ```yaml
  temperature: 0.3
  max_tokens: 80
  timeout_seconds: 8.0
  probability_threshold: 0.35    # P(adverse) gate — LightGBM first-passage model
  min_gap_between_entries_secs: 30
  llm_adapter: MLXInferenceAdapter   # Swappable via registry
  probability_adapter: LGBMProbabilityAdapter
  ```
- **Guarantees:**
  - Prompt building uses `prompt_builder.build_entry_prompt()` — no inline prompt construction
  - LLM call runs in `asyncio.to_thread()` (not blocking event loop)
  - Timeout handled via `ThreadPoolExecutor` + `future.result(timeout=N)` inside thread
  - Probability engine check happens before LLM call — P < threshold short-circuits to FLAT
  - Every call result (including FLAT with reason) is emitted on `llm_decisions`
  - `correlation_id` threads through from original tick to decision

---

### 4.6 OVERSEER PROCESSOR

**Purpose:** Monitor open positions every N seconds. Ask the LLM whether to HOLD, TIGHTEN_SL, PARTIAL_EXIT, FULL_EXIT, or ADD.

---

#### `OverseerProcessor`
- **Input:**
  - `LLMDecisionMessage` from channel `llm_decisions` — signals entry (activates overseer for that position)
  - `AMTResultMessage` from channel `amt_results` — continuous market context
  - `PositionOpenedMessage` from channel `position_events` — alternative trigger
  - `PositionClosedMessage` from channel `position_events` — deactivates overseer for position
- **Output:**
  - `OverseerActionMessage` on channel `overseer_actions`
- **Config:**
  ```yaml
  cooldown_secs: 3.0
  add_cooldown_secs: 120.0
  max_adds_per_position: 2
  timeout_seconds: 8.0
  probability_adverse_exit_threshold: 0.65
  llm_adapter: MLXInferenceAdapter
  ```
- **Guarantees:**
  - Only active when there are open positions
  - ADD rate-limited: cooldown + max-adds guard enforced internally
  - Probability engine can override HOLD → FULL_EXIT independently of LLM
  - All actions logged to storage via the persistence channel
  - Separate internal timer task drives periodic check; not triggered on every tick

---

### 4.7 RISK MANAGEMENT PROCESSOR

**Purpose:** Take an LLM decision or overseer action and compute exact SL, TP, and size. Apply session risk tier constraints. Output a risk-validated order intent.

---

#### `RiskManagementProcessor`
- **Input:**
  - `LLMDecisionMessage` from channel `llm_decisions`
  - `OverseerActionMessage` from channel `overseer_actions`
  - `AMTResultMessage` from channel `amt_results` (for ATR-based SL floor)
- **Output:**
  - `OrderIntentMessage` on channel `order_intents`
  - `RiskRejectedMessage` on channel `risk_rejected` (can_trade = false, max trades, etc.)
- **Config:**
  ```yaml
  min_sl_atr_multiple: 1.5
  min_sl_pct: 0.005
  max_sl_pct: 0.03
  default_position_size: 1
  session_max_trades: 5
  max_profit_risk_pct: 0.30
  ```
- **Guarantees:**
  - SL floor: `max(min_sl_pct * price, ATR(14) * min_sl_atr_multiple)`
  - Position sizing derived from cushion tier (SessionRiskManager) — CONSERVATIVE, NORMAL, CUSHION, MOMENTUM, DEFENSIVE
  - `can_trade` check happens first; if false emits `RiskRejectedMessage` immediately
  - Never calls LLM, broker, or storage

---

### 4.8 ORDER EXECUTION PROCESSOR

**Purpose:** Submit the order to the broker. Map the abstract `OrderIntentMessage` to broker-specific API call. Emit execution confirmation or rejection.

---

#### `PaperExecutionProcessor`
- **Input:** `OrderIntentMessage` from channel `order_intents`
- **Output:**
  - `OrderFilledMessage` on channel `order_fills`
  - `OrderRejectedMessage` on channel `order_fills` (on simulated rejection)
- **Config:**
  ```yaml
  fill_at_price: ltp    # ltp | mid | worst
  simulated_slippage_bps: 2
  ```

---

#### `DhanExecutionProcessor`
- **Input:** `OrderIntentMessage` from channel `order_intents`
- **Output:**
  - `OrderFilledMessage` on channel `order_fills`
  - `OrderRejectedMessage` on channel `order_fills`
- **Config:**
  ```yaml
  client_id: ${DHAN_CLIENT_ID}
  access_token: ${DHAN_ACCESS_TOKEN}
  order_type: MARKET
  product_type: INTRADAY
  ```
- **Guarantees:**
  - Idempotency key derived from `correlation_id` — duplicate fills are deduplicated by broker API contract check
  - All fills persisted via persistence channel before emitting

---

### 4.9 STATE PERSISTENCE PROCESSOR

**Purpose:** Consume messages from any processor and write them to durable storage. Decoupled from the main pipeline — runs asynchronously on a separate bounded queue (current `AsyncPersistenceBus` pattern).

---

#### `PersistenceProcessor`
- **Input:** `PersistMessage` on channel `persist_queue` (fan-in from all processors that need to write)
- **Output:** None (sink)
- **Config:**
  ```yaml
  adapter: SQLiteStorageAdapter
  db_path: glassytrade.db
  batch_size: 50
  flush_interval_secs: 1.0
  write_candles: true
  write_trades: true
  write_decisions: true
  write_position_events: true
  ```
- **Guarantees:**
  - All writes are async — main pipeline never blocks on storage I/O
  - On shutdown, flushes remaining queue before closing
  - Write failures are logged and retried once; then dead-lettered (not dropped silently)

---

### 4.10 FRONTEND STREAMING PROCESSOR

**Purpose:** Aggregate state from multiple upstream channels and publish a composite snapshot to WebSocket viewers. Read-only — never modifies state.

---

#### `FrontendStreamingProcessor`
- **Input:**
  - `CandleUpdateMessage` from channel `candle_updates`
  - `AMTResultMessage` from channel `amt_results`
  - `LLMDecisionMessage` from channel `llm_decisions`
  - `OverseerActionMessage` from channel `overseer_actions`
  - `OrderFilledMessage` from channel `order_fills`
  - `PortfolioSnapshotMessage` from channel `portfolio_snapshots`
- **Output:** `FrontendStateMessage` on channel `frontend_state`
- **Config:**
  ```yaml
  publish_interval_ms: 150     # Minimum ms between state pushes
  symbols: ["NIFTY2426525000CE"]
  ```
- **Guarantees:**
  - Generation counter incremented on every publish (current viewer-notification pattern preserved)
  - Viewers poll via `wait_for_update(known_gen)` — unchanged interface
  - Never touches broker, LLM, or storage
  - Serializes to camelCase DTOs before publishing (current `schemas.py` behaviour preserved)

---

### 4.11 NOTIFICATION PROCESSORS

**Purpose:** Send human-readable notifications on trade events.

---

#### `TelegramNotificationProcessor`
- **Input:** `NotificationMessage` on channel `notifications`
- **Output:** None (sink)
- **Config:**
  ```yaml
  bot_token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
  rate_limit_per_minute: 10
  ```

---

#### `NullNotificationProcessor`
- **Input:** `NotificationMessage` on channel `notifications`
- **Output:** None (sink)
- **Config:** None
- **Use case:** Default when no TELEGRAM_BOT_TOKEN is set

---

### 4.12 SCANNER PROCESSOR

**Purpose:** Score the option chain and select the optimal contract for the current regime. Outputs a symbol recommendation that the Ingestion Processor uses to subscribe.

---

#### `OptionScannerProcessor`
- **Input:**
  - `RegimeMessage` from channel `regime_updates`
  - `ScanRequestMessage` on channel `scan_requests` (manual or scheduled trigger)
- **Output:**
  - `ScanResultMessage` on channel `scan_results`
- **Config:**
  ```yaml
  underlying: NIFTY
  exchange: NSE_FO
  max_premium: 1500
  max_spread_pct: 1.5
  min_oi_multiplier: 0.02
  prefer_itm_strikes: 1
  rescan_on_regime_change: true
  ```
- **Guarantees:**
  - Pure scoring — no side effects
  - `ScanResultMessage` contains recommended symbol, strike, expiry, score, and bias
  - Pipeline can wire `ScanResultMessage` into `DhanIngestionProcessor`'s dynamic symbol subscription

---

## 5. Message and Event Schema

All messages extend a common envelope. Payloads are frozen dataclasses. Every field that enters or leaves a processor must be represented in a message schema — no `dict` payloads.

### 5.1 Message Envelope

```python
@dataclass(frozen=True)
class MessageEnvelope:
    message_id: str           # UUID4
    correlation_id: str       # UUID4 — ties a tick to its resulting order
    symbol: str
    timestamp: datetime       # Market event time (IST)
    produced_at: datetime     # Wall clock creation time (UTC)
    source_processor: str     # Processor.name that created this
    pipeline_id: str          # Identifies which pipeline run
```

### 5.2 RawTickMessage

```python
@dataclass(frozen=True)
class RawTickPayload:
    ltp: float
    volume: int                    # Cumulative session volume
    total_buy_qty: int             # Cumulative session buy quantity
    total_sell_qty: int            # Cumulative session sell quantity
    ltq: int                       # Last trade quantity
    oi: int                        # Open interest
    depth_bids: tuple[DepthLevel, ...]   # Up to 20 levels
    depth_asks: tuple[DepthLevel, ...]
    exchange_timestamp: datetime | None

@dataclass(frozen=True)
class DepthLevel:
    price: float
    qty: int

RawTickMessage = Message[RawTickPayload]
```

### 5.3 CandleUpdateMessage

```python
@dataclass(frozen=True)
class CandlePayload:
    bar_start: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    delta: Decimal
    vwap: Decimal
    taker_buy_volume: Decimal
    buy_volume: Decimal
    sell_volume: Decimal
    is_closed: bool          # True when bar is finalised

CandleUpdateMessage = Message[CandlePayload]    # is_closed=False
CandleClosedMessage = Message[CandlePayload]    # is_closed=True
```

### 5.4 FootprintUpdateMessage

```python
@dataclass(frozen=True)
class FootprintCell:
    price_level: float
    bar_start: datetime
    buy_vol: float
    sell_vol: float
    delta: float
    absorption_detected: bool
    contested: bool

FootprintUpdateMessage = Message[FootprintCell]
```

### 5.5 AMTResultMessage

```python
@dataclass(frozen=True)
class AMTResultPayload:
    market_state: str
    poc: float
    value_area_high: float
    value_area_low: float
    lvns: tuple[float, ...]
    hvns: tuple[float, ...]
    aggression: float
    profile_shape: str          # "P" | "b" | "D"
    cvd_slope: float
    cvd_divergence: str         # "BULLISH_DIV" | "BEARISH_DIV" | ""
    session_vwap: float
    vwap_upper_1: float
    vwap_lower_1: float
    vwap_upper_2: float
    vwap_lower_2: float
    balance_ratio: float
    market_structure: str       # "BALANCE" | "TREND" | "BREAKOUT" | ...
    structure_confidence: int
    day_type: str
    ib_high: float
    ib_low: float
    ib_complete: bool
    prior_poc: float
    prior_vah: float
    prior_val: float
    gap_type: str
    opening_bias: str
    break_direction: str
    break_type: str
    break_level: float
    poc_signal: str
    lvn_play: dict | None
    ofi: float
    dev_poc: float
    dev_vah: float
    dev_val: float
    aggressive_prints: tuple[AggressivePrintData, ...]
    cushion_tier: str
    session_pnl: float
    latest_candle: CandlePayload

AMTResultMessage = Message[AMTResultPayload]
```

### 5.6 RegimeMessage

```python
@dataclass(frozen=True)
class RegimePayload:
    regime: str                  # "BALANCE" | "TREND" | "REVERSAL" | "SQUEEZE"
    regime_changed: bool         # True only on transition
    previous_regime: str | None
    squeeze_active: bool
    second_drive_detected: bool
    structure_confidence: int
    session_info: dict           # Session name, bias, volatility context

RegimeMessage = Message[RegimePayload]
```

### 5.7 GatePassMessage / GateBlockMessage

```python
@dataclass(frozen=True)
class GateResultPayload:
    passed: bool
    gate_score: float                    # Confluence score 0.0–1.0
    three_align_result: bool
    confirmation_count: int              # How many of 3 confirmations passed
    volatility_filter_result: bool
    block_reason: str | None             # Populated if passed=False
    amt_snapshot: AMTResultPayload       # Full market state at gate time
    regime_snapshot: RegimePayload

GatePassMessage = Message[GateResultPayload]    # passed=True
GateBlockMessage = Message[GateResultPayload]   # passed=False
```

### 5.8 LLMDecisionMessage

```python
@dataclass(frozen=True)
class LLMDecisionPayload:
    action: str                  # "LONG" | "SHORT" | "FLAT"
    direction: str               # "BUY" | "SELL" | "NONE"
    confidence: float            # 0.0–1.0 from LLM response
    rationale: str               # Raw LLM output excerpt
    setup_grade: str             # "A" | "B" | "C" | ""
    entry_price: float           # Suggested entry (LTP at decision time)
    probability_adverse: float   # P(adverse) from LightGBM
    gate_score: float            # From upstream GatePassMessage
    latency_us: int              # LLM inference latency in microseconds
    model_name: str              # Which LLM adapter produced this
    raw_prompt_hash: str         # SHA256 of prompt — reproducibility audit
    flat_reason: str | None      # "PROBABILITY_TOO_LOW" | "TIMEOUT" | "LLM_NOT_READY" | None

LLMDecisionMessage = Message[LLMDecisionPayload]
```

### 5.9 OverseerActionMessage

```python
@dataclass(frozen=True)
class OverseerActionPayload:
    action: str                  # "HOLD" | "TIGHTEN_SL" | "PARTIAL_EXIT" | "FULL_EXIT" | "ADD"
    position_id: str
    new_sl: float | None
    exit_fraction: float | None  # 0.5 for partial
    rationale: str
    probability_adverse: float
    override_reason: str | None  # "PROBABILITY_OVERRIDE" if P > threshold

OverseerActionMessage = Message[OverseerActionPayload]
```

### 5.10 OrderIntentMessage

```python
@dataclass(frozen=True)
class OrderIntentPayload:
    intent_type: str             # "OPEN" | "CLOSE" | "MODIFY_SL" | "PARTIAL_CLOSE"
    side: str                    # "BUY" | "SELL"
    symbol: str
    size: int
    entry_price: float
    stop_loss: float
    take_profit: float
    sl_pct: float
    tp_pct: float
    risk_tier: str               # From SessionRiskManager
    setup_grade: str
    source: str                  # "LLM_ENTRY" | "OVERSEER" | "WATCHDOG"

OrderIntentMessage = Message[OrderIntentPayload]
```

### 5.11 OrderFilledMessage / OrderRejectedMessage

```python
@dataclass(frozen=True)
class OrderFillPayload:
    order_id: str                # Broker-assigned
    position_id: str             # Internal position UUID
    side: str
    fill_price: float
    fill_qty: int
    commission: float
    slippage_bps: float
    broker: str                  # "DHAN" | "PAPER" | ...

OrderFilledMessage = Message[OrderFillPayload]

@dataclass(frozen=True)
class OrderRejectPayload:
    reason: str
    error_code: str | None

OrderRejectedMessage = Message[OrderRejectPayload]
```

### 5.12 StreamHealthMessage

```python
@dataclass(frozen=True)
class StreamHealthPayload:
    status: str                  # "CONNECTED" | "DISCONNECTED" | "STALE" | "REPLAY_COMPLETE"
    consecutive_failures: int
    last_tick_age_secs: float

StreamHealthMessage = Message[StreamHealthPayload]
```

### 5.13 PortfolioSnapshotMessage

```python
@dataclass(frozen=True)
class PositionData:
    position_id: str
    symbol: str
    side: str
    size: int
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    unrealised_pnl: float
    source: str

@dataclass(frozen=True)
class PortfolioSnapshotPayload:
    open_positions: tuple[PositionData, ...]
    session_pnl: float
    total_trades: int
    win_rate: float
    profit_factor: float
    risk_tier: str

PortfolioSnapshotMessage = Message[PortfolioSnapshotPayload]
```

### 5.14 NotificationMessage

```python
@dataclass(frozen=True)
class NotificationPayload:
    level: str                   # "INFO" | "TRADE" | "ALERT" | "ERROR"
    title: str
    body: str
    trade_data: dict | None      # Structured trade summary if level="TRADE"

NotificationMessage = Message[NotificationPayload]
```

### 5.15 ScanResultMessage

```python
@dataclass(frozen=True)
class ScanResultPayload:
    recommended_symbol: str
    underlying: str
    strike: int
    option_type: str             # "CE" | "PE"
    expiry: str
    score: float
    bias: str                    # "BULLISH" | "BEARISH" | "NEUTRAL"
    ltp: float
    spread: float
    oi: int

ScanResultMessage = Message[ScanResultPayload]
```

---

## 6. Pipeline Configuration Format (YAML)

The YAML config is the single source of truth for pipeline topology. No Python code changes are needed to rewire the pipeline.

### 6.1 Full Production Config

```yaml
# pipeline_production.yaml
pipeline:
  id: production-v1
  description: "Live trading — Dhan WS, MLX LLM, SQLite storage"

channels:
  # All channels are bounded async queues.
  # capacity governs backpressure. Tune based on throughput profile.
  - name: raw_ticks
    capacity: 1000
    type: RawTickMessage

  - name: candle_updates
    capacity: 500
    type: CandleUpdateMessage

  - name: closed_candles
    capacity: 200
    type: CandleClosedMessage

  - name: footprint_updates
    capacity: 500
    type: FootprintUpdateMessage

  - name: amt_results
    capacity: 100
    type: AMTResultMessage

  - name: regime_updates
    capacity: 100
    type: RegimeMessage

  - name: gate_pass
    capacity: 50
    type: GatePassMessage

  - name: gate_block
    capacity: 200
    type: GateBlockMessage

  - name: llm_decisions
    capacity: 50
    type: LLMDecisionMessage

  - name: overseer_actions
    capacity: 50
    type: OverseerActionMessage

  - name: order_intents
    capacity: 50
    type: OrderIntentMessage

  - name: risk_rejected
    capacity: 100
    type: RiskRejectedMessage

  - name: order_fills
    capacity: 100
    type: OrderFilledMessage

  - name: portfolio_snapshots
    capacity: 50
    type: PortfolioSnapshotMessage

  - name: position_events
    capacity: 100
    type: PositionEventMessage

  - name: frontend_state
    capacity: 100
    type: FrontendStateMessage

  - name: notifications
    capacity: 200
    type: NotificationMessage

  - name: persist_queue
    capacity: 5000
    type: PersistMessage

  - name: scan_results
    capacity: 20
    type: ScanResultMessage

  - name: scan_requests
    capacity: 10
    type: ScanRequestMessage

  - name: stream_health
    capacity: 50
    type: StreamHealthMessage

processors:
  - id: ingestion
    type: DhanIngestionProcessor
    inbox: {}
    outbox:
      raw_ticks: raw_ticks
      stream_health: stream_health
    config:
      client_id: ${DHAN_CLIENT_ID}
      access_token: ${DHAN_ACCESS_TOKEN}
      symbols:
        - NIFTY2426525000CE
        - NIFTY2426524950PE
      exchange: NSE_FO
      reconnect_cooldown_secs: 5.0
      max_retries: 10

  - id: candle_builder
    type: CandleBuilderProcessor
    inbox:
      raw_ticks: raw_ticks
    outbox:
      candle_updates: candle_updates
      closed_candles: closed_candles
      footprint_updates: footprint_updates
    config:
      interval: "5m"
      timezone: "Asia/Kolkata"
      cumulative_vol_reset_threshold: 0.05

  - id: amt_analysis
    type: AMTAnalysisProcessor
    inbox:
      closed_candles: closed_candles
      candle_updates: candle_updates
    outbox:
      amt_results: amt_results
    config:
      lookback_candles: 200
      lvn_threshold: 0.40
      hvn_threshold: 0.40
      aggression_sigma: 2.5
      ema_period: 20

  - id: regime_detection
    type: RegimeDetectionProcessor
    inbox:
      amt_results: amt_results
    outbox:
      regime_updates: regime_updates
    config:
      squeeze_threshold_atr_mult: 0.3
      second_drive_lookback: 10

  - id: signal_gate
    type: SignalGateProcessor
    inbox:
      amt_results: amt_results
      regime_updates: regime_updates
    outbox:
      gate_pass: gate_pass
      gate_block: gate_block
    config:
      three_align_required: true
      confirmation_bundle_min: 2
      volatility_filter_atr_percentile: 40
      min_candles_before_entry: 6

  - id: llm_entry
    type: LLMEntryProcessor
    inbox:
      gate_pass: gate_pass
    outbox:
      llm_decisions: llm_decisions
    config:
      temperature: 0.3
      max_tokens: 80
      timeout_seconds: 8.0
      probability_threshold: 0.35
      min_gap_between_entries_secs: 30
      llm_adapter: MLXInferenceAdapter
      llm_model_path: poc3/models/glassytrade-options-fused/
      probability_adapter: LGBMProbabilityAdapter
      probability_model_dir: backend/models/

  - id: overseer
    type: OverseerProcessor
    inbox:
      llm_decisions: llm_decisions
      amt_results: amt_results
      position_events: position_events
    outbox:
      overseer_actions: overseer_actions
    config:
      cooldown_secs: 3.0
      add_cooldown_secs: 120.0
      max_adds_per_position: 2
      timeout_seconds: 8.0
      probability_adverse_exit_threshold: 0.65
      llm_adapter: MLXInferenceAdapter

  - id: risk_manager
    type: RiskManagementProcessor
    inbox:
      llm_decisions: llm_decisions
      overseer_actions: overseer_actions
      amt_results: amt_results
    outbox:
      order_intents: order_intents
      risk_rejected: risk_rejected
      portfolio_snapshots: portfolio_snapshots
    config:
      min_sl_atr_multiple: 1.5
      min_sl_pct: 0.005
      max_sl_pct: 0.03
      default_position_size: 1
      session_max_trades: 5
      max_profit_risk_pct: 0.30

  - id: execution
    type: PaperExecutionProcessor
    inbox:
      order_intents: order_intents
    outbox:
      order_fills: order_fills
      position_events: position_events
    config:
      fill_at_price: ltp
      simulated_slippage_bps: 2

  - id: persistence
    type: PersistenceProcessor
    inbox:
      persist_queue: persist_queue
    outbox: {}
    config:
      adapter: SQLiteStorageAdapter
      db_path: glassytrade.db
      batch_size: 50
      flush_interval_secs: 1.0

  - id: frontend_streaming
    type: FrontendStreamingProcessor
    inbox:
      candle_updates: candle_updates
      amt_results: amt_results
      llm_decisions: llm_decisions
      overseer_actions: overseer_actions
      order_fills: order_fills
      portfolio_snapshots: portfolio_snapshots
    outbox:
      frontend_state: frontend_state
    config:
      publish_interval_ms: 150

  - id: notifications
    type: TelegramNotificationProcessor
    inbox:
      notifications: notifications
    outbox: {}
    config:
      bot_token: ${TELEGRAM_BOT_TOKEN}
      chat_id: ${TELEGRAM_CHAT_ID}
      rate_limit_per_minute: 10

  - id: option_scanner
    type: OptionScannerProcessor
    inbox:
      regime_updates: regime_updates
      scan_requests: scan_requests
    outbox:
      scan_results: scan_results
    config:
      underlying: NIFTY
      exchange: NSE_FO
      max_premium: 1500
      max_spread_pct: 1.5
      rescan_on_regime_change: true
```

### 6.2 File Replay Config (Backtesting)

```yaml
# pipeline_replay.yaml
# Identical analysis chain — only ingestion processor changes.
pipeline:
  id: replay-v1
  description: "File replay — deterministic backtest"

# All channels identical to production

processors:
  - id: ingestion
    type: FileReplayIngestionProcessor    # Only this line changes
    inbox: {}
    outbox:
      raw_ticks: raw_ticks
      stream_health: stream_health
    config:
      file_path: data/replay/nifty_20240115.jsonl
      speed_multiplier: 0.0          # Max speed
      loop: false

  # All remaining processors copied verbatim from production config
  # ... (candle_builder, amt_analysis, signal_gate, llm_entry, etc.)
```

### 6.3 A/B Test Config

```yaml
# pipeline_ab_test.yaml
# Two signal gates run in parallel on the same AMT data.
# Results are compared by a dedicated A/B collector processor.

channels:
  - name: gate_pass_control
    capacity: 50
    type: GatePassMessage
  - name: gate_pass_treatment
    capacity: 50
    type: GatePassMessage
  - name: ab_results
    capacity: 200
    type: ABComparisonMessage

processors:
  # ... ingestion, candle_builder, amt_analysis, regime_detection same as production ...

  - id: signal_gate_control
    type: SignalGateProcessor
    inbox:
      amt_results: amt_results
      regime_updates: regime_updates
    outbox:
      gate_pass: gate_pass_control
      gate_block: gate_block
    config:
      three_align_required: true
      confirmation_bundle_min: 2

  - id: signal_gate_treatment
    type: SignalGateProcessor
    inbox:
      amt_results: amt_results         # Same input channel — both read independently
      regime_updates: regime_updates
    outbox:
      gate_pass: gate_pass_treatment
      gate_block: gate_block
    config:
      three_align_required: true
      confirmation_bundle_min: 3       # Treatment: stricter bundle

  - id: ab_collector
    type: ABCollectorProcessor
    inbox:
      control: gate_pass_control
      treatment: gate_pass_treatment
    outbox:
      ab_results: ab_results
    config:
      track_metric: gate_score
      window_minutes: 60
```

Note: For A/B testing where both variants drive execution, use a `TrafficSplitterProcessor` that routes each tick to one variant deterministically (e.g., by minute parity). Both variants write to separate `order_fills` channels for comparison.

---

## 7. Dependency Graph

### 7.1 Allowed Call Directions

The following shows what can know about what. The arrows point in the only permitted dependency direction. If A → B, A may import B's message types. A may never import B's processor implementation.

```
INFRASTRUCTURE LAYER (Adapters)
    DhanIngestionProcessor
    FileReplayIngestionProcessor
    SyntheticDataIngestionProcessor
    MLXInferenceAdapter
    LGBMProbabilityAdapter
    SQLiteStorageAdapter
    TelegramNotificationProcessor
    DhanExecutionProcessor
    PaperExecutionProcessor
            │
            ▼  (adapters implement ports; processors emit/consume messages)
APPLICATION LAYER (Processors & Orchestration)
    CandleBuilderProcessor
    AMTAnalysisProcessor
    RegimeDetectionProcessor
    SignalGateProcessor
    LLMEntryProcessor
    OverseerProcessor
    RiskManagementProcessor
    FrontendStreamingProcessor
    PersistenceProcessor
    OptionScannerProcessor
    PipelineRunner
            │
            ▼  (processors use domain services; never the reverse)
DOMAIN LAYER (Pure Logic — no asyncio, no I/O)
    AMTAnalyzer (domain service)
    EntryGate (three_align_check, confirmation_bundle, etc.)
    PromptBuilder (build_entry_prompt, parse_entry_response)
    RegimeDetector (domain service)
    SessionRiskManager (domain service)
    TradeManager (domain service)
    CVDTracker (domain service)
    ProfileClassifier (domain service)
    MarketStructureClassifier (domain service)
    OptionScannerService (domain service)
    RiskManager (domain service)
            │
            ▼  (domain uses value objects and ports)
DOMAIN PORTS (Abstract Interfaces — no implementation)
    LLMInferencePort
    ProbabilityInferencePort
    StoragePort sub-ports
    BrokerPort
    NotificationPort
    MarketDataPort
            │
            ▼  (ports define message value objects)
MESSAGE SCHEMAS (Immutable dataclasses)
    All Message[T] types defined in Section 5
    All domain value objects (OHLC, AMTResult, OrderBook, etc.)
```

### 7.2 Strict Rules

1. **Domain layer has zero imports from application or infrastructure.** This is already partially true — `entry_gate.py` and `prompt_builder.py` are pure functions. The remaining coupling in `TradingSessionService` is eliminated by the processor model.

2. **Processors never import each other.** `LLMEntryProcessor` does not import `SignalGateProcessor`. It only imports `GatePassMessage` from the message schemas module.

3. **Infrastructure adapters implement domain ports.** `MLXInferenceAdapter` implements `LLMInferencePort`. It never calls an application-layer processor.

4. **Message schemas have no business logic.** They are frozen dataclasses with typed fields only. Validation lives in the processor that produces them.

5. **The `PipelineRunner` is the only place that wires processors to channels.** It reads the YAML config and performs the wiring. No processor knows the identity of its upstream or downstream processor.

### 7.3 Data Flow Diagram

```
[DhanIngestionProcessor] ──raw_ticks──► [CandleBuilderProcessor]
                                                │
                                    ┌───────────┼────────────────────┐
                                    │           │                    │
                             candle_updates  closed_candles   footprint_updates
                                    │           │
                                    └───────────┴──► [AMTAnalysisProcessor]
                                                              │
                                                          amt_results
                                                         ┌────┴────┐
                                                         │         │
                                              [RegimeDetector]  [FrontendStreaming]
                                                         │
                                                   regime_updates
                                                         │
                                              [SignalGateProcessor]
                                                    │         │
                                               gate_pass  gate_block (dead letter)
                                                    │
                                          [LLMEntryProcessor]
                                                    │
                                              llm_decisions
                                           ┌────────┴────────┐
                                           │                 │
                                    [OverseerProcessor]  [RiskManagement]
                                           │                 │
                                    overseer_actions   order_intents
                                                             │
                                                  [ExecutionProcessor]
                                                             │
                                                        order_fills
                                                             │
                                                  ─────────────────────
                                                  Notifications, Storage,
                                                  Frontend (all fan-out)
```

---

## 8. Testing Strategy per Layer

### 8.1 Message Schema Tests (pytest, zero mocks)

Test that every message can be constructed, serialised to dict, and round-tripped. Test that frozen fields prevent mutation. Test all `DepthLevel`, `CandlePayload`, `AMTResultPayload` edge cases (zero volume, NaN guard, negative delta).

Location: `tests/messages/test_*.py`

No mocks needed — schemas are pure data.

### 8.2 Domain Service Tests (pytest, zero mocks)

Test each domain service in complete isolation. Every function in `entry_gate.py`, `prompt_builder.py`, `regime_detector.py`, `session_risk_manager.py`, `amt_analyzer.py`, `cvd_tracker.py` is already tested this way. The new architecture enforces this by making it impossible to construct a domain service that depends on an external I/O port — domain services accept only value objects.

Location: `tests/domain/test_*.py`

Pattern:
```python
def test_three_align_gate_blocks_on_balance():
    amt = build_test_amt_result(market_state="BALANCE")
    result = three_align_check(amt)
    assert result.passed is False
    assert "BALANCE" in result.block_reason
```

### 8.3 Processor Unit Tests (pytest + async, mock channels)

Each processor is tested by feeding messages into a fake input channel and asserting on the output channel. The test does not start a real pipeline.

Location: `tests/processors/test_*.py`

Pattern:
```python
async def test_candle_builder_emits_closed_candle_on_bar_boundary():
    inbox = {"raw_ticks": FakeChannel([tick_at_09_15, tick_at_09_20])}
    outbox = {"closed_candles": CollectingChannel(), "candle_updates": CollectingChannel()}

    processor = CandleBuilderProcessor()
    await processor.setup(CandleBuilderConfig(interval="5m"))
    await processor.process(inbox, outbox)

    closed = outbox["closed_candles"].received
    assert len(closed) == 1
    assert closed[0].payload.is_closed is True
    assert closed[0].payload.bar_start == datetime(2024, 1, 15, 9, 15, tzinfo=IST)
```

`FakeChannel` is a test double that yields pre-loaded messages then raises `StopAsyncIteration`. `CollectingChannel` accumulates all messages sent to it. Both are tiny test utilities in `tests/utils/channels.py`.

### 8.4 Pipeline Integration Tests (pytest + async, real channels, mock adapters)

Wire two or three processors together using real `Channel` instances. Use mock infrastructure adapters (mock LLM returns a canned LONG response, mock storage discards writes).

Location: `tests/integration/test_pipeline_segments.py`

Pattern:
```python
async def test_signal_gate_to_llm_decision_roundtrip():
    # Wire: SignalGateProcessor → LLMEntryProcessor
    gate_pass_channel = Channel("gate_pass", capacity=10)
    decision_channel = Channel("llm_decisions", capacity=10)

    gate = SignalGateProcessor()
    llm = LLMEntryProcessor()
    await llm.setup(LLMEntryConfig(llm_adapter="MockLLMAdapter"))

    # Inject a passing market state
    await gate_pass_channel.send(build_passing_gate_message())

    async with asyncio.TaskGroup() as tg:
        tg.create_task(llm.process({"gate_pass": gate_pass_channel}, {"llm_decisions": decision_channel}))

    decision = await asyncio.wait_for(decision_channel.receive(), timeout=2.0)
    assert decision.payload.action in ("LONG", "SHORT", "FLAT")
```

### 8.5 Pipeline Topology Tests (no I/O, config validation)

Parse the YAML config and verify:
- Every channel referenced by a processor exists in the channel list
- No channel is written by more than one processor (unless intentional fan-in)
- Every processor type name resolves in the registry
- No circular processor dependencies

Location: `tests/config/test_pipeline_config.py`

This is a static analysis test — it verifies the YAML structure before runtime.

### 8.6 Determinism Tests (replay vs live equivalence)

Load a recorded tick file. Run the full pipeline with `FileReplayIngestionProcessor`. Capture every `LLMDecisionMessage`. Run again. Assert identical decisions.

Location: `tests/determinism/test_replay_determinism.py`

This test validates Principle P4 — same input produces same output regardless of data source.

### 8.7 Performance Baseline Tests (throughput and latency)

Measure the per-processor latency budget:

| Processor              | Target latency | Acceptable max |
|------------------------|----------------|----------------|
| CandleBuilder          | < 0.5ms        | 2ms            |
| AMTAnalysisProcessor   | < 10ms         | 30ms           |
| SignalGateProcessor    | < 1ms          | 5ms            |
| LLMEntryProcessor      | < 500ms        | 2000ms         |
| RiskManagementProcessor| < 1ms          | 5ms            |
| ExecutionProcessor     | < 5ms          | 50ms           |

Channel backpressure tests: fill a channel to capacity, verify that the producer blocks rather than dropping messages.

---

## 9. A/B Testing Support

### 9.1 How A/B Works in This Architecture

Because processors communicate only through channels, running two variants in parallel requires no code change — only YAML config change.

**Pattern 1: Parallel gate test**
Both `signal_gate_control` and `signal_gate_treatment` subscribe to the same `amt_results` channel. Python's asyncio queues support multiple consumers — both gates receive every AMT result independently. Their outputs go to separate channels (`gate_pass_control`, `gate_pass_treatment`). An `ABCollectorProcessor` receives from both and records the comparison.

**Pattern 2: Traffic split for execution**
A `TrafficSplitterProcessor` receives from one input channel and routes to one of two output channels. Routing is deterministic by symbol + minute (even minutes → control, odd → treatment). Both variants drive real execution, and the persistence layer records which pipeline produced each trade for post-session comparison.

**Pattern 3: Shadow mode**
The `treatment` pipeline runs but its `OrderIntentMessage` goes to a `ShadowExecutionProcessor` that logs the intent without placing the order. Compare the logged intents from the shadow pipeline against the control pipeline's actual fills. This is the safest A/B mode for production.

### 9.2 ABCollectorProcessor Interface

```
Input:
  - control: any message type
  - treatment: any message type (same type as control)
Output:
  - ab_results: ABComparisonMessage

Config:
  track_metric: str              # Field name from message payload to compare
  window_minutes: int            # Rolling window for statistics
  min_sample_size: int           # Minimum observations before reporting
```

### 9.3 Metrics Captured per Variant

- Gate pass rate (gate_score distribution)
- LLM LONG/SHORT/FLAT ratio
- Fill rate (intent → fill conversion)
- P&L contribution (trade by trade)
- Probability P(adverse) distribution at decision time
- Latency at each stage

---

## 10. Migration Path from Current Codebase

Migration is designed as six non-breaking phases. At each phase boundary the system is deployable to production. No phase requires changing more than two Python files that are not new files.

### Phase 1 — Formalise Message Schemas (1 week)
**Goal:** Extract all inter-component data into typed dataclasses.

Action: Create `backend/app/pipeline/messages.py` with all message types defined in Section 5. These mirror the existing domain value objects and handler outputs but add the `MessageEnvelope` wrapper.

Nothing in the existing code changes. The message module is additive.

Test: Schema serialisation tests pass for all 15 message types.

### Phase 2 — Create Channel Infrastructure and ProcessorRegistry (1 week)
**Goal:** Build the plumbing without connecting it to the existing engine.

Action: Create `backend/app/pipeline/channels.py` (bounded async queue with type enforcement), `backend/app/pipeline/base.py` (abstract `Processor` Protocol), and `backend/app/pipeline/registry.py` (processor class registry + decorator).

Write `FakeChannel` and `CollectingChannel` test utilities. Write the topology validator that checks YAML config against the registry.

Nothing in the existing engine changes. The pipeline infrastructure runs in parallel.

Test: Channel backpressure test passes. Registry decorator registers a stub processor.

### Phase 3 — Extract Ingestion and Candle Building (2 weeks)
**Goal:** Pull the tick streaming and candle aggregation logic out of `TradingEngine` into processor classes, while `TradingEngine` continues to work.

Action:
1. Create `DhanIngestionProcessor` wrapping the existing `DhanMarketDataAdapter.stream_full()`. The processor emits `RawTickMessage` objects.
2. Create `CandleBuilderProcessor` wrapping `_aggregate_candle()` logic from `TradingEngine`. The processor consumes `RawTickMessage` and emits `CandleClosedMessage`.
3. Create a shim inside `TradingEngine._tick_loop()` that, in addition to existing processing, sends ticks to the new channel. Both paths run simultaneously.

The existing `TradingEngine` continues to function. The new processors run alongside it on separate asyncio tasks.

Test: `FileReplayIngestionProcessor` + `CandleBuilderProcessor` integration test reproduces known candle sequence from the existing test suite.

### Phase 4 — Extract Analysis, Gate, and LLM Processors (2 weeks)
**Goal:** Replace `AMTHandler`, `LLMEntryHandler`, and `LLMOverseerHandler` with processor classes.

Action:
1. Create `AMTAnalysisProcessor` wrapping `AMTAnalyzer` + `RegimeDetector`.
2. Create `SignalGateProcessor` wrapping `entry_gate.py` functions.
3. Create `LLMEntryProcessor` wrapping `LLMEntryHandler` logic (prompt build, inference, parse).
4. Create `OverseerProcessor` wrapping `LLMOverseerHandler` logic.
5. Wire Phase 3 channel output (`CandleClosedMessage`) into Phase 4 processors.
6. In `TradingSessionService.process_tick()`, add a parallel path that publishes to the new channel. Both paths write to `_latest_states` (the existing path continues to win as ground truth).

At end of this phase, the new processors produce shadow `LLMDecisionMessage` objects that are logged but do not drive positions. Compare against the existing path's decisions to verify parity.

Test: Determinism test passes — replay produces identical `LLMDecisionMessage` sequence when compared with historical decisions captured before migration.

### Phase 5 — Extract Risk, Execution, and Persistence Processors (1 week)
**Goal:** Complete the execution path through the new pipeline.

Action:
1. Create `RiskManagementProcessor` wrapping `RiskManager` + `SessionRiskManager`.
2. Create `PaperExecutionProcessor` wrapping `PaperBrokerAdapter`.
3. Create `PersistenceProcessor` wrapping `AsyncPersistenceBus`.
4. Flip the switch: route `OrderIntentMessage` from the new pipeline to the execution processor. The old execution path in `TradingSessionService` is disabled (behind a feature flag in `config.py`).

Feature flag: `PIPELINE_V2_EXECUTION: bool = False` in `config.py`. Setting it to `True` routes orders through the new processor pipeline.

Test: Full pipeline integration test from replay file → `OrderFilledMessage` in paper mode.

### Phase 6 — Remove Old Engine and Session Service (1 week)
**Goal:** Delete the legacy code once the new pipeline has run in production for one full trading week with `PIPELINE_V2_EXECUTION=True`.

Action:
1. Remove `TradingEngine._aggregate_candle()`, `_tick_loop()`, and all per-symbol state dicts (they are now inside `CandleBuilderProcessor`).
2. Remove `TradingSessionService.process_tick()` and handler dispatch (now in processors).
3. Remove the feature flag.
4. `TradingEngine` becomes a thin wrapper that starts the `PipelineRunner` and exposes `get_latest_state()` (which reads from the `FrontendStreamingProcessor`'s state cache).

The `ServiceGraph` in `dependencies.py` now instantiates `PipelineRunner` with the YAML config path instead of constructing handlers manually.

Test: The full test suite (currently 569 tests) passes. New processor unit tests bring total to approximately 700+.

---

## 11. Folder Structure

```
backend/
  app/
    pipeline/                          # NEW — Pipeline infrastructure
      __init__.py
      messages.py                      # All Message[T] types (Section 5)
      channels.py                      # Channel[T] bounded async queue
      base.py                          # Processor Protocol + ProcessorConfig ABC
      registry.py                      # ProcessorRegistry + @register_processor decorator
      runner.py                        # PipelineRunner — loads YAML, wires, starts all tasks
      config_loader.py                 # YAML → Pipeline dataclass; topology validator
      ab_collector.py                  # ABCollectorProcessor + TrafficSplitterProcessor
      health.py                        # PipelineHealthMonitor — channel depths, lag metrics

    processors/                        # NEW — One file per processor
      __init__.py
      ingestion/
        __init__.py
        dhan_ingestion.py              # DhanIngestionProcessor
        file_replay.py                 # FileReplayIngestionProcessor
        synthetic.py                   # SyntheticDataIngestionProcessor
        rest_polling.py                # RESTPollingIngestionProcessor
      candle_builder.py                # CandleBuilderProcessor
      market_analysis/
        __init__.py
        amt_analysis.py                # AMTAnalysisProcessor
        regime_detection.py            # RegimeDetectionProcessor
      signal_gate.py                   # SignalGateProcessor
      llm_entry.py                     # LLMEntryProcessor
      overseer.py                      # OverseerProcessor
      risk_management.py               # RiskManagementProcessor
      execution/
        __init__.py
        paper_execution.py             # PaperExecutionProcessor
        dhan_execution.py              # DhanExecutionProcessor
      persistence.py                   # PersistenceProcessor
      frontend_streaming.py            # FrontendStreamingProcessor
      notifications/
        __init__.py
        telegram.py                    # TelegramNotificationProcessor
        null.py                        # NullNotificationProcessor
      option_scanner.py                # OptionScannerProcessor

    domain/                            # UNCHANGED — pure domain logic
      trading/
        models/
          value_objects.py             # OHLC, AMTResult, OrderBook, etc.
          entities.py
          aggregates.py
          enums.py
        events.py
        services/
          risk_manager.py
          trade_manager.py
      fabio_ai/
        services/
          amt_analyzer.py
          entry_gate.py                # three_align_check, confirmation_bundle
          prompt_builder.py
          regime_detector.py
          session_risk_manager.py
          cvd_tracker.py
          footprint_analyzer.py
          profile_classifier.py
          market_structure_classifier.py
          option_scanner.py
          mlx_compute.py
      ports/
        llm_inference.py               # LLMInferencePort
        probability_inference.py       # ProbabilityInferencePort
        storage.py                     # StoragePort sub-ports
        broker.py                      # BrokerPort
        notifications.py               # NotificationPort
        market_data.py                 # MarketDataPort

    infrastructure/                    # UNCHANGED — adapters
      adapters/
        dhan_adapter.py
        mlx_inference_adapter.py
        lgbm_probability_adapter.py
        paper_broker.py
        telegram_adapter.py
        null_notification_adapter.py
        data_generator.py
      storage/
        database.py                    # SQLiteStorageAdapter
      event_bus.py
      async_persistence.py
      metrics.py
      observability.py

    application/                       # SHRINKS — thin coordinator only
      engine.py                        # TradingEngine → thin wrapper over PipelineRunner
      services/
        trading_session.py             # Retained during Phase 3-5; deleted in Phase 6
        daily_reporter.py
        forward_test_logger.py
        snapshot_builder.py
      handlers/                        # Retained during migration; processors supersede them
        amt_handler.py
        llm_entry_handler.py
        llm_overseer_handler.py
        trade_lifecycle_handler.py
        rl_handler.py

    api/                               # UNCHANGED
      websocket/
        gameloop.py
      routers/
        trading.py
        market.py
        ai.py
        analysis.py

pipelines/                             # NEW — YAML pipeline configs at repo root level
  pipeline_production.yaml             # Section 6.1
  pipeline_replay.yaml                 # Section 6.2
  pipeline_ab_test.yaml                # Section 6.3
  pipeline_dev.yaml                    # Synthetic data, no LLM calls, fast candles
  pipeline_paper.yaml                  # Live data, paper execution, full LLM

tests/
  messages/                            # Section 8.1
    test_message_schemas.py
  domain/                              # Section 8.2 — already exists, unchanged
    test_amt_analyzer.py
    test_entry_gate.py
    test_prompt_builder.py
    test_regime_detector.py
    test_session_risk_manager.py
  processors/                          # Section 8.3
    test_candle_builder.py
    test_amt_analysis_processor.py
    test_signal_gate_processor.py
    test_llm_entry_processor.py
    test_overseer_processor.py
    test_risk_management_processor.py
    test_execution_processor.py
  integration/                         # Section 8.4
    test_pipeline_segments.py
    test_full_replay_pipeline.py
  config/                              # Section 8.5
    test_pipeline_config_validation.py
  determinism/                         # Section 8.6
    test_replay_determinism.py
  performance/                         # Section 8.7
    test_channel_backpressure.py
    test_processor_latency_budget.py
  utils/
    channels.py                        # FakeChannel, CollectingChannel test utilities
    fixtures.py                        # build_test_amt_result(), build_passing_gate_message()
```

---

## 12. Patterns Reference

### 12.1 Apache NiFi Processor Model

NiFi's key insight is that processors declare relationships (`success`, `failure`, `retry`) rather than hardcoding routing logic. This architecture uses named channels in the YAML config to achieve the same effect. The `gate_block` channel is the `failure` relationship of `SignalGateProcessor`. Anything can subscribe to it for dead-letter analysis without the gate knowing.

The `correlation_id` threading through every message is the NiFi `FlowFile.uuid` equivalent — it enables end-to-end tracing from a raw tick to the resulting order fill.

### 12.2 Hexagonal Architecture (Ports and Adapters)

This architecture already has ports. The extension is that **processors are not ports** — they are the application layer that wires ports to channels. A port (`LLMInferencePort`) is implemented by an adapter (`MLXInferenceAdapter`). A processor (`LLMEntryProcessor`) receives the port via constructor injection and calls it. The processor never knows which adapter is wired.

This makes `LLMEntryProcessor` testable with a `MockLLMAdapter` that returns canned responses.

### 12.3 LMAX Disruptor Influence

The Disruptor's key properties — ring buffer, single producer, multiple consumers without locking — are approximated in Python asyncio by using `asyncio.Queue` with a bounded capacity. The critical LMAX insight applied here: **sequence numbers as coordination**. The `correlation_id` in every message is a logical sequence that allows the `FrontendStreamingProcessor` to detect out-of-order messages and the `PersistenceProcessor` to deduplicate writes without a distributed lock.

For extreme latency requirements (sub-millisecond candle aggregation), the `CandleBuilderProcessor` can be implemented as a direct callback in the ingestion hot path (bypassing the channel for the candle state update), with only the `CandleClosedMessage` going onto the bounded channel. This mirrors the Disruptor pattern of keeping the critical path lock-free while routing results through a ring buffer.

### 12.4 Event Sourcing for Positions

`PositionEventMessage` (Section 5) is an append-only event log: `POSITION_OPENED`, `SL_MOVED`, `PARTIAL_CLOSE`, `POSITION_CLOSED`. Current state can always be reconstructed by replaying these events. This means:

1. The `OverseerProcessor`'s TIGHTEN_SL action is always recorded as a `PositionEventMessage`, never as a mutable in-place edit.
2. Post-trade reconstruction (for debugging P&L discrepancies) works by replaying the event stream.
3. The existing `trade_reconstruction.py` module already has this idea — the new architecture formalises it as the canonical persistence model.

### 12.5 Python asyncio Structured Concurrency

All processors run as `asyncio.Task` instances created by `PipelineRunner`. Python 3.11+ `asyncio.TaskGroup` provides structured concurrency: if any processor task raises an unhandled exception, `TaskGroup` cancels all sibling tasks and propagates the exception. For processors that must survive individual failures (e.g., `TelegramNotificationProcessor`), the task wraps its `process()` loop in `try/except` and restarts with exponential backoff — it never propagates to the task group.

The critical rule: every processor's `process()` method is an `async def` that runs an infinite `async for msg in inbox["channel"]` loop. The loop exits only when the channel is closed (graceful shutdown) or the task is cancelled. This matches the `asyncio.TaskGroup` lifecycle model precisely.

---

*End of document*
