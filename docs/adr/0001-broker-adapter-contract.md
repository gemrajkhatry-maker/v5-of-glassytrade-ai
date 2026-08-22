# ADR-0001 — Broker Adapter Contract Rules

**Status:** Accepted
**Date:** 2026-08-22
**Context:** Deep architectural audit (shotgun surgery / coupling pass) — every
duplication finding across the Dhan/Upstox broker pair traced to mirrored
normalization logic that must change in lockstep. This ADR pins the shared
vocabulary a new broker adapter must use, and the guardrails that keep it
enforced.

---

## 1. Order-type mapping lives in `common/order_types.py` — once

The domain `OrderType` → wire-string mapping (and its reverse) is *mirrored*
logic: Dhan (`STOP_LOSS`/`STOP_LOSS_MARKET`) and Upstox (`SL`/`SL-M`) collapse
`STOP_LIMIT` and priced-`STOP` to the same native string. When the domain enum
grows, **every** adapter must change.

**Rule:** an adapter never re-implements the STOP-mapping `if` chain. It
declares its native names and delegates:

```python
# dhan/client.py
return native_order_type(request, base="STOP_LOSS", market="STOP_LOSS_MARKET")
# upstox/client.py
return native_order_type(request, base="SL", market="SL-M")
```

Reverse mapping uses `domain_order_type(value, base=..., market=...,
has_price=...)`. One caveat is **not** shared: Upstox's `SL` always
reverse-maps to `STOP_LIMIT` (pass `base_is_stop_limit=True`); Dhan
disambiguates by price. Do not "simplify" this — it is broker wire behavior.

## 2. Response order-id extraction uses `response_order_id()`

`order_id`/`orderId` keys + plural-list fallback + missing-id error are
identical across brokers. An adapter with provider-specific keys (Dhan eDIS
`authorizationId`) passes them as the `primary` override and delegates the
rest. Do not re-implement the fallback chain.

## 3. Live order-stream fills override price with the traded price

Order-stream updates report the *limit* price; fills trade at the traded
price. `common/order_types.stream_order_price(order, row, traded_keys=...)`
performs the override for `FILLED`/`PARTIALLY_FILLED` rows. Adapters declare
their row keys (Dhan `tradedPrice`/`traded_price`, Upstox `average_price`) and
empty-value policy via `excluded` (Upstox excludes `0`). The fill bridge
depends on this — a fill priced at the limit price instead of the trade price
is a silent accounting divergence.

## 4. Protective-price invariants are broker contracts — never "simplified"

- Dhan super orders require `price`, `target_price`, `stop_loss_price` with a
  BUY/SELL price ordering invariant (`stop < price < target`).
- Dhan/Upstox forever orders require both `price` and `trigger_price`.

These encode live API validation. A refactor may move them, not weaken them.

## 5. Position/account rows use `common/portfolio.py`

Raw REST position rows → `Position` uses `positions_from_rows(rows, registry=...,
spec=PositionRowSpec(...))`; each broker declares its row-key layout as a
frozen spec (Dhan `securityId`/`netQty`, Upstox `instrument_token`/`quantity`).
Account snapshots use `normalize_account()`. New position fields are added in
the shared builder once.

## 6. Instrument identity goes through the registry

Instrument resolution always uses `registry.resolve()`; never hand-parse
provider keys. Master-backed metadata (tick size) is applied via
`instrument_from_registry` so contracts carry tick math into quotes and
analytics.

---

## Guardrails (Phase 5)

1. **Dependency direction** — `domain ← brokers ← trading`, never reverse.
   Enforced statically by `trading/tests/architecture/test_fitness_checks.py`
   (runs in CI). The check scans raw source text, so **do not mention
   `tradex_trading` in broker docstrings/comments**.
2. **Mode branches** live only in `runtime/startup.py` (fitness check #4).
3. **Shared helpers before new code** — when a new adapter needs order-type,
   order-id, stream-order-price, or position-row logic, extend
   `common/order_types.py` / `common/portfolio.py`. Duplicating an `if`
   chain from an existing adapter fails review.
4. **CI gates** — `mypy src` and `ruff check src` run per package in CI
   (`.github/workflows/test.yml`); both must be clean on every PR.
5. **`__all__` declarations** on every shared module so the public surface is
   explicit.
6. **Knowledge graph** — run `graphify update .` after structural changes;
   optionally `graphify hook install` for post-commit refresh.
