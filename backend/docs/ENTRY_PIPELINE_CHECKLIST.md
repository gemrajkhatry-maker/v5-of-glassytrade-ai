# Entry pipeline ops checklist (tick → EXECUTING)

Single-source runbook for **why a candle may produce no trade** and **what must pass before `EXECUTING` appears in logs**.  
Execution is **quant-first** (LightGBM agent + gates); the LLM path enriches the UI and can record `QUANT_*` bypass reasons when session or regime blocks inference.

## 1. Data path

| Step | What happens | Code |
|------|----------------|------|
| Tick in | `TickReceived` updates buffers, portfolio, caches | `TradingSession._on_tick` |
| Session / venue | Phase check, profile persistence; MCX options use **resolved** session market (not default exchange only) | `_session_phase_check`, `resolve_session_market` |
| AMT | Volume profile, POC/VA/LVN, market state, aggression | `AMTHandler` / `amt_analyzer` |
| Agent | Features → `run_agent_pipeline` → direction, probability, regime | `SessionEventRouter.run_micro_agent_pipeline` |

## 2. Preconditions for **any** live entry (`run_entry` flag)

From `_resolve_entry_decision` and `execute_entry_path`:

1. **No open position** on symbol; **not** in lifecycle cooldown (trading-session cooldown).
2. **Agent**: direction `LONG` or `SHORT` and **`probability >= AGENT_DECISION_THRESHOLD`** (default **0.55**, `app.domain.constants`).
3. If **SHORT**: `allow_short` must be true.
4. **≥ 60 s** since last execution attempt on that session (`_last_exec_mono` monotonic spacing).
5. **Session risk** allows trading (`SessionRiskManager.can_trade`).
6. **`run_gate_pipeline`** passes (hard + soft gates, R:R, structure, etc.).
7. If **SHORT**, **`evaluate_short_gates`** passes.
8. **`build_entry_signal`** returns a signal; broker / thesis checks in `EntryCoordinator` succeed.

**High block rate is expected** when confluence is missing (Fabio-style selectivity).

## 3. LLM path (parallel, not the primary trigger)

| Check | Effect |
|--------|--------|
| `LLMEntryHandler.should_run` | Degenerate AMT (POC/VAH ≤ 0), `ai_running`, open position, model not ready, **30 s** LLM spacing, AMT `DEAD` → skip |
| `get_session_info` + `allow_entry` | If false → `last_ai_analysis.raw_output == QUANT_PHASE_BLOCKED`, LLM not called |
| `_build_market_data_ai` | Agent `regime == DEAD` → `QUANT_DEAD_MARKET`, LLM not queued |

See also: `tests/unit/application/test_llm_session_market_resolution.py` for venue resolution.

## 4. “Money” bar (outside this checklist)

Positive expectancy and drawdown limits are **not** proven by unit tests. Use **paper/live history** in SQLite and **`scripts/paper_trade_kpis.py`** (or `scripts/run_backtest.py`) on closed trades.

## 5. Log anchor

When everything on the **quant path** passes, you should see:

`EXECUTING: <symbol> dir=<LONG|SHORT> P=<prob> via AMT pipeline`

in `SessionEventRouter.execute_entry_path` — that is the point just before `EntryCoordinator.execute_signal`.
