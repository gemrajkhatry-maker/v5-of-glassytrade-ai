# AMT Strategy Cleanup — Results

**Date:** 2026-08-06 · **Branch:** stable_4 · **Plan:** docs/superpowers/plans/2026-08-06-amt-strategy-cleanup.md

## What shipped (7 commits, all TDD)

| Task | Commit | Result |
|---|---|---|
| T1 UI payload cut | `6afc4e9` | Removed 13 dead snapshot keys, 15 dead AMT DTO fields, `lotSize`, portfolio `history`; trimmed agentDecision + genAIAnalysis; frontend types + consumers updated, `npm run build` + 450 frontend tests pass |
| T2 AMT concurrency lock | `e0d34d5` | `AMTHandler._analyze_lock` (RLock) serializes per-symbol `analyze()`; `AMTService._state_lock` guards `_sync_underlying_state` |
| T3 entry-flow gating | `6448a16` | `is_new_candle` now meaningful (initialized at session create + written on every closed candle, not only signal build); entry LLM gated on candle + event triggers (market-state change, VWAP ±2σ cross, absorption/break) with 60s floor; deleted dead `run_overseer` block |
| T4 overseer gating | `a0682f7` | `pos_state` now carries stop_loss/take_profit/hold_time/risk_tier/daily_pnl/consecutive_losses/daily_loss_pct/symbol; `OVERSEER_COOLDOWN=15s` enforced; queue `maxsize=2` drop-busy |
| T5 LLM inputs | `bf8ae54` | Fixed VWAP key (`session_vwap` not `vwap`); added session_name/favor_strategy/gate_context/dev_*/iv/theta; removed worker hot-refresh (decision-consistent inputs); deduped CVD-DIVERGENCE block; single JSON instruction; moved DECISION HIERARCHY/AMT RULES to system instruction; removed 22 dead keys + dead helpers |
| T6 watchdog lifecycle | `52ac5ff` | SL-watchdog closes route through shared dedup + exit lifecycle (no duplicate `trades` rows); `ExitCoordinator.on_position_closed` idempotent; overseer gets broadcast bridge (immediate UI push) |
| Test cleanup | `ae9c723` | Removed dead episodic-memory source-string test (code deleted in T5) |

## Verified results

- **Tests:** 1819 passed / 77 skipped (only pre-existing env-broken suites ignored: aiohttp/httpx/gymnasium/starlette).
- **LLM cadence (live, 3 symbols, ~3.5 min):** 7 entry calls total (~2/min) vs the old 120/hr/symbol. Per-candle + event-trigger gate working.
- **LLM latency:** 2-5s per generation (early-stop active), GPU no longer saturated.
- **Prompt correctness (live DB):** `SESSION:` + `Session favors:` render (were absent); VWAP context renders (was absent); `CVD DIVERGENCE` deduped.
- **Stability:** 0 tick processing errors, 0 "dictionary changed size" crashes.

## Remaining known items (non-blocking)

- `iv`/`theta` default to 0.0 — AMTResult has no such fields yet; inert until the analyzer populates them.
- Post-trade `entry_context` uses close-time `sessionVwap` as proxy (entry VWAP not persisted in position metadata).
- `tick_processor.py` throttled agentDecision delta still carries slAdjust/tpAdjust/stopLoss/takeProfit (backend-side, frontend doesn't read them).
- Pre-existing env-broken test suites (aiohttp/httpx) remain ignored.
