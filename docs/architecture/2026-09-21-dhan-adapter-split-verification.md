# Dhan Adapter Split — Verification Report (v7 prune N5)

Date: 2026-09-21 · Node: N5 · Type: verify · Risk: money-path

## Verdict: the split is legitimate hexagonal architecture — do NOT merge

| Adapter | Port | Consumers | LOC |
|---|---|---|---|
| `dhan_adapter.py` (`DhanMarketDataAdapter`) | `IMarketData` — option chains, LTP, historical candles, lot sizes, symbol discovery | WS market streaming, scanner bootstrap | 565 |
| `dhan_broker_adapter.py` (`DhanBrokerAdapter`) | `IBroker` — order execution, stop placement, positions, order-status polling, durable order persistence | composition root (`_create_broker_adapter`), live OMS | 1,242 |

Both wrap the same SDK (`brokers.broker.dhan.application.broker.DhanBroker`)
but implement **different ports with disjoint method sets** — the only shared
surface is `__init__`-time broker construction and symbol/exchange mapping.
Merging them would couple feed health to order state and violate the
port boundary `tests/architecture` enforces.

## Genuine duplication found: none requiring extraction

Checked candidates:

- `_make_instrument` exists in both, but the two implementations answer
  different questions: the market-data one derives `Instrument` from a display
  symbol alone; the broker one derives it from a `Signal` + metadata
  (`security_id`, `option_type`, exchange hints). Forcing one function to serve
  both would add flag-driven branching — worse than the small textual overlap.
- `classify_symbol` / `_exchange_enum` are already centralized in
  `_dhan_common.py` and imported by both adapters. No further dedupe target.
- `_format_time`, `_is_terminal`, `_is_filled` live only in the broker adapter
  (order-feed concerns); the market-data adapter has no equivalents.

## Changes made

None. This node's original hypothesis ("merge the two adapters") was
**refuted by inspection**; per the v7 conventions, the finding is corrected in
place rather than shipping a destructive merge. The audit's original
"two Dhan adapters = duplication" claim in
`docs/architecture/2026-09-21-v7-prune-execution-graph.json` (node N5 evidence)
is superseded by this report.

## Follow-up (optional, not filed as work)

`dhan_broker_adapter.py` at 1,242 LOC mixes three concerns (order execution,
order-status polling/feed, persistence hooks). If it keeps growing, split by
concern into `execution` / `order_status` / `persistence` — port-preserving,
no behaviour change. Not needed for the Fabio path.
