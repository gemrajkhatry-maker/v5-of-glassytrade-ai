# GlassyTrade AI — Architecture Master Plan
**Date:** 2026-03-14  
**Status:** Implementation in progress  
**Based on:** Architecture Audit (Agent 1) + Pipeline Design (Agent 2) + Tick Flow Investigation (Agent 3)

---

## Confirmed Root Causes Fixed

| Issue | Root Cause | Fix Applied |
|-------|-----------|-------------|
| Chart assertion error (duplicate timestamps) | `query_ticks` returned multiple rows per candle (per-tick writes) | `_load_candles_from_db` aggregates by timestamp; confirmed per audit: writes ARE per-candle-close |
| MCX WS circuit breaker cascade | `fetch_history` hitting `CHARTS_INTRADAY` → HTTP 400 for OPTFUT | Early return for MCX options in `fetch_history` |
| MCX live data: "Waiting for Market Data" | Dhan WS never sends binary frames for MCX OPTFUT (broker limitation, confirmed) | REST LTP polling fallback in `stream_poll` + stale watchdog switches after 60s |
| WS "no close frame" (previous session) | Expired Dhan access token, not wrong segment | Fresh token fixes it; MCX_COMM is correct segment |

---

## Architecture Refactoring — 6 Phases

### Phase 1: Pipeline Core (In Progress) ✅
`backend/app/pipeline/`
- `message.py` — Typed frozen dataclass messages (RawTick, Candle, AMTResult, LLMDecision…)
- `channel.py` — Bounded async queue with backpressure
- `processor.py` — Processor Protocol + BaseProcessor
- `registry.py` — YAML loader + processor factory
- `processors/ingest.py` — DhanWsIngestor, RestPollIngestor, FileReplayIngestor, SimIngestor

**Key principle:** Any ingestor → same `RawTickMessage` → rest of pipeline unchanged

### Phase 2: Candle Builder Processor
`backend/app/pipeline/processors/candle.py`
- `CandleBuilderProcessor` wraps existing `_aggregate_candle` logic
- Consumes `RawTickMessage`, produces `CandleMessage`
- Emits `closed=True` when candle period closes
- Completely data-source agnostic (same output for WS, poll, file, sim)
- `CandleClosedMessage` triggers DB write (decoupled from tick loop)

### Phase 3: Analysis Processors
`backend/app/pipeline/processors/analysis.py`
- `AMTAnalysisProcessor` wraps `AMTAnalyzer` → `AMTResultMessage`
- `SignalGateProcessor` wraps `entry_gate.py` → `SignalGateMessage`
- Pure functions: same input → identical output regardless of data source

### Phase 4: Decision Processors
`backend/app/pipeline/processors/llm_entry.py`
- `LLMEntryProcessor` wraps `LLMEntryHandler` → `LLMDecisionMessage`
- `OverseerProcessor` wraps `LLMOverseerHandler` → `OverseerDecisionMessage`
- Isolation: failures caught at channel boundary, don't propagate

### Phase 5: Execution + Persistence Processors
`backend/app/pipeline/processors/execution.py`
`backend/app/pipeline/processors/persistence.py`
- `OrderExecutionProcessor` → wraps PaperBroker/DhanBroker
- `PersistenceProcessor` → writes candles/trades/events to storage
- `FrontendPublisherProcessor` → pushes state to WS game loop

### Phase 6: Legacy Removal
- Delete `TradingEngine._tick_loop()` internals (keep public API as thin wrapper)
- `TradingSessionService.process_tick()` becomes a pipeline runner
- Event bus actually used for inter-processor fan-out

---

## Folder Structure (Final State)

```
backend/app/pipeline/
├── __init__.py
├── message.py          # All typed message payloads
├── channel.py          # Bounded async Channel[T]
├── processor.py        # Processor Protocol + BaseProcessor
├── registry.py         # YAML loader + factory
└── processors/
    ├── __init__.py
    ├── ingest.py        # DhanWsIngestor, RestPollIngestor, FileReplayIngestor, SimIngestor
    ├── candle.py        # CandleBuilderProcessor
    ├── analysis.py      # AMTAnalysisProcessor, SignalGateProcessor
    ├── llm_entry.py     # LLMEntryProcessor
    ├── overseer.py      # OverseerProcessor
    ├── execution.py     # OrderExecutionProcessor
    ├── persistence.py   # PersistenceProcessor
    └── frontend.py      # FrontendPublisherProcessor

pipelines/
├── production.yaml      # Dhan WS → candles → AMT → gate → LLM → execution
├── replay.yaml          # File replay → same pipeline (deterministic backtest)
├── paper_trading.yaml   # REST poll → same pipeline → paper broker
└── dev.yaml             # SimIngestor → same pipeline (no external deps)

backend/tests/unit/pipeline/
├── test_message.py
├── test_channel.py
├── test_ingestors.py
├── test_candle_builder.py
├── test_analysis_processors.py
└── test_pipeline_registry.py
```

---

## Testing Strategy

| Layer | Approach | No external deps |
|-------|---------|-----------------|
| Messages | Unit: frozen dataclass properties, immutability | ✅ |
| Channel | Unit: asyncio queue, backpressure, stats | ✅ |
| SimIngestor | Unit: seeded reproducibility, tick count | ✅ |
| FileReplayIngestor | Unit: JSONL/CSV parsing, speed multiplier | ✅ (temp files) |
| CandleBuilder | Unit: OHLCV aggregation, candle close detection | ✅ |
| AMTAnalysis | Unit: existing amt_analyzer tests apply | ✅ |
| SignalGate | Unit: gate pass/block conditions | ✅ |
| LLMEntry | Unit: mock MLX adapter | ✅ |
| Full pipeline | Integration: SimIngestor → full chain end-to-end | ✅ |
| Determinism | Regression: file replay produces identical signals | ✅ |

---

## Breaking Seams Addressed

From the audit's 10 broken seams:

| Seam | Fix |
|------|-----|
| No event publishing in hot loop | Processors communicate via channels (Phase 1-6) |
| TradingEngine→TradingSessionService tight coupling | TickProcessorPort abstraction (Phase 4-5) |
| Candle closing → DB write implicit | Explicit CandleClosedMessage → PersistenceProcessor (Phase 5) |
| No signal idempotency | correlation_id on every message, dedup at execution (Phase 4) |
| Crash recovery not atomic | Event sourcing via PositionEventProcessor (Phase 5) |
| No separation entry/management | Separate LLMEntryProcessor + OverseerProcessor channels (Phase 4) |
| Dhan-specific code in non-infra | All in DhanWsIngestor (infrastructure only) (Phase 1) |
| Overseer probability silent failure | Explicit setup validation in OverseerProcessor (Phase 4) |
| Risk state not versioned | Versioned state in PersistenceProcessor (Phase 5) |
| LLM response not validated | Validation schema in LLMEntryProcessor (Phase 4) |
