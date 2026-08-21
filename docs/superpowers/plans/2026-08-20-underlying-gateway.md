# Wire Underlying Gateway (Fabio Task 8) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make option engines run AMT analysis on the underlying futures auction instead of the option's own premium, so direction/absorption/CVD/VA are computed on the correct (liquid) market.

**Architecture:** `multi_engine._spawn_engine` builds a `QuantEngine` per symbol but does NOT pass `underlying_gateway`, so `runtime.run()` falls back to analyzing the option premium (logged warning "running AMT on the option premium"). The `underlying_gateway` path already exists in `runtime.py:208-244` — it subscribes a second feed and feeds the *underlying* ticks to the aggregator/AMT, using the option tick only for quotes/depth/fills.

**Tech Stack:** Python 3.13; `LiveGateway` (multi_engine), `QuantEngine` (runtime), `ExchangeConfig.extract_underlying` (existing).

## Global Constraints

- Do NOT loosen any threshold (absorption/acceptance/CVD) — this change must only make the *data* correct, not the *signal* easier.
- Futures symbols are already streamed as separate engines; options must subscribe to the SAME futures feed (no new market data source).
- Real-money: verify with synthetic test before restart.

---

### Task 1: Resolve option → futures symbol mapping ✅

**Files:**
- Modify: `quant/multi_engine.py` (add a resolver using `ExchangeConfig.extract_underlying` + `_resolve_futures_symbols`)

**Goal:** Given an option symbol (`CRUDEOIL 17 SEP 8200 CALL`), find the full underlying futures symbol (`CRUDEOIL SEP FUT`) that already has a live gateway.

- [x] Read `_resolve_futures_symbols` (multi_engine.py:176) to see the exact futures symbol format produced.
- [x] Read `ExchangeConfig.extract_underlying` (quant/contracts/exchange_config.py) to see the option→underlying name mapping.
- [x] Add `_underlying_futures_symbol(option_symbol) -> str | None` that maps an option to its futures symbol (via `_build_futures_map` keyed by `extract_underlying` root). Returns None for futures/non-options.

### Task 2: Wire `underlying_gateway` in `_spawn_engine` ✅

**Files:**
- Modify: `quant/multi_engine.py:298-318`, `quant/brokers/multiplexed_feed.py`, `quant/brokers/live_gateway.py`, `quant/runtime.py`, `quant/amt_engine.py`

- [x] In `_spawn_engine`, resolve the option's underlying futures symbol and pass `underlying_gateway` to `QuantEngine` only for option symbols.
- [x] **Fan-out discovery:** a naive second `LiveGateway` on the futures symbol would steal ticks from the futures engine (one queue per symbol). Added `MultiplexedMarketFeed.add_reader/remove_reader` — a per-symbol fan-out reader queue that receives a COPY of every tick, so the option engine's underlying gateway never starves the futures engine. `LiveGateway` gained a `reader_queue` mode (passive reader, never unsubscribes the shared symbol).
- [x] Underlying gateway tracked in `_underlying_gateways` and closed in `_stop_engine`.
- [x] `seed_symbol` added to `QuantEngine`/`AMTEngine` so the option engine seeds its AMT profile from the FUTURES history (not its own premium) — consistent with futures live bars.

### Task 3: Synthetic test — option engine uses underlying AMT ✅

**Files:**
- Test: `tests/quant/test_underlying_feed.py` (extended), `tests/quant/test_multiplexed_feed.py` (fan-out)

- [x] Existing Task 8 tests pass: with an underlying gateway, bars close from the futures stream, option ticks only drive quotes/depth.
- [x] `test_seed_symbol_uses_underlying_futures_history` — seed fetches the futures history, not the option premium.
- [x] `test_add_reader_fans_out_full_stream_to_each_reader` / `test_remove_reader_wakes_blocked_reader` — the fan-out reader sees the full stream and never steals ticks.

### Task 4: Restart + verify

- [ ] `./start.sh mcx`, then monitor `backend.log` for options producing non-`VA_FADE` approvals and the "running AMT on the option premium" warning disappearing.
