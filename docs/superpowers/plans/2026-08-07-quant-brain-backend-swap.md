# Quant Brain Backend — Full Swap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the greenfield `QuantEngine` the only decision brain and strip the FastAPI backend to a thin transport shell (WS viewer + REST), porting the LLM + all frontend values into `quant/`.

**Architecture:** `quant/coordinator.py` (`QuantCoordinator`) owns one `QuantEngine` per scanned contract, each with a `LiveGateway` (extended to carry `oi` + `depth`). The MLX adapter moves into `quant/inference/`; the engine's bar-close path folds LLM results (`genAIAnalysis`, `overseerAction/Reason`, `agentDecision`) into `StateProjector` asynchronously. The backend becomes REST + WS transport only, resolving the coordinator and draining its decision queue into `PaperBrokerAdapter`.

**Tech Stack:** Python 3.13, FastAPI/uvicorn, MLX, asyncio, threading, Dhan broker API.

## Global Constraints

- `quant/` stays pure: imports `quant.*` + stdlib + `quant/inference/*` ONLY — zero `app.*` imports (hard rule, verified by a test).
- `quant.brokers.gateway.Tick` stays the tick contract; time strings MUST be int-parseable for `BarAggregator`.
- `view_state_to_ws`/`StateProjector.snapshot` output keys are the frontend contract — never rename/remove a key the frontend reads.
- Do NOT add new dependencies beyond what the repo already declares.
- Run tests from repo root for `tests/quant/`, from `backend/` for `backend/tests/`.

---

### Task 1: Move MLX adapter into `quant/inference/`

**Files:**
- Create: `quant/inference/mlx_inference_adapter.py`
- Modify: `quant/inference/__init__.py` (export `MLXInferenceAdapter`)
- Delete: `backend/app/infrastructure/adapters/mlx_inference_adapter.py`
- Test: `backend/tests/unit/infrastructure/test_mlx_inference_adapter.py` (move alongside)

**Interfaces:**
- Consumes: `quant.contracts.ports.llm_inference.ILLMInference` protocol (`predict`, `is_ready`, `wait_until_ready`, `validate`).
- Produces: `class MLXInferenceAdapter(ILLMInference)` with the same public API. It reads `MLX_MODEL_PATH`/`MLX_ADAPTER_PATH` env vars and repo-relative `models/` dirs.

- [ ] **Step 1: Move the file** with `git mv`, then strip every `from app.` import. Search the file for `app.` imports and replace:
  - `from app.infrastructure.mlx_gpu_lock import MLX_GPU_LOCK` → move `MLX_GPU_LOCK` into `quant/inference/mlx_inference_adapter.py` (module-level `threading.Lock()`).
  - Any `from app.config import settings` / `from app.config_models...` → replace with `os.environ.get("MLX_MODEL_PATH", "models/vibethinker-3b")` etc. The existing `_effective_model_path()`/`_ensure_runtime_env_loaded()` already resolve repo-relative paths; keep that.
  - `from app.core.logging import logger` → `import logging; logger = logging.getLogger(__name__)`.
- [ ] **Step 2: Export from `quant/inference/__init__.py`**: add `from quant.inference.mlx_inference_adapter import MLXInferenceAdapter`.
- [ ] **Step 3: Update imports everywhere** the old path is referenced: `grep -rn "mlx_inference_adapter" backend/ quant/ --include="*.py"` and repoint to `quant.inference.mlx_inference_adapter`.
- [ ] **Step 4: Run tests** from repo root: `.venv/bin/python -m pytest tests/quant/ -q` (expect green). The adapter tests move to `backend/tests/unit/infrastructure/`.
- [ ] **Step 5: Commit**: `git add -A && git commit -m "refactor: move MLX adapter into quant/inference"`

---

### Task 2: Extend `LiveGateway` to carry `oi` + `depth`

**Files:**
- Modify: `backend/app/infrastructure/adapters/live_gateway.py` (extend `_convert` to also emit oi/depth via the gateway)
- Modify: `quant/brokers/gateway.py` (extend `Tick` with `oi: float = 0.0` and `depth: dict | None = None`)
- Test: `backend/tests/unit/infrastructure/test_live_gateway.py`

**Interfaces:**
- Consumes: Dhan `stream_full` FullPacket dict fields `oi`, `depth_bids`, `depth_asks`, `ltp`, `ltq`, `volume`, `total_buy_qty`, `total_sell_qty`, `timestamp`.
- Produces: `Tick` gains `oi: float = 0.0` and `depth: dict | None = None` where `depth = {"bids": [[price, qty], ...], "asks": [[price, qty], ...]}` (top 5 each).

- [ ] **Step 1: Extend `Tick`** in `quant/brokers/gateway.py`:
```python
@dataclass(frozen=True)
class Tick:
    time: str
    price: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    oi: float = 0.0
    depth: dict | None = None
```
- [ ] **Step 2: In `LiveGateway._convert`**, parse `oi` and depth:
```python
depth = None
db = pkt.get("depth_bids") or []
da = pkt.get("depth_asks") or []
if db or da:
    depth = {
        "bids": [[float(b["price"]), float(b["quantity"])] for b in db[:5]],
        "asks": [[float(a["price"]), float(a["quantity"])] for a in da[:5]],
    }
# add to the Tick(...) constructor:
oi=float(pkt.get("oi") or 0),
depth=depth,
```
- [ ] **Step 3: Update `test_live_gateway.py`** — add a packet with `oi` and `depth_bids`/`depth_asks`; assert the produced `Tick.oi` and `Tick.depth` match.
- [ ] **Step 4: Run**: from repo root `.venv/bin/python -m pytest backend/tests/unit/infrastructure/test_live_gateway.py -q` → all pass.
- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat: LiveGateway carries oi and order-book depth"`

---

### Task 3: Projector folds `oi`, `depth`, `amt`, LLM fields into snapshots

**Files:**
- Modify: `quant/state.py` (`StateProjector.on_event`, `_symbol_state`)
- Test: `tests/quant/state/test_projector_events.py` (new)

**Interfaces:**
- Consumes: `quant.events` (`BarClosed`, `AuctionUpdated`, `DecisionProduced`, `PositionOpened`, `PositionClosed`, `RiskUpdated`) plus new events from Task 4: `LLMAnalysisProduced`, `OverseerProduced`, `AgentDecisionProduced`, `DepthUpdated`.
- Produces: snapshots with populated `oi`, `depth`, `amt`, `gen_ai`, `overseer_action`, `overseer_reason`, `agent_decision`.

- [ ] **Step 1: Write failing tests** in `tests/quant/state/test_projector_events.py` asserting each new event folds into `snapshot(symbol)`:
  - `DepthUpdated` → `snapshot.depth` set.
  - `LLMAnalysisProduced` → `snapshot.gen_ai` = `{"direction","confidence","rationale","inputPrompt","rawOutput"}`.
  - `OverseerProduced` → `snapshot.overseer_action` + `overseer_reason` set.
  - `AgentDecisionProduced` → `snapshot.agent_decision` = `{"direction","probability","regime","timing","sizeFraction","latencyUs","rationale"}`.
  - `amt` populated (from the engine's AuctionState-derived value — see Task 4).
- [ ] **Step 2: Add event handlers** in `StateProjector.on_event`:
```python
elif isinstance(event, DepthUpdated):
    s["depth"] = event.depth
elif isinstance(event, LLMAnalysisProduced):
    s["gen_ai"] = event.analysis
elif isinstance(event, OverseerProduced):
    s["overseer_action"] = event.action
    s["overseer_reason"] = event.reason
elif isinstance(event, AgentDecisionProduced):
    s["agent_decision"] = event.decision
elif isinstance(event, AmtUpdated):
    s["amt"] = event.amt
```
Ensure `oi` is folded on `BarClosed` from `event.bar` (add `oi` to `_bar_to_tick` if the bar carries it).
- [ ] **Step 3: Run** `.venv/bin/python -m pytest tests/quant/state/ -q` → green.
- [ ] **Step 4: Commit**: `git add -A && git commit -m "feat: projector folds oi/depth/LLM/amt into snapshots"`

---

### Task 4: LLM hook in the engine + new events

**Files:**
- Modify: `quant/events.py` (add `LLMAnalysisProduced`, `OverseerProduced`, `AgentDecisionProduced`, `DepthUpdated`, `AmtUpdated`)
- Modify: `quant/runtime.py` (`QuantEngine` gains an `inference` param + async fold-back)
- Test: `tests/quant/runtime/test_llm_hook.py` (new)

**Interfaces:**
- Consumes: `quant.inference.mlx_inference_adapter.MLXInferenceAdapter` (`predict`, `is_ready`), `quant.inference.prompt_builder`.
- Produces: new `quant.events` dataclasses; `QuantEngine(gateway, symbol, interval_seconds=60, journal_path=None, min_rr=1.5, tick_size=0.05, time_stop_bars=60, inference=None, llm_history=None)`.

- [ ] **Step 1: Add events** to `quant/events.py`:
```python
@dataclass(frozen=True)
class DepthUpdated(Event):
    depth: dict | None = None
@dataclass(frozen=True)
class LLMAnalysisProduced(Event):
    analysis: dict | None = None
@dataclass(frozen=True)
class OverseerProduced(Event):
    action: str = ""
    reason: str = ""
@dataclass(frozen=True)
class AgentDecisionProduced(Event):
    decision: dict | None = None
@dataclass(frozen=True)
class AmtUpdated(Event):
    amt: dict | None = None
```
- [ ] **Step 2: In `QuantEngine.__init__`** accept `inference=None` and `llm_history=None` (a per-symbol capped list buffer). Store them.
- [ ] **Step 3: In `_on_bar_closed`**, after computing `state`, schedule a non-blocking LLM fold-back:
```python
if self._inference is not None and self._inference.is_ready():
    self._schedule_llm(state, bar)
```
`_schedule_llm` runs `self._inference.predict(...)` on a `ThreadPoolExecutor(max_workers=1)` and, when the future completes, `self._emit(LLMAnalysisProduced(...))` (and Overseer/AgentDecision) from a thread-safe emit path. If `inference` is None, emit `AmtUpdated` from the auction state directly (so `amt` is always populated).
- [ ] **Step 4: Write tests** asserting: with a fake inference returning canned JSON, snapshots eventually contain `gen_ai`; with `inference=None`, `amt` still populates; the deterministic trace (bars/decisions) is unchanged when inference is present.
- [ ] **Step 5: Run** `.venv/bin/python -m pytest tests/quant/runtime/ -q` → green.
- [ ] **Step 6: Commit**: `git add -A && git commit -m "feat: LLM hook folds analysis/overseer/agent into engine snapshots"`

---

### Task 5: `QuantCoordinator` — multi-symbol orchestrator

**Files:**
- Create: `quant/coordinator.py`
- Test: `tests/quant/test_coordinator.py` (new)

**Interfaces:**
- Consumes: `OptionScannerService` (`quant/amt/session/scanner.py`), `QuantEngine`, `LiveGateway`, `MLXInferenceAdapter`, a broker adapter.
- Produces:
```python
class QuantCoordinator:
    def __init__(self, market_data, inference, broker, config=None): ...
    def start(self) -> None: ...          # scan + spawn engines
    def rescan(self) -> list[str]: ...    # new contracts
    def switch_symbol(self, old: str, new: str) -> bool: ...
    def stop(self) -> None: ...
    def snapshot(self, symbol: str) -> dict: ...       # view_state_to_ws(engine.projector.snapshot(symbol))
    def symbols(self) -> list[str]: ...
    def llm_history(self, symbol: str) -> list[dict]: ...
    def decisions(self) -> queue.Queue: ...            # engine decisions for the backend to fill
```

- [ ] **Step 1: Write failing tests** (`tests/quant/test_coordinator.py`) with a fake scanner + fake gateway + fake inference:
  - `start()` scans, spawns one engine per contract, `symbols()` returns them.
  - `snapshot(sym)` returns a dict with the frontend contract keys.
  - `switch_symbol(old,new)` replaces the engine and returns True.
  - `rescan()` returns the new contract list.
  - `llm_history(sym)` returns appended records.
  - `decisions()` yields decisions from each engine.
- [ ] **Step 2: Implement `QuantCoordinator`** — runs each `QuantEngine.run()` on its own daemon thread; per-symbol `LiveGateway`; a shared inference adapter; a decision `queue.Queue` drained via the engine's event bus (subscribe to `SignalApproved`/`DecisionProduced` in `start()`).
- [ ] **Step 3: Run** `.venv/bin/python -m pytest tests/quant/test_coordinator.py -q` → green.
- [ ] **Step 4: Commit**: `git add -A && git commit -m "feat: QuantCoordinator orchestrates per-symbol engines"`

---

### Task 6: Thin backend shell — REST endpoints + WS viewer over coordinator

**Files:**
- Modify: `backend/app/main.py` (lifespan boots `QuantCoordinator`; wire `/api/ai/history`, `/api/scanner/rescan` to coordinator)
- Modify: `backend/app/api/routers/health.py`, `backend/app/api/routers/ai.py` (repoint to coordinator)
- Modify: `backend/app/api/websocket/gameloop.py` (`_viewer_loop` reads coordinator snapshots)
- Modify: `backend/app/application/di/composition_root.py` (resolve coordinator)
- Test: `backend/tests/unit/api/test_ws_over_coordinator.py` (new)

**Interfaces:**
- Consumes: `QuantCoordinator` (from Task 5).
- Produces: `/api/ai/history` returns `{"history": [...]}` per symbol; `/api/scanner/rescan` POST returns new contracts; gameloop WS streams `view_state_to_ws` snapshots with delta compression (reuse existing `_compute_delta`/`_deep_equal`).

- [ ] **Step 1: Wire DI** — in `composition_root.py`, build `MLXInferenceAdapter` + `DhanMarketDataAdapter` + `PaperBrokerAdapter`, construct `QuantCoordinator`, register as singleton. Boot it in `main.py` lifespan `startup` and stop in `shutdown`.
- [ ] **Step 2: Repoint `_viewer_loop`** in `gameloop.py` to pull `coordinator.snapshot(symbol)` on a timer (existing delta compression reused); handle `subscribe`, `ping/pong`, `server_mode`, `symbol_switched`, `history_loaded`.
- [ ] **Step 3: Repoint REST** — `/api/system/config` (already exists, returns config), `/api/ai/history` (read `coordinator.llm_history(symbol)`), `/api/scanner/rescan` (call `coordinator.rescan()`).
- [ ] **Step 4: Write tests** with a fake coordinator: WS sends a snapshot with all contract keys; `/api/ai/history` returns history; `/api/scanner/rescan` returns contracts.
- [ ] **Step 5: Run** from `backend/`: `.venv/bin/python -m pytest tests/unit/api/ -q` → green.
- [ ] **Step 6: Commit**: `git add -A && git commit -m "feat: thin backend shell serves coordinator snapshots"`

---

### Task 7: Delete legacy decision pipeline + tests

**Files:**
- Delete: `backend/app/application/services/amt_service.py`, `session_event_router.py`, `entry_coordinator.py`, `exit_coordinator.py`, `trading_session.py`, `engine_lifecycle.py`, `stream_manager.py`, `watchdog_manager.py`, `quant_bridge.py`, `quant_signal_mapper.py`, all `session_*.py` managers, `state_snapshot_builder.py`, `state_broadcaster.py`
- Delete: `backend/app/application/handlers/` (amt_handler, entry_gate_coordinator, llm_entry_handler, llm_overseer_handler, post_trade_analyst, pre_candle_advisor, trade_lifecycle_handler, rl_handler)
- Delete: matching test files in `backend/tests/`
- Test: run full suites

**Interfaces:**
- Consumes: nothing (deletions only); Task 6 must already work end-to-end.

- [ ] **Step 1: `git rm`** every file listed. Search for dangling imports: `grep -rn "amt_service\|session_event_router\|entry_coordinator\|trading_session\|engine_lifecycle\|stream_manager\|watchdog_manager\|quant_bridge\|state_snapshot_builder\|state_broadcaster\|llm_entry_handler\|llm_overseer_handler\|post_trade_analyst\|pre_candle_advisor\|trade_lifecycle_handler\|amt_handler\|entry_gate_coordinator" backend/ --include="*.py"` and fix/remove any remaining references (main.py, composition_root.py, routers).
- [ ] **Step 2: Remove legacy tests** that target deleted modules (`backend/tests/unit/application/*`, `backend/tests/unit/domain/*` referencing them — run pytest and delete only the failing legacy files).
- [ ] **Step 3: Run** from `backend/`: `.venv/bin/python -m pytest tests/ -q` → all remaining tests green.
- [ ] **Step 4: Commit**: `git add -A && git commit -m "refactor: delete legacy AMT/gate/entry/LLM-handler pipeline"`

---

### Task 8: End-to-end verify + live restart

**Files:**
- None new; verification only.

**Interfaces:**
- Consumes: the full swapped stack.

- [ ] **Step 1: Run all suites**: from repo root `.venv/bin/python -m pytest tests/quant/ -q`; from `backend/` `.venv/bin/python -m pytest tests/ -q`.
- [ ] **Step 2: Restart backend** (from `backend/`): `GLASSYTRADE_ENV=paper GLASSYTRADE_STRATEGY=nse_options PYTHONPATH="/Users/apple/Documents/v5-of-glassytrade-ai:/Users/apple/Documents/v5-of-glassytrade-ai/backend" DEBUG=false nohup .venv/bin/python -u -m uvicorn app.main:app --host 0.0.0.0 --port 9090 > backend.log 2>&1 &`
- [ ] **Step 3: Verify health**: `curl http://localhost:9090/api/health` → `{"status":"ok", ...}` with `llm` check reflecting the ported adapter.
- [ ] **Step 4: Verify WS**: connect to `ws://127.0.0.1:9090/api/trading/ws/gameloop` with `{"subscribe":"NIFTY AUG FUT"}`; expect snapshots containing `_symbol, portfolio, amt, auction, quantDecision, genAIAnalysis, overseerAction, overseerReason, agentDecision, riskState, tick, ltp, oi, depth`.
- [ ] **Step 5: Confirm frontend** at :5190 loads with the same snapshot shape.
- [ ] **Step 6: Commit**: no code change → commit any leftover test/doc edits.
