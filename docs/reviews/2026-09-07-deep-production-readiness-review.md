# Deep Production Readiness Review

## Indian NSE/MCX Futures and Options Platform

> **Review date:** 2026-09-07  
> **Scope:** A second, deeper, read-only audit after
> `docs/reviews/2026-09-06-valentini-guide-platform-review.md`.
>
> **Question:** Are we building the right system, and is it safe to move
> toward live Indian futures/options trading?

## Executive verdict

**The architecture is promising for research and paper trading, but this is
not ready for live money.** The main reason is not strategy quality. The
main reason is that market-risk truth can diverge from engine state in
several failure modes:

1. The engine stop is primarily local and tick-driven. A protective Dhan stop
   order is not placed for the normal entry path.
2. A broker outcome that is unknown after an exception can be persisted as
   `REJECTED`.
3. A one-lot option partial close can produce a non-lot quantity.
4. Startup reconciliation compares mostly symbol presence, not exact side,
   quantity, contract identity, or pending orders.
5. Risk recovery can start fresh after storage/load failure, and aggregate
   portfolio limits default to 95% of capital.
6. The option engine currently uses normalized option candle delta as
   `option_delta` for underlying-to-option stop translation. That field is
   order-flow delta, not an option Greek delta.

The correct next step is **risk and truth infrastructure**, not adding more
signals. Keep the AMT strategy mostly stable while closing the release
blockers below.

---

## Evidence and validation

### Repository and graph

- Existing Graphify graph was refreshed after the latest refactors.
- Graph size: **13,424 nodes, 30,539 edges, 511 communities**.
- Graphify confirmed the active relationships among `Tick`,
  `MultiplexedMarketFeed`, `BarAggregator`, `QuantEngine`, `LiveOMS`,
  `DhanBrokerAdapter`, `OrderFilled`, `OptionSelector`, and
  `startup_reconcile`.
- Because the graph exceeds 5,000 nodes, Graphify used an aggregated
  community view rather than a full node-level visualization.

### Tests

- Targeted current regression suite: **68 passed**, 1 dependency warning.
- The previous full quant baseline was **1764 passed, 11 skipped** before
  the latest broker-domain refactors. A full suite should be rerun after
  the next source change and before release.
- No application was launched, no broker/network calls were made, and no
  source files were changed during this audit.
- The previous dirty worktree was preserved.

### Prior review status

The earlier incremental-profile duplicate-volume finding is **closed in the
current source**. `quant/amt/profile/volume_profile.py:429-432` now adds each
bucket's total exactly once, and a direct full-vs-incremental check matched
volume, buy volume, and sell volume.

The following previous findings remain open:

- directionless aggression scoring;
- directionally blind CVD confirmation in IMBALANCED state;
- scanner/selector liquidity threshold drift;
- range bars not being the live default;
- LiveOMS pyramids intentionally disabled.

---

# 1. Release-blocking findings

## P0-1. Normal entries do not place a broker-native protective stop

**Evidence:**

- `backend/app/infrastructure/adapters/dhan_broker_adapter.py:186-205`
- `brokers/broker/dhan/application/order_converter.py:124-165`
- `quant/execution/exits.py:119-190`
- `quant/runtime.py:580-582`

The normal engine entry signal has `signal.stop_loss`, but the adapter maps an
unspecified order type to `MARKET` and then converts it to a marketable
`LIMIT` entry (`dhan_broker_adapter.py:196-205`). It sets
`trigger_price = 0.0` for that entry. The converter is capable of sending
Dhan `STOP_LOSS`/`STOP_LOSS_MARKET` payloads, but the live path does not place
a separate protective stop after the entry fill.

The configured stop is therefore primarily enforced by:

```text
Dhan tick → MultiplexedMarketFeed → QuantEngine._manage_tick_exit()
```

That is useful, but it is not an exchange/broker-native protection. If the
process, feed, event loop, or network fails after the entry, the position can
remain unprotected until the EOD watchdog. `multi_engine.py:834-870` is a
square-off backstop, not a stop-loss mechanism.

### Required design

Choose one explicit production model:

1. **Broker-native protective stop:** after entry fill, place and persist a
   linked stop order; update/cancel it on every stop move; reconcile it by
   broker order ID; or
2. **Strict local-stop model:** document that it is not crash-safe, prohibit
   live trading, and require a separate supervisory risk daemon with
   independent connectivity.

For real live trading, use option 1. The stop lifecycle must be part of the
position state machine, not a comment on the signal.

**Release gate:** Kill the process and disconnect the feed immediately after
an entry in a test broker. The broker must still hold an active protective
stop, or live mode must refuse to start.

---

## P0-2. Unknown broker outcomes can become `REJECTED`

**Evidence:** `backend/app/infrastructure/adapters/dhan_broker_adapter.py:219-249`
and `:355-362`.

The entry path correctly persists `SUBMITTED` before `place_order`. It also
correctly persists `UNKNOWN` for one specific timeout/cancel-failure path.
However, the broad handlers catch all `DhanError` and `Exception` and persist
`REJECTED`:

```python
except DhanError:
    self._persist_order_terminal(signal, "REJECTED")
except Exception:
    self._persist_order_terminal(signal, "REJECTED")
```

A transport timeout or exception can occur after Dhan accepted the order but
before the response reaches this process. Recording `REJECTED` then permits
operators and recovery logic to believe there is no exposure, while the
broker may hold a live position.

### Required design

- Classify pre-ack network/timeout/connection failures as `UNKNOWN`, never
  `REJECTED`.
- Query the broker by correlation ID/order ID when possible.
- Keep `UNKNOWN` orders in a quarantine state until resolved.
- Never resubmit an unknown entry automatically.
- Require reconciliation before any new order for the same root.
- Add tests for: accepted-at-broker + lost response, polling exception,
  process crash after POST, and restart with an unresolved order.

---

## P0-3. Risk state can fail open after restart or storage failure

**Evidence:** `quant/execution/risk.py:70-130, 132-150`.

`SessionRisk._load()` catches every load exception and starts with fresh risk
state. `_save()` treats missing storage as success, and `record_trade()` only
logs when persistence fails (`:186-193`). This can erase:

- daily loss;
- consecutive-loss streak;
- trade count;
- an active halt;
- the equity basis used for sizing.

`SessionLevelStore` correctly returns a boolean for disk flush success
(`quant/session_levels.py:169-196`), but not every caller treats a false result
as a trading block. A live risk authority cannot silently downgrade to
in-memory state.

### Required design

- Live mode must refuse entries if risk state cannot be loaded.
- Live mode must refuse entries after a failed risk-state write.
- Risk state needs a durable version, checksum, trading date, account ID,
  and monotonic update sequence.
- Corrupt state must be quarantined, preserved, and surfaced. It must not be
  reset to zero and resumed.
- Paper/replay may explicitly opt into memory-only state, but that mode must
  be visible in runtime configuration.

---

## P0-4. Corrupt P&L is reset and trading resumes

**Evidence:** `quant/execution/risk.py:103-125`.

If persisted daily P&L exceeds 50% of starting equity, the code treats it as
corrupt, resets P&L, clears loss counters and halt state, and persists the
reset. This is dangerous even if the original value really is corruption:

- the reset destroys the evidence needed to diagnose it;
- it can clear a safety halt;
- the system can resume with an untrusted equity/risk basis.

### Required design

Use a `QUARANTINED` state, retain the original record, stop live order
submission, emit a critical alert, and require explicit operator
acknowledgement or a signed recovery action. Never auto-unhalt from a
cross-scale anomaly.

---

## P0-5. Aggregate portfolio risk defaults to 95% of capital

**Evidence:** `quant/execution/portfolio_risk.py:25-34`.

```python
max_portfolio_risk_pct = 0.95
max_portfolio_daily_loss_pct = 0.95
```

These defaults are incompatible with the local per-engine risk design, whose
default daily loss is 2% and risk per trade is 0.25%-0.50%. If portfolio
configuration is omitted or incorrectly wired, the aggregate authority can
permit approximately 95% open risk and a 95% realized daily loss.

The fact that normal sizing may not immediately reach the limit does not make
the default safe. The authority is the last safety ceiling and must fail
closed.

### Required design

- Set a conservative default, for example a documented 2%-5% aggregate open
  risk ceiling depending on account policy.
- Require explicit live configuration for any larger limit.
- Validate the limit at boot against per-trade and max-position limits.
- Refuse live startup for missing/invalid portfolio risk configuration.
- Emit immutable config provenance in the startup audit.

---

## P0-6. Option `option_delta` is not an option Greek delta

**Evidence:**

- `quant/amt/session/structure.py:144-150`
- `quant/amt/dto.py:141-143`
- `quant/decision/context_builder.py:395-399`
- `quant/runtime.py:869-894`
- `quant/amt/session/selector.py:439-447`

`compute_per_symbol_delta()` returns:

```python
option_tick.delta / option_tick.volume
```

This is normalized candle/order-flow delta in the range `[-1, +1]`. It is not
Black-Scholes/chain Greek delta. The value is serialized as
`deltaNormalizedOption`, then `DecisionContextBuilder` assigns it to
`DecisionContext.option_delta`. The runtime passes it to
`translate_underlying_signal_to_option()`, where it scales the underlying
stop and target as though it were option Greek delta.

This can produce materially wrong premium stops and lot sizing. The scanner
has chain Greek delta (`scanner.py:82-84, 209-216`), but the selected result's
Greek delta is not carried into the live engine construction path. When the
normalized value is zero, the code silently falls back to 0.50, which masks
the missing data instead of rejecting the trade.

### Required design

Separate fields and types:

```text
orderflow_delta_ratio: candle delta / volume
option_greek_delta: option-chain Greek delta
```

Carry the selected contract's dated chain snapshot and Greek delta into the
engine. Reject option buying when the Greek is absent or stale. Never use a
candle delta ratio to map an underlying stop into an option premium stop.

---

# 2. High-severity execution and reconciliation gaps

## P1-1. Partial close uses requested quantity, not actual broker fill

**Evidence:** `quant/execution/live_oms.py:215-290`.

The requested close size is calculated as `position.size * fraction` and
truncated with `abs(int(closed_size))`. After the broker responds,
`filled_qty` is read but not used to construct the remaining position or P&L.
The code books:

- requested-size P&L;
- requested-size reduction;
- a quantity that may not match the broker fill.

A partial fill can therefore overstate realized P&L and make the engine think
it holds less than the broker actually holds.

### Required design

- Use actual `filled_qty` for P&L and remaining quantity.
- Preserve unfilled residual as open exposure.
- Persist the close order and its fill quantity.
- Reconcile the engine position to broker net quantity before allowing a new
  order.
- Keep all derivative quantities lot-valid. For a one-lot option position,
  disable fractional TP or close the whole lot. Do not submit 32 units of a
  65-unit NIFTY lot.

The conformance tests currently document the difference between PaperOMS
float slices and LiveOMS integer truncation
(`tests/quant/execution/test_oms_conformance.py:12-23, 256-269`). That is a
known semantic gap, not a safe production behavior.

---

## P1-2. Close orders do not have the entry order's durable lifecycle

**Evidence:** `backend/app/infrastructure/adapters/dhan_broker_adapter.py:364-525`.

Entry orders persist `SUBMITTED` and terminal state. Close orders create a
stable correlation ID (`:432-440`) but do not persist `SUBMITTED`, broker
order ID, `UNKNOWN`, actual fill quantity, or terminal close state. A process
crash during close can leave a broker order in flight without a durable close
record.

The local engine retains the position and retries in some cases, which is
better than assuming success. It is not sufficient for proving exactly-once
flattening across restart.

### Required design

Use a single durable order state machine for entries, partial exits, full
exits, fallback closes, and protective stops:

```text
INTENT → SUBMITTED → ACKED → PARTIAL → FILLED
                    ↘ UNKNOWN → RECONCILE_REQUIRED
                    ↘ REJECTED/CANCELLED
```

Every state transition should include logical ID, broker order ID, symbol,
security ID, exchange, side, requested quantity, filled quantity, average
price, and timestamps.

---

## P1-3. In-process duplicate guard is never cleared

**Evidence:** `backend/app/infrastructure/adapters/dhan_broker_adapter.py:171-185`.

`signal_id` is added to `_executing_signal_ids`, but the visible execution
path has no `finally` removal. This is useful for preventing duplicate
submission, but it can permanently block a retry for the life of the process
after a rejected or unknown outcome. On restart the in-memory guard disappears,
so the durable order state must be the authority.

### Required design

- Make the guard stateful by outcome, not a permanent set.
- Clear only after a terminal, reconciled outcome.
- Keep `UNKNOWN` blocked across restart using durable storage.
- Use a durable uniqueness constraint on logical order ID.
- Never treat “not currently in this process's set” as permission to submit.

---

## P1-4. Startup reconciliation is presence-only

**Evidence:** `backend/app/domain/ops/startup_reconciliation.py:119-145`.

The code explicitly compares presence, not sizes, and calls the reconciliation
service without metadata. It does not prove equality of:

- side;
- signed quantity;
- exchange segment;
- Dhan security ID;
- product type;
- average entry price;
- pending/open orders;
- protective stop orders.

The live startup gate at `backend/app/main.py:438-459` compares only DB and
broker position **counts**. Equal counts with the wrong contracts or opposite
sides can pass this check.

### Required design

Make reconciliation exact and fail closed:

```text
engine position ↔ broker position ↔ durable order/stop ledger
```

Use `(exchange, security_id, symbol)` identity, signed quantity, side,
product, and tolerance-bounded average price. Reconcile pending orders before
starting engines. Quarantine every mismatch; do not silently delete or adopt.

---

## P1-5. Broker query failure is not itself a successful reconciliation

`StartupReconciliation.reconcile()` records broker query errors and continues
(`startup_reconciliation.py:99-117`). The application-level live gate does
raise if the startup reconciliation call itself raises, so the current
composition path is safer than the domain function alone. Nevertheless, a
future caller can consume a result containing `broker_positions=0` after a
query failure.

### Required design

Return an explicit `UNKNOWN` reconciliation status, not an empty broker list.
The live gate must require:

```text
query succeeded
exact comparison completed
zero unresolved mismatches
```

No caller should be able to interpret an unavailable broker as “broker is
flat.”

---

## P1-6. Stop-gap loss is understated in bar-driven paths

**Evidence:** `quant/execution/exit_checks.py:26-32`,
`quant/execution/exits.py:136-149`.

A bar crossing the stop returns the configured stop price, not the observed
bar extreme or an adverse gap fill. The tick path can capture a real tick
price when ticks arrive, but a feed gap, sparse option, or bar-only replay
will book the configured stop. This makes loss, daily P&L, and performance
optimistic exactly in the failure modes that matter most.

### Required design

- Define stop-fill policy separately for live, paper, and replay.
- For a gap through stop, book worst observable executable price or a
  configured gap/slippage model.
- Treat no quote / locked limit / illiquid option as a distinct unresolved
  execution state.
- Add gap-through and feed-starvation acceptance tests.

---

## P1-7. Risk reservation is not a single explicit reserve transition

**Evidence:** `quant/runtime.py:985-1000`,
`quant/execution/portfolio_risk.py:40-99`.

`can_accept()` and `register_open()` each lock internally, while the engine
calls them separately. `register_open()` repeats important checks, so this is
not an immediate capacity bypass. It is still the wrong contract for a live
risk authority: approval and reservation are two API calls with a race window,
and order outcome reconciliation is not part of the same transition.

### Required design

Expose one atomic operation:

```text
reserve(signal_id, symbol, risk, expiry) -> reservation token
```

Consume or release that token exactly once when the broker outcome is
reconciled. Include idempotency and durable recovery for reservations.

---

# 3. High-severity market-data and contract issues

## P1-8. Dhan tick delta is a proxy, not exchange aggressor delta

**Evidence:** `quant/brokers/multiplexed_feed.py:68-166, 520-524`.

The feed correctly avoids treating Dhan `total_buy_qty` and
`total_sell_qty` as traded buy/sell splits. It converts cumulative volume to a
delta and classifies buy/sell using uptick/downtick and bid/ask location.
That is an engineering compromise, not true aggressor-side trade data.

Consequences:

- CVD is a proxy;
- absorption direction is probabilistic;
- footprint imbalances are inferred;
- backtest data must use the same attribution model or results will not be
  comparable.

This is acceptable for a research signal, but it must be exposed as a data
quality grade. Do not describe it as exchange-true order flow.

### Required design

Add `delta_source` and `data_quality` to each bar/decision, for example:

```text
EXCHANGE_AGGRESSOR, BID_ASK_TICK_RULE, PRICE_DIRECTION_PROXY, UNKNOWN
```

Gate high-conviction setups when data quality is below the required level.

---

## P1-9. Range/profile model is still synthetic when using OHLC bars

`quant/amt/profile/volume_profile.py:275-317` distributes candle volume
uniformly across the candle high-low range unless concentrated mode is used.
`quant/amt/orderflow/footprint.py:24-99` uses Gaussian allocation for the
chart footprint when tick data is unavailable.

These are reasonable visualization approximations, but they are not actual
volume-at-price. POC, LVN, HVN and stacked imbalance conclusions should not
be treated as equivalent to a real tick footprint.

The live `TickFootprintAccumulator` is realer and is active through
`AMTEngine.on_tick()`, but the fallback path remains synthetic and the DTO
does not make the distinction prominent enough for decision governance.

### Required design

- Mark every profile as `TICK_EXACT`, `CANDLE_DISTRIBUTED`, or
  `CANDLE_GAUSSIAN`.
- Do not allow high-conviction footprint setups from synthetic data unless
  explicitly configured.
- Validate total volume, buy/sell volume and delta invariants at every
  conversion boundary.

---

## P1-10. Underlying futures fallback is not contract-safe

**Evidence:** `quant/multi_engine.py:1289-1312`.

The preferred path calls `market_data.get_nearest_futures()`, which is good.
But if it returns nothing, the code synthesizes:

```python
f"{root.upper()} {month_str} FUT"
```

That fallback does not prove the contract exists, is the correct expiry, or
has the correct Dhan security ID. It can also choose the current calendar
month even when the nearest valid contract has rolled or the current contract
is expired.

`UnderlyingFuturesProvider` also intentionally derives a display-style
`ROOT MON FUT` symbol (`futures_provider.py:34-47`) rather than retaining a
fully identified contract. The provider tests pin this display format, not
broker security identity.

### Required design

- Resolve exact security ID and expiry from the dated broker instrument master.
- Store the option contract's underlying root and expiry relation.
- Assert that the futures contract used for AMT is the intended basis.
- Refuse to trade when the broker master cannot resolve the exact contract.
- Never synthesize a live tradable symbol as a silent fallback.

---

## P1-11. Active option scanner ignores important liquidity/Greek gates

**Evidence:** `quant/amt/session/scanner.py:137-216`,
`quant/multi_engine.py:1144-1165`, `quant/amt/session/selector.py:191-225`.

The active scanner:

- rejects OI below a threshold;
- rejects spreads above 4% when bid/ask exist;
- scores delta proximity;
- applies premium limits.

But it does not enforce `OptionSelectorConfig.min_volume`, does not require
bid/ask to be present, and its hard 4% spread threshold disagrees with
`OptionSelectorConfig.max_spread_pct=0.02`. `validate_option()` and
`check_theta()` exist but are not in the coordinator's active scan-to-engine
selection path.

A result can therefore enter the active contract set without a valid live
quote, without the configured volume minimum, and without a theta viability
check. The engine then defaults missing option delta to 0.50.

### Required design

Make one option-selection pipeline authoritative:

```text
chain snapshot → expiry → security ID → volume/OI → bid/ask → spread
→ Greek delta/IV/theta → premium → contract metadata → active engine
```

Persist the selection snapshot and reject stale or incomplete fields.

---

# 4. Quant and strategy correctness issues

## P1-12. Aggression score remains directionless

**Evidence:** `quant/amt/orderflow/aggression.py:51-144`.

The scorer accepts booleans but no trade direction. A bearish or bullish
setup can receive the same score from opposing order-flow evidence. Gate-level
checks partially protect entries, but the score remains misleading in DTOs,
journals, and any future consumer.

Add direction-aware evidence or make the scorer explicitly non-directional
and prohibit downstream code from interpreting it as directional conviction.

## P1-13. CVD confirmation remains directionally blind in IMBALANCED

**Evidence:** `quant/amt/orderflow/compute.py:84-93`.

Both positive and negative CVD slope set `cvd_confirmed=True` when market state
is IMBALANCED. The later gate partially masks this, but it still pollutes
aggression score and diagnostics.

Return a signed confirmation, such as `LONG`, `SHORT`, or `NONE`, and require
it to agree with the proposed setup direction.

## P1-14. Stop and target risk use a candle-scale heuristic for options

This is the combined consequence of P0-6 and the live engine design:
underlying structure is correctly used to decide direction, but option premium
risk is translated with the wrong delta field. Until real chain Greeks are
carried into the execution context, all option stop/target and lot-size
results are suspect even when the underlying signal is correct.

---

# 5. Risk, economics, and backtest governance

## P1-15. Trade costs are not authoritative in the QuantEngine execution path

`quant/execution/trade_costs.py` and `backend/app/infrastructure/adapters/paper_broker.py`
contain a cost model. The active `QuantCoordinator` injects `PaperOMS` into
`QuantEngine` (`quant/multi_engine.py:1337-1375`), while `PaperOMS` computes
raw price-difference P&L. The cost helper is therefore not the same source of
truth for the primary quant engine paper/replay path.

The separate model also uses fixed assumptions in
`quant/execution/trade_costs.py:32-58`: fixed brokerage, simplified GST,
STT side handling, exchange/SEBI percentages, no dated contract-master
schedule, and no exact partial-fill/order-count treatment.

### Required design

One fill ledger must drive:

- paper P&L;
- replay P&L;
- live realized P&L;
- risk halts;
- performance reports;
- broker reconciliation.

Costs must be product/segment/side/date aware and applied at actual fills,
not merely logged at entry.

## P1-16. Stop-gap and fill economics are optimistic in replay

The deterministic replay and golden tests are valuable for software
regression, but they are synthetic. They do not prove:

- queue position;
- bid/ask execution;
- latency;
- partial/rejected fills;
- real gaps;
- stale quotes;
- broker order state races;
- contract rolls;
- exchange charges and taxes.

A deterministic synthetic replay proves determinism, not trading validity.

### Required release-grade replay

Use captured, time-ordered data with:

- exchange timestamps and receive timestamps;
- bid/ask/depth snapshots;
- order and fill events;
- exact security IDs and contract metadata;
- fees, taxes, and slippage;
- reconnect gaps and duplicate packets;
- partial/rejected/unknown broker outcomes;
- point-in-time active contract universe.

Then independently recompute exposure, fills, costs, stop loss, daily loss,
and risk limits from the journal rather than trusting engine outputs.

## P1-17. No proven point-in-time contract universe

`quant/contracts/instrument_registry.py:73-117` contains hardcoded current
lot/tick/strike/freeze/min-OI values. These are useful defaults, but they are
not a dated exchange instrument-master history. Historical research must not
use today's lot sizes, symbols, expiries, or active universe for prior periods.

Add versioned dated contract-master snapshots and rollover tests. Unknown or
stale metadata must fail closed for live trading.

---

# 6. What remains correct

The second audit confirms these architectural choices are sound:

- AMT analysis and execution are separated.
- `MultiplexedMarketFeed` uses one producer and per-symbol queues.
- Exchange event timestamps are preferred over local arrival time
  (`quant/brokers/multiplexed_feed.py:453-471`).
- Cumulative volume is converted to per-tick deltas before aggregation.
- `TickFootprintAccumulator` is wired through `AMTEngine.on_tick()`.
- The option chart merge prevents futures-scale levels from being rendered on
  the option-premium chart (`quant/runtime.py:737-762`).
- The preferred futures resolver uses the broker instrument cache
  (`backend/app/infrastructure/adapters/dhan_adapter.py:404-433`).
- Dhan order POST retry safety avoids blindly retrying an ambiguous POST.
- Correlation IDs are sent in Dhan payloads
  (`brokers/broker/dhan/application/order_converter.py:159-165`).
- Startup live boot refuses a reconciliation exception at the application
  boundary (`backend/app/main.py:448-459`).
- EOD square-off is wall-clock driven and independent of bar flow
  (`quant/multi_engine.py:834-870`).
- Event sourcing, journal replay, deterministic tests, and periodic engine
  reconciliation are strong foundations.

These foundations should be protected while the release blockers are fixed.

---

# 7. Correct build sequence from here

## Phase 0 — Lock the live safety contract

Before adding signals:

1. Define `UNKNOWN`, `QUARANTINED`, `RECONCILE_REQUIRED`, and terminal order
   states.
2. Make risk and order persistence fail closed in live mode.
3. Set conservative aggregate risk defaults and require explicit live config.
4. Add broker-native protective stops or formally prohibit live mode.
5. Define exact position identity: exchange, security ID, symbol, side,
   product, signed quantity.

## Phase 1 — Correct the option execution basis

1. Carry chain Greek delta, IV, theta, expiry, security ID and quote age from
   scanner to engine.
2. Rename normalized candle delta to `orderflow_delta_ratio`.
3. Reject absent/stale Greeks and absent bid/ask.
4. Remove the 0.50 default for live option stop translation.
5. Make all entry and exit quantities lot-valid.

## Phase 2 — Make broker truth durable

1. Persist entry, close, partial, fallback, and stop orders uniformly.
2. Never map ambiguous exceptions to `REJECTED`.
3. Reconcile unknown orders on restart before engine startup.
4. Reconcile exact broker positions, not symbol presence.
5. Use actual filled quantity/price in all engine state transitions.
6. Clear duplicate guards only after terminal reconciliation.

## Phase 3 — Make the paper/replay loop economically representative

1. Route all PaperOMS fills through one cost-aware fill ledger.
2. Add fees/taxes/slippage by instrument and date.
3. Model gaps, quote spread, partial fills, latency and rejected orders.
4. Add captured-market replay with point-in-time contracts.
5. Add independent economic invariant checks.

## Phase 4 — Only then refine alpha

After the safety loop is closed:

- fix direction-aware aggression and CVD;
- align scanner and selector liquidity gates;
- decide whether range bars are a live feature or remove them;
- measure Triple-A setup performance by data-quality grade;
- run walk-forward and out-of-sample validation.

---

# 8. Release gates

Do not enable live order execution until all are true:

- [ ] Broker-native protective stop is confirmed after every live entry.
- [ ] Kill/restart test leaves no unprotected position.
- [ ] Unknown order outcome never becomes `REJECTED`.
- [ ] Unknown orders and close orders reconcile across restart.
- [ ] Exact broker position reconciliation checks side, signed quantity,
      exchange/security ID, product and pending orders.
- [ ] Risk load/write failure blocks live entries.
- [ ] Corrupt risk state quarantines and preserves evidence.
- [ ] Aggregate portfolio risk is conservative and explicitly configured.
- [ ] Option Greek delta is distinct from order-flow delta.
- [ ] Every live option quantity is a valid contract-lot multiple.
- [ ] Partial close uses actual fill quantity and actual fill price.
- [ ] Stop-gap behavior is tested and conservatively booked.
- [ ] Costs are applied to actual fills and feed risk/P&L.
- [ ] Contract metadata is dated, security-ID based and stale-checked.
- [ ] Captured-market replay passes independent exposure/economic invariants.
- [ ] Feed disconnect/reconnect and order-feed gap recovery are tested.
- [ ] Full quant, backend unit, and system execution suites pass after the
      fixes.

## Final conclusion

You are building the right **direction** of system: the domain separation,
AMT decomposition, Indian session model, broker port, event journal and
multi-symbol feed are solid. You are not yet building a sufficiently safe
**live execution system** because the broker, risk and contract truths are
not yet stronger than the strategy loop.

The next milestone should be called **Live Safety Certification**, not another
signal feature. Once the safety contract is enforced, the existing AMT
research can be evaluated honestly instead of being confounded by untracked
fills, wrong option delta, optimistic stops, missing costs, or stale contract
metadata.
