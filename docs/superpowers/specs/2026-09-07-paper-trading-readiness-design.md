# Paper Trading Readiness Design

## Status

Approved by the user on 2026-09-07 for planning. This document defines the
paper-trading target. It does not authorize live trading and does not change
production code.

## Goal

Make the existing Python/NSE/MCX futures-options platform trustworthy for
paper trading by making simulated fills, costs, positions, risk, journals and
restarts agree exactly.

Paper mode must answer:

> If this decision had been sent to a broker, what contract would have been
> traded, at what executable price, for what valid lot quantity, with what
> costs, and what would the resulting position and risk state be after a
> restart?

## Non-goals

- No live-order enablement.
- No broker credentials or broker calls.
- No new alpha model before the paper ledger is trustworthy.
- No exposure of Dhan security IDs to `quant.*` strategy/domain code.
- No replacement of the AMT architecture or event-sourced runtime.

## Explicit sizing policy

The user requested 95% position sizing for paper mode. The current setting
uses the name `risk_per_trade_pct`, but `SessionRisk` interprets that field as
stop-loss risk percentage. Setting it to `0.95` would mean risking 95% of
equity at the stop, not deploying 95% of capital.

The design therefore separates two meanings:

```yaml
paper:
  capital_deployment_pct: 0.95   # requested paper sizing policy
  risk_per_trade_pct: 0.005     # independent stop-loss risk budget
  max_daily_loss_pct: 0.02      # paper risk circuit breaker
```

`capital_deployment_pct=0.95` means the simulator may deploy up to 95% of
available paper capital/notional subject to contract lot, margin, liquidity,
portfolio and configured max-position limits. It does not override the
stop-loss risk budget.

A deliberately dangerous stress mode may set `risk_per_trade_pct=0.95`, but
that requires an explicit `allow_extreme_risk=true` paper-only flag and is
never accepted in live mode.

## Broker identity policy

Broker security IDs remain internal to each broker adapter.

### Engine-visible identity

The quant/domain layer may carry a broker-neutral `ContractRef` containing:

- display symbol;
- exchange/segment name;
- expiry;
- strike;
- option type;
- lot size;
- tick size;
- contract multiplier;
- product type.

It must never carry:

- Dhan `securityId`;
- broker instrument row IDs;
- broker-specific order payloads;
- broker authentication data.

### Adapter-private identity

The Dhan adapter resolves `ContractRef` to the broker instrument master and
keeps `securityId` private. The paper adapter uses a deterministic internal
paper instrument key and does not pretend to have a Dhan security ID.

The adapter may persist broker-specific identifiers in infrastructure-owned
order records for reconciliation, but those values never cross into strategy
context, AMT DTOs, signal objects, or shared domain contracts.

### Resolution rules

- A live Dhan order must resolve through the current broker instrument master.
- Unknown, stale, expired, exchange-mismatched or ambiguous contracts fail
  closed.
- The current calendar-month `ROOT MON FUT` fallback is not a valid live
  contract resolver. It may exist only as a paper/research display fallback.
- Reconciliation uses broker-neutral contract identity plus signed quantity;
  the Dhan adapter additionally validates its private security ID.

## Target execution flow

```text
Market data
  → canonical Tick
  → BarAggregator
  → AMTEngine
  → DecisionService / Fabio setup evidence
  → SessionRisk + PortfolioRiskAuthority
  → PaperOMS
  → PaperExecutionSimulator
  → FillLedger
  → Position projection
  → Risk/P&L/cost projection
  → Journal and restart snapshot
```

There is one paper fill authority. `PaperOMS`, `PaperBrokerAdapter`, and
`Portfolio` must not independently invent fill, cost or position semantics.

## Paper fill contract

Every paper order has a durable logical ID and a lifecycle:

```text
INTENT
  → SUBMITTED
  → ACCEPTED
  → PARTIAL
  → FILLED

Failure branches:
  SUBMITTED → REJECTED
  SUBMITTED → UNKNOWN → RECONCILE_REQUIRED
  ACCEPTED  → CANCELLED
```

Each fill records:

- logical order ID;
- contract reference;
- side;
- requested and filled quantity;
- average fill price;
- bid/ask snapshot or configured fill model;
- slippage;
- costs;
- event timestamp and receive timestamp;
- reason/setup/model label.

## Fill modes

Paper mode must select an explicit fill model:

- `instant_mid` for basic unit tests only;
- `bid_ask` for normal paper trading;
- `slippage_model` for stress tests;
- `captured_replay` for historical validation.

The normal paper environment uses `bid_ask` plus the configured cost model.
No fill silently uses the decision price unless the selected mode explicitly
says so.

## Lot and partial-exit policy

Derivative quantities are integer lot multiples at every boundary.

- A one-lot position closes fully. It cannot be split into half a lot.
- Partial exits are allowed only when the requested and actual filled
  quantities are valid lot multiples.
- Actual broker/simulator filled quantity, not requested quantity, determines
  P&L and remaining position.
- A partial-fill residual remains open and must be reconciled.

## Cost and P&L policy

One fill ledger is authoritative for:

- gross P&L;
- entry and exit slippage;
- brokerage;
- STT;
- exchange transaction charges;
- GST;
- SEBI charges;
- stamp duty where configured;
- net P&L.

The same net P&L feeds `SessionRisk`, `PortfolioRiskAuthority`, the journal,
performance reports and restart recovery.

## Fabio AMT acceptance boundary

The current implementation contains the main Fabio playbook structure:

- absorption with displacement;
- Triple-A state machine;
- value area and VWAP;
- initial balance;
- acceptance/rejection;
- profile shape and LVN/HVN;
- second-drive and squeeze evidence;
- contested footprint zones;
- deterministic rule-based exits.

It is not yet fully correct for paper evaluation because:

1. aggression score is directionless;
2. CVD confirmation is directionally blind in IMBALANCED state;
3. `deltaNormalizedOption` is candle order-flow delta, not option Greek delta;
4. active option scanning does not consistently enforce volume, spread,
   theta and Greek freshness;
5. candle-distributed/Gaussian footprints are approximations, not tick-exact
   order flow.

Paper reports must expose data quality and must not call synthetic footprint
signals tick-exact.

## Restart contract

On restart, paper mode must:

1. load the fill ledger;
2. rebuild open positions;
3. rebuild reserved risk and realized P&L;
4. reconcile in-flight orders;
5. quarantine unresolved states;
6. refuse new entries until reconciliation succeeds.

A restart may not reset daily loss, trade count or open exposure merely because
a local cache is unavailable.

## Paper readiness definition

Paper mode is ready only when all of the following hold:

- 95% capital deployment policy is explicit and separate from stop risk;
- contract identity is broker-neutral in the engine;
- security IDs remain adapter-private;
- paper fills use one authoritative simulator and ledger;
- costs are included in net P&L;
- partial fills and lot multiples are correct;
- restart reconstruction is exact;
- unknown order states are quarantined;
- option Greek delta is separate from order-flow delta;
- Fabio setup evidence is deterministic and data-quality labelled;
- full paper acceptance scenarios pass.
