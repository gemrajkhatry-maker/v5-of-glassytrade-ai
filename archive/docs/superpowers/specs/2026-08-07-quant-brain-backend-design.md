# Quant Brain Backend — Full Swap Design

**Date:** 2026-08-07
**Status:** Approved (user confirmed sections 1–4)

## Goal

Make the greenfield `quant/` engine the **only** decision brain and strip the FastAPI backend down to a thin transport shell (WS viewer + REST). Delete the legacy AMT/gate/entry/LLM-handler pipeline. Port every frontend-facing indicator/value the UI reads into the quant brain so the frontend keeps receiving the same snapshot shape.

## Architecture

```
quant/                      ← brain (stays pure: quant.* + stdlib + quant/inference/*)
  coordinator.py            NEW QuantCoordinator: scanner → one QuantEngine per scanned contract
  runtime.py                QuantEngine (unchanged core loop)
  brokers/live_gateway.py   extends: forward oi + depth from FullPacket
  state.py                  StateProjector: fold in amt, genAIAnalysis, overseer, agentDecision, depth, oi
  ws_adapter.py             view_state_to_ws (already matches frontend contract)
  inference/                mlx_inference_adapter + prompt builders MOVE here (no app.* imports)

backend/app/                ← thin FastAPI server shell (transport only)
  main.py                   lifespan boots QuantCoordinator
  api/websocket/gameloop.py WS viewer: streams coordinator snapshots, delta compression
  api/routers/              /api/system/config, /api/ai/history, /api/scanner/rescan, health, metrics
  di/                       resolves QuantCoordinator + broker adapters
  infrastructure/adapters/  DhanMarketDataAdapter, PaperBrokerAdapter (execution seam)
```

## Section 1 — QuantCoordinator (new, in quant/coordinator.py)

- `QuantCoordinator(broker, inference, llm_adapter, config)`
- `start()` → run `OptionScannerService` → build one `LiveGateway` per scanned contract → one `QuantEngine` per contract
- `snapshot(symbol)` → merged frontend state from that symbol's engine projector
- `llm_history(symbol)` → capped (~50) list of genAIAnalysis records
- `control()` → rescan, switch_symbol(old, new), start/stop
- Deterministic bar-close loop + async LLM fold-back (non-blocking)
- Execution seam: engines emit decisions → coordinator `decisions` queue → backend drains to broker adapter

One `QuantEngine` per **scanned contract** (maps 1:1 to the per-symbol WS subscription the frontend uses).

## Section 2 — Thin backend shell (9090)

**Stays:**
- `app/main.py`, FastAPI app + lifespan → boots `QuantCoordinator`
- WS viewer `gameloop.py` (snapshots + delta compression + control messages: subscribe, ping/pong, server_mode, symbol_switched, history_loaded)
- REST: `/api/system/config`, `/api/ai/history`, `/api/scanner/rescan`, health, metrics
- DI container → resolves `QuantCoordinator` + broker adapters
- `DhanMarketDataAdapter`, `PaperBrokerAdapter`
- `quant/contracts/*`, `quant/inference/*`

**Deleted (legacy decision pipeline):**
- services: `amt_service.py`, `session_event_router.py`, `entry_coordinator.py`, `exit_coordinator.py`, `trading_session.py`, `engine_lifecycle.py`, `stream_manager.py`, `watchdog_manager.py`, `session_*` managers, `quant_bridge.py`, `quant_signal_mapper.py`
- handlers: `amt_handler.py`, `entry_gate_coordinator.py`, `llm_entry_handler.py`, `llm_overseer_handler.py`, `post_trade_analyst.py`, `pre_candle_advisor.py`, `trade_lifecycle_handler.py`, `rl_handler.py`
- snapshot/broadcast: `state_snapshot_builder.py`, `state_broadcaster.py` (replaced by coordinator + `quant/state.py` + `quant/ws_adapter.py`)

## Section 3 — LLM integration inside the engine

- `mlx_inference_adapter.py` moves to `quant/inference/` (already quant-flavored), no `app.*` imports
- Engine bar-close hook → submit prompt to LLM executor → fold `genAIAnalysis`/`overseerAction`/`overseerReason`/`agentDecision` into projector asynchronously
- `LLMHistoryBuffer` per symbol (capped ~50) → `/api/ai/history`
- LLM failure never blocks the deterministic loop (preserve circuit-breaker)
- Prompt builders move to `quant/inference/`
- `LiveGateway` passes `oi` + top-of-book `depth` through Tick → aggregator → projector

## Section 4 — Testing & rollout

- Keep greenfield tests green (`tests/quant/*`)
- New: QuantCoordinator (multi-symbol, rescan, symbol-switch, decision queue), LLM-in-engine (mock adapter), backend shell (gameloop + REST against fake coordinator)
- Delete legacy backend tests targeting removed modules
- Restart backend on :9090 with coordinator; frontend unchanged (same WS path + shape); verify live NIFTY/BANKNIFTY/FINNIFTY snapshots on gameloop; keep :8765 standalone experiment for back-compat reference until confirmed
