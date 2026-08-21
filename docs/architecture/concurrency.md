# Concurrency Architecture — GlassyTrade quant core

One page. Read this before touching any thread, lock, or shared dict in
`quant/`. These invariants are enforced by convention; violations caused
every production bug in the 2026-08-21 incident chain.

## Thread inventory

| Thread | Count | Role | Must never |
|---|---|---|---|
| Feed producer | 1 | Sole WS consumer; converts packets to ticks; sole writer of `_prev_cum/_prev_price/_prev_ts/_depth_cache` | Block on engine state |
| Engine (`quant-{symbol}`) | N (one per contract) | Owns that symbol's ENTIRE trading state: position, OMS, PositionManager, SessionRisk, bar_index | Read another engine's state |
| AMT seed (`amt-seed-*`) | ≤2 per engine (daemon) | REST history seeding; check-and-set under `_amt_lock` | Outlive warmup |
| Event loop (uvicorn) | 1 | HTTP + WS viewers; reads snapshots only | Call anything blocking (`join`, broker I/O, file I/O on hot paths) |

## State ownership (three tiers)

1. **Thread-confined** — no locks needed, never touched cross-thread:
   `QuantEngine._position`, `_bar_index`, `_oms`, `_pos_mgr`, `_risk`
   (engine-local instance), aggregator, AMT candle ring (via `_amt_lock`).
2. **Shared read-mostly, guarded** — `StateProjector` (single `RLock`,
   folded only from `_emit`, read from event loop), `SessionLevelStore`
   (single `RLock`, JSON flush under it), coordinator `_engines/_gateways`
   dicts (`_lock`, copy-out pattern).
3. **Single-writer, lock-free reads** — feed baseline dicts (producer
   writes; GIL-atomic dict ops make races benign drops). Do not add locks
   to one side only — see the comment block in `MultiplexedMarketFeed.__init__`.

## Lock inventory & ordering

| Lock | Protects | Notes |
|---|---|---|
| `MultiplexedMarketFeed._lock` | queues/readers dicts | Never held while blocking |
| `QuantEngine._emit_lock` | bus publish + trace + projector fold | The engine's outermost lock |
| `StateProjector._lock` | view state | Acquired only inside `_emit_lock` or alone — **no inversion possible** |
| `SessionLevelStore._lock` | levels/npocs/kv + disk flush | `RLock`; reentrant by design |
| `AMTEngine._amt_lock` | candle ring / incremental profile | Short critical sections only |

Ordering rule: `_emit_lock → projector._lock` is the only legal nesting.
Never acquire a feed or store lock while holding an emit lock.

## Event bus contract

All `EventBus.subscribe` calls happen **before** engines start. Publishing
is lock-free by design; runtime subscription is unsupported (documented on
the class).

## Event loop rule (the one that bit us twice)

Anything that can block >10ms goes through `asyncio.to_thread`:
- `coordinator.rescan()` (done)
- `coordinator.switch_symbol()` (joins threads, may init broker) (done)
- Any future endpoint touching `fetch_history`, broker auth, or file writes

## Price-scale separation (option engines)

An option engine holds TWO AMT engines: underlying futures (decision
evidence, futures price scale) and the option itself (tradable scale).
Futures bars NEVER drive entries/exits; a signal >5× or <⅕× the option's
LTP is dropped by the scale gate (`[SCALE GUARD]` log). `SessionRisk`
rejects any persisted `|daily_pnl| > 50%` of starting equity on load.

## Incident history (why these rules exist)

- 2026-08-21: blocking `next_tick()` in the underlying drain starved
  option engines → snapshots emitted futures-scale AMT for options.
- 2026-08-21: futures bars drove option decisions → futures-priced fills
  on option instruments → ₹cr-scale phantom P&L, persisted across restarts.
