# Persistence Layer Audit (v7 prune N8)

Date: 2026-09-21 · Node: N8 · Type: verify (NO deletions — see Hard Rule)

## The six layers, by concern

| Concern | Authoritative writer | Read path | Notes |
|---|---|---|---|
| **Event sourcing / replay** | `quant/event_store.py` `EventStore` (892L) — checksum-chained in-memory append log, owned per-engine (`runtime.py:434` via `EventAppender`) | `EventExport` sequence, `verify_chain`, certification battery | The "source of truth" *within* an engine process. Not shared across processes. |
| **Tick/decision journal (JSONL)** | `quant/persistence.py` `Journal` — rotated JSONL segments subscribed to the engine bus | `replay()` (determinism tests) | Diagnostics + replay input; never read back into decisions. |
| **Position/fill book (durable)** | `backend/app/infrastructure/storage/database.py` `SQLiteStorageAdapter` (1,121L) implements `IStorage` — trades, fills ledger, orders, open positions, session profiles, ticks | restart reconciliation (`startup_reconciliation.py`), WS views | The only **cross-restart durable** store. |
| **Event → storage projection** | `quant/persistence_bridge.py` `PositionStorageBridge` — subscribes PositionOpened/Reduced/Closed on the bus, writes via `IStorage` | none (write-only projection) | This is a *bridge*, not a layer: it moves facts from the event loop into SQLite. Alive — imported by `runtime.py`. |
| **Append safety boundary** | `quant/persistence_boundary.py` — `EventAppender` + `PersistenceHealth` port around `EventStore` | health checks, startup gates | Small (well under 100L); prevents silent event loss after storage failure. Alive. |
| **Post-trade analytics journal** | `backend/app/application/services/trade_journal.py` `TradeJournal` (1,031L) — markdown/JSON trade narratives in `live_trading_logs/` | humans, reports | Read-only w.r.t. decisions; observational. |

## Verdict per layer

1. `event_store.py` — **authoritative** for in-process event truth. Keep.
2. `persistence.py` (Journal) — **authoritative** for replayable tape. Keep.
3. `database.py` — **authoritative** for durable cross-restart state. Keep.
4. `persistence_bridge.py` — **alive projection** (runtime import verified).
   Keep. Do not confuse "bridge" with "duplicate".
5. `persistence_boundary.py` — **alive safety boundary**. Keep.
6. `trade_journal.py` — **analytical projection**, no decision authority. Keep.

## Duplication assessment

The layer count (6) looks bloated but the **authorities do not overlap**:
each concern has exactly one writer, and the two projections (bridge,
trade journal) read from distinct sources (event bus vs engine snapshot).
The real cost is **surface area**, not duplication:

- `database.py` mixes tick buffering, trade ledger, orders, positions,
  session profiles, and performance snapshots in one 1,121L adapter.
- `trade_journal.py` at 1,031L mixes logging with analytics computation.

## Follow-up candidates (NOT executed here — need their own nodes)

- **N10 (candidate):** split `SQLiteStorageAdapter` by concern
  (`ticks` / `trades` / `orders` / `positions` / `profiles`) behind the
  unchanged `IStorage` port. Port-preserving, no behaviour change.
- **N11 (candidate):** extract `TradeJournal` analytics (breakdowns,
  performance metrics) into a pure query service; journal becomes thin IO.

Both require their own footprints and merge gates per the v7 conventions;
`runtime.py` (co-owned) is not touched by either.
