# Independent NSE/MCX Futures and Options Refactoring Plan

**Date:** 2026-09-07  
**Status:** Design proposal — Phase 1 adoption started; explicit topology and same-contract execution guard are implemented  
**Objective:** Make every traded futures or options contract an independent ultra-fast scalping unit while preserving exchange-correct NSE/MCX rules and allowing cross-instrument analytics only as explicit, non-execution coupling.

## 1. Executive decision

The target is **independent execution by contract**, not “futures signal translated into options.” Each active symbol owns its own:

```text
ContractRef
→ feed subscription
→ tick/bar aggregation
→ AMT state and evidence
→ signal and gates
→ position/risk state
→ OMS/order lifecycle
→ fills/P&L
→ persistence/restart state
```

A futures or spot feed may be used as optional market context, but it must never silently create, alter, approve, size, price, stop, or close an option order. Cross-instrument confirmation should be a separately named strategy mode and disabled by default.

This architecture improves correctness and testability; it cannot guarantee large daily returns. Profitability must be established by out-of-sample replay, realistic costs, paper acceptance, and controlled risk limits.

## 2. Current implementation findings

### Already aligned

- `QuantCoordinator` normally creates one `QuantEngine` per scanned symbol.
- `_spawn_engine()` currently sets `underlying_gateway = None` and `execution_enabled = True`, so the normal coordinator path is already independent in practice.
- `PortfolioRiskAuthority` is configured with `separate_by="symbol"` in the current coordinator, allowing same-root futures and options to hold separate execution locks.
- `InstrumentRegistry` is the strongest existing metadata authority for root, exchange, Dhan segment, tick, lot, strike interval, freeze limit, and session profile.
- `ExchangeConfig` and session context distinguish NSE and MCX session behavior.
- Cost-aware paper OMS composition and event/fill persistence have been introduced at the coordinator boundary.

### Remaining coupling and ambiguity

1. **Legacy dual-feed mode remains callable.** `QuantEngine` accepts `underlying_gateway`, creates both underlying and option AMT engines, merges DTOs, and calls `translate_underlying_signal_to_option()`. A manually constructed engine can therefore still mix price scales and decision ownership.
2. **The option selector still exposes translation as a first-class API.** Its domain documentation describes futures/index-to-option translation, and the runtime contains a translation branch guarded only by the presence of `underlying_gateway`.
3. **Configuration does not express execution topology explicitly.** `include_futures`, strategy names such as `nse_options`, and scanner behavior jointly determine topology. The system needs an explicit `execution_model`, not inference from strategy/exchange/contract names.
4. **Scanner topology may intentionally mix futures and options in one universe, but the contract is undocumented.** `_scan()` resolves futures first and allocates remaining slots to options. This is valid only if slot budgets, independent engines, and per-contract metadata are explicit.
5. **Market context and execution identity are not yet separate types.** `_underlying()` and root extraction are useful analytics helpers, but root identity must not become a shared position key or order target.
6. **Risk semantics need two explicit layers.** Symbol-level execution isolation is required, but same-root futures/options remain economically correlated. A symbol lock should not be replaced by a root execution lock; correlation must be a separate aggregate-risk budget.
7. **Some internal state and test fixtures still encode observer-engine assumptions.** `_underlying_gateways`, `_underlying_amt_dto`, `_option_amt_dto`, merged AMT payloads, and observer-specific tests need migration or explicit compatibility quarantine.
8. **Exchange metadata is mostly centralized but not fully contract-native.** Options are resolved from human-readable symbols; live execution must use a validated `ContractRef` from broker instrument metadata, including exact segment, security ID, expiry, strike, option type, lot, tick, and tradability.
9. **Persistence/reconciliation must be contract-keyed.** Fill IDs, positions, order state, and restart reconstruction must use canonical contract identity, not only root or display symbol.
10. **Current risk defaults require continued hardening.** The previous audit identified overly permissive defaults and incomplete portfolio caps. Independent engines must not multiply risk simply because they execute concurrently.

## 3. Target domain model

### 3.1 Canonical contract identity

Create/standardize an immutable `ContractRef` as the only execution identity:

```text
contract_id         stable broker-neutral ID
symbol              display symbol
exchange            NSE | MCX (and future supported exchanges)
segment             NSE_FNO | MCX_COMM | ...
root                canonical underlying root
instrument_type     FUTURE | OPTION
expiry              optional date
strike              optional decimal
option_type         CE | PE | empty for futures
lot_size            exchange/broker authoritative
price_tick          exchange/broker authoritative
quantity_step       lot or contract quantity rule
freeze_limit        exchange order-slice limit
broker_identity     adapter-private, never exposed to decision logic
```

Reject unknown, ambiguous, stale, expired, or internally inconsistent contracts before engine creation. Display-symbol parsing may select a candidate but broker instrument metadata must validate it.

### 3.2 Independent engine context

Each engine receives an immutable `ExecutionContext` containing:

- `ContractRef`;
- exchange session/calendar profile;
- its own gateway/feed subscription;
- its own AMT analyzer and bar aggregators;
- its own strategy instance or an immutable strategy configuration;
- symbol-local session risk and position manager;
- shared portfolio risk authority for aggregate limits only;
- its own OMS binding and persistence aggregate ID.

No `underlying_gateway` is present in the independent context.

### 3.3 Explicit topology

Use an explicit enum/configuration:

```yaml
execution_model: independent
```

Supported values:

- `independent` — default; local evidence generates orders for the same contract only.
- `cross_confirmed` — future opt-in; a separate confirmation service may veto/confirm but never substitutes the execution contract or price scale.
- `legacy_translated` — temporary compatibility only; disabled in production, warning at construction, removal deadline recorded.

Do not infer topology from `mcx_options`, `nse_options`, symbol suffixes, or `underlying_gateway is not None`.

## 4. Required invariants

### Independence

- A futures signal can produce only a futures `TradeIntent`.
- An option signal can produce only an option `TradeIntent`.
- `TradeIntent.contract_id`, signal symbol, OMS contract, fill contract, position contract, and persistence aggregate must agree exactly.
- An engine never reads another engine’s bars, AMT DTO, signal, stop, target, quantity, or position.
- No DTO merge may overwrite execution-scale fields from another contract.
- Removing the futures feed must not change an option engine’s local decision trace in independent mode.

### Exchange correctness

- NSE/NFO and MCX use their own session open/close, holidays, expiry cutoffs, tick, lot, freeze, fees, and option-chain rules.
- Contract identity determines exchange/session; coordinator mode is never the authority.
- An NSE configuration cannot spawn an MCX contract and vice versa without explicit mixed-exchange support.
- Mixed NSE + MCX trading shares only deliberately global controls: account equity, global loss halt, persistence, and observability.

### Risk correctness

- Symbol-level duplicate protection allows independent futures and options.
- Root-level correlation exposure is measured separately and does not serialize execution.
- Exchange-level and global limits remain enforced.
- Portfolio limits are explicit, validated, and bounded; no permissive 95%-style production defaults.
- A failed or unknown order outcome halts new entries for the affected contract/portfolio according to policy while exits remain available.

### State correctness

- Partial fills, retries, duplicate broker events, restart, and reconciliation preserve the exact contract identity.
- Position quantity derives only from actual fills.
- Costs are calculated once per fill and are exchange/instrument-aware.
- Closed positions and stale contracts cannot be silently reassigned to a newly selected strike or expiry.

## Latest adoption status — release-gate slice

Implemented in the shared checkout:

- `ContractRef` now exposes canonical `contract_id`, root, instrument type, and serializable identity metadata.
- The broker port and Dhan/paper adapters accept optional `contract_ref`; `LiveOMS` forwards it and retains compatibility with older test doubles.
- Portfolio risk now supports separate root and exchange risk budgets while retaining symbol-level execution locks.
- Option admission now rejects invalid quotes, configurable low volume, stale quotes (>5s), and stale chains (>30s), in addition to spread/OI/DTE checks. Legacy fixtures with omitted volume remain compatible; production scanner configuration should provide it.
- Mixed NSE/MCX and correlation-budget certification tests were added.

Validation evidence for this slice:

```text
91 focused tests passed
Python compilation passed for changed broker/runtime/risk/contract modules
git diff --check passed
```

Still not honestly claimable as complete without environment-specific evidence:

- Broker security ID/segment validation from live instrument master (requires current broker metadata/API).
- Live restart reconciliation against real broker positions and unknown-order outcomes.
- Full-session NSE/MCX paper acceptance, latency/soak/chaos evidence, and operator GO review.
- Full repository suite from a clean checkout; the working tree contains pre-existing unrelated edits and remains intentionally uncommitted.


### Gate G2 — coordinator contract identity propagation

Implemented in the primary worktree:

- Coordinator resolves one validated `ContractRef` before constructing each production engine.
- The same identity is passed to `QuantEngine` and the cost-aware paper OMS.
- The engine validates that `ContractRef.symbol` exactly matches its engine symbol.
- NSE and MCX future/option representative contracts are covered by boundary tests.
- Direct synthetic/replay construction remains optional-contract compatibility while callers migrate.

Evidence:

```text
Engine identity/topology tests: 20 passed
Coordinator/instrument/isolation tests: 29 passed
Backend topology/DI tests: 9 passed
```

Remaining for the full G2/G3 release gate: restart reconciliation and mixed-exchange coordinator certification. Live OMS identity propagation and durable position/fill identity are now implemented with backward-compatible optional metadata.

### Gate G3 — live and durable contract identity

Implemented in the primary worktree:

- `LiveOMS` accepts the validated `ContractRef` and rejects mismatched entry signals and exit positions before broker submission.
- Coordinator passes the same contract object into live OMS construction.
- Position persistence records exchange, expiry, lot/tick, strike, option type, and multiplier in the existing extensible `extra` payload, preserving old SQLite schemas.
- Fill-ledger persistence carries the same identity metadata through the storage bridge.
- Mixed NSE/NFO and MCX futures/options identity certification covers independent topology and exchange assignment.

Evidence:

```text
Live OMS, persistence, mixed-exchange, and coordinator tests: 33 passed
```

The live broker method signatures remain backward-compatible (`symbol` is still the adapter argument); the OMS contract guard is the authoritative pre-submit boundary. A future broker-port migration may promote `ContractRef` to a required adapter argument after all adapters are migrated.

Parallel work is allowed only on disjoint ownership surfaces. A lead integrator owns shared contracts, branch integration, and final certification.

### Phase 0 — Baseline and contract freeze

**Lead:** architecture/integration agent  
**Parallel agents:** exchange metadata audit; runtime topology audit; risk/persistence audit.

Deliverables:

- ownership matrix mapping canonical owner, port, adapter, persistence key, and deletion target;
- deterministic baseline traces for one NSE future, NSE option, MCX future, and MCX option;
- topology decision recorded as `independent` default;
- no production code changes until traces and affected callers are catalogued.

Gate: clean baseline, all alternate construction paths listed, no hidden production dependency on translation.

### Phase 1 — Contract identity and exchange authority

**Owner:** instrument/contract agent.

Changes:

- make `ContractRef` the required engine/OMS identity;
- validate exact registry/broker metadata for NSE/NFO and MCX contracts;
- consolidate parsing through `InstrumentRegistry` and remove fallback exchange guesses;
- add `ExecutionContext` and typed exchange/session profile;
- add contract validation for expiry, strike, option type, tick, lot, segment, and tradability.

Tests:

- all registered NSE and MCX futures/options formats;
- CRUDEOIL vs CRUDEOILM and GOLD vs GOLDM disambiguation;
- NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY contract identity;
- wrong exchange, expired, unknown root, wrong lot/tick, malformed option;
- exact `ContractRef` equality through order/fill/persistence.

Gate: no execution path can trade without validated contract identity.

### Phase 2 — Independent engine boundary

**Owner:** runtime agent.

Changes:

- introduce an independent engine constructor/factory that has no `underlying_gateway` parameter;
- move legacy dual-feed behavior behind an explicitly named compatibility adapter;
- remove the runtime translation branch from independent mode;
- make the engine’s local AMT DTO the sole decision evidence in independent mode;
- ensure options use option-premium bars for signal, stop, target, quantity, and P&L;
- ensure futures use futures bars and futures economics;
- make strategy output a same-contract `TradeIntent`.

Compatibility policy:

- retain legacy translation only for old unit tests during migration;
- production composition must reject `legacy_translated` unless an explicit non-production flag is set;
- delete the adapter after migration tests are ported.

Tests:

- futures-only engine with no option state;
- option-only engine with no futures state;
- same option trace with/without unrelated futures feed is identical;
- no cross-scale stops/targets/P&L;
- approved futures signal cannot submit an option order;
- approved option signal cannot mutate futures state;
- independent engines run concurrently without event or state contamination.

Gate: independent mode has no runtime call path to `translate_underlying_signal_to_option()`.

### Phase 3 — Coordinator, scanner, and mixed NSE/MCX topology

**Owner:** coordinator/scanner agent.

Changes:

- replace implicit scanner behavior with an explicit `UniverseConfig` containing exchange, roots, instrument types, slot budgets, and per-family caps;
- allow mixed NSE and MCX universes only when configured explicitly;
- allocate separate capacity for futures and options rather than silently consuming option slots with mandatory futures;
- construct one engine per validated contract;
- make lifecycle, rotation, and EOD policies contract-aware;
- never rotate a live position into a new strike/expiry; close/reconcile first;
- use contract ID, not root, for gateway maps and engine maps.

Tests:

- NSE futures + NSE options;
- MCX futures + MCX options;
- simultaneous NSE and MCX;
- futures-only, options-only, and mixed universes;
- scanner returns no invalid or duplicate contracts;
- rescan/rotation cannot orphan open positions;
- exchange-specific session/EOD behavior in one coordinator.

Gate: topology is visible in configuration and startup telemetry, with exact active contract list.

### Phase 4 — Risk and portfolio separation

**Owner:** risk agent.

Changes:

- preserve symbol-level execution locks;
- add explicit aggregate dimensions: symbol, root, exchange, instrument type, global;
- separate correlation budget from execution serialization;
- require validated portfolio limits at composition root;
- enforce max concurrent positions, max open risk, daily loss, drawdown, and per-exchange budgets;
- pass marked-to-market option and futures exposure using instrument-specific economics;
- add failure breakers for repeated unknown/rejected submissions and persistence/reconciliation failure.

Tests:

- same-root future and option may enter independently;
- root correlation budget can reject a new entry without blocking an existing exit;
- NSE and MCX limits are independently enforced;
- option premium risk is not calculated using futures point value;
- concurrent entries cannot exceed global limits;
- reservation release after submit failure;
- restart restores risk reservations or blocks entries until reconciled.

Gate: concurrency cannot multiply configured risk, and every rejection has a stable reason.

### Phase 5 — Order, fill, persistence, and reconciliation certification

**Owner:** money-path agent.

Changes:

- unify `TradeIntent → OrderLifecycle → FillLedger → PositionProjection`;
- carry `contract_id`, exchange, segment, logical order ID, fill ID, sequence, event/receive timestamps, and causation/correlation IDs;
- make duplicate identical events idempotent and conflicting events quarantine;
- persist every actual fill and calculate costs once;
- reconcile by exact contract identity and signed quantity;
- restore each futures/options engine independently after restart.

Tests:

- partial option fill followed by final fill;
- futures and option fills interleaved;
- duplicate and conflicting fill IDs;
- crash before submit acknowledgement, after acknowledgement, and after fill;
- restart with open futures and option positions;
- stale strike/expiry quarantine;
- broker/manual position mismatch;
- paper/live adapter conformance.

Gate: replay and restart produce byte-equivalent position, P&L, risk, and event state or enter explicit `RECONCILE_REQUIRED`.

### Phase 6 — AMT evidence and scalping quality

**Owner:** AMT/decision agent.

Changes:

- make AMT analyzer a facade over profile, VWAP, CVD, absorption, aggression, session, and break components;
- define `DataQuality` for tick-exact, candle-distributed, proxy, and unknown evidence;
- make setup requirements exchange/instrument-specific but contract-local;
- separate signal latency from analysis timeframe: micro trigger plus macro context must be explicit and local to the same contract;
- enforce option liquidity gates using fresh bid/ask, spread, OI, volume, chain timestamp, delta/gamma/theta where required;
- do not manufacture a default Greek for independent option decisions; use option-local evidence or fail closed.

Tests:

- option signal uses option-local profile and quote;
- futures signal uses futures-local profile;
- stale/missing option chain blocks only that option entry;
- MCX and NSE thresholds/session windows differ correctly;
- data-quality restrictions prevent unsupported high-conviction approvals;
- latency and stale quote gates are observable.

Gate: every approved setup contains explainable, same-contract evidence with freshness and quality.

### Phase 7 — Observability, rollout, and certification

**Owner:** operations/certification agent.

Changes:

- expose active contract identity, exchange, instrument type, execution model, data age, seed state, risk state, readiness, and last order/fill per engine;
- add correlation IDs across decision/order/fill/reconciliation;
- add dashboards/alerts for stale feed, wrong exchange, cross-contract contamination, unknown order, risk halt, and persistence failure;
- run shadow and paper modes before any live canary;
- keep live execution disabled by default and require explicit human GO.

Gate: full certification matrix green and operator can explain every blocked or submitted order.

## 6. Suggested agent matrix

| Agent | Owns | Must not edit concurrently |
|---|---|---|
| Contract/Exchange | `ContractRef`, registry, NSE/MCX metadata, contract validation | runtime constructor, persistence schema |
| Runtime Isolation | engine context, removal of implicit translation, local AMT ownership | shared event schema without integrator |
| Coordinator/Universe | scanner topology, engine factory, lifecycle/rotation | risk authority internals |
| Risk | portfolio dimensions, limits, breakers, reservations | engine decision flow except through port |
| Money Path | intents, order/fill lifecycle, persistence, reconciliation | scanner/config topology |
| AMT Quality | local evidence, freshness, option gates, data quality | OMS and persistence |
| Operations | readiness, metrics, alerts, runbooks, rollout | domain semantics |
| Integration Lead | branch merges, golden traces, contract compatibility, final gates | no speculative parallel edits to owned files |

## 7. Validation matrix

### Unit and contract

- registry and symbol parser matrix for NSE, NFO, MCX;
- contract metadata and exchange/session matrix;
- independent engine isolation properties;
- risk dimension and limit truth tables;
- order/fill state-machine transitions;
- duplicate/conflict/idempotency tests.

### Integration

- one engine per NSE future, NSE option, MCX future, MCX option;
- mixed exchange coordinator startup;
- independent concurrent tick streams;
- option and future orders interleaved;
- partial fills and restart reconstruction;
- scanner rotation with open/flat positions;
- broker reconciliation and unknown order outcomes.

### Replay and performance

- deterministic golden replay per instrument family and exchange;
- differential trace: old independent path vs refactored path;
- realistic spread, slippage, brokerage, STT/exchange charges, and latency;
- full NSE session soak;
- full MCX day/evening session soak;
- maximum configured contracts plus 2× headroom;
- p50/p95/p99 tick-to-decision and decision-to-submit latency;
- queue depth, memory, lock wait, journal lag, and dropped-event monitoring.

### Release gates

```text
G0 baseline and ownership artifact
G1 contract identity and exchange authority
G2 no implicit cross-instrument execution
G3 independent mixed-exchange coordinator
G4 risk and money-path invariants
G5 restart/reconciliation certification
G6 paper acceptance with costs and latency
G7 operator/chaos/rollback drill
G8 explicit human GO for restricted canary
```

## 8. Files likely affected

### Primary production surfaces

- `quant/runtime.py`
- `quant/multi_engine.py`
- `quant/amt/session/selector.py`
- `quant/contracts/instrument_registry.py`
- `quant/contracts/exchange_config.py`
- `quant/execution/portfolio_risk.py`
- `quant/execution/risk.py`
- `quant/position_manager.py`
- `quant/execution/oms_factory.py`
- `quant/execution/oms.py`
- `quant/execution/live_oms.py`
- `quant/event_store.py`
- `quant/events.py`
- `quant/reconciliation_service.py`
- backend composition/config loader and exchange-specific strategy YAML files
- frontend runtime/readiness/contract display surfaces

### Tests/artifacts

- `tests/quant/runtime/`
- `tests/quant/coordinator/`
- `tests/quant/decision/`
- `tests/quant/execution/`
- `tests/quant/replay/`
- `backend/tests/unit/domain/`
- `backend/tests/integration/`
- `docs/architecture/ownership-map.md`
- `docs/architecture/runtime-state-machine.md`
- `docs/operations/release-ledger.md`

## 9. Explicit non-goals

- No default `delta=0.50` repair for the legacy futures-to-option handoff.
- No automatic enabling of live futures or options.
- No promise of “huge daily returns.”
- No shared root lock that serializes otherwise independent contracts.
- No removal of exchange-specific NSE/MCX rules in favor of global defaults.
- No broad rewrite before golden traces and failure-mode tests exist.

## 10. Definition of done

The refactor is complete only when:

1. Independent mode is explicit and the default.
2. Production construction cannot reach legacy signal translation.
3. Four representative engines—NSE future, NSE option, MCX future, MCX option—run independently.
4. Same-root futures and options can execute independently while correlation/global budgets remain enforced.
5. Contract identity is exact from scanner through OMS, fill ledger, restart, and UI.
6. No cross-scale price, stop, target, quantity, P&L, AMT, or event contamination is possible.
7. NSE/MCX session, holiday, expiry, lot, tick, fee, and freeze rules are tested separately.
8. Partial fills, duplicate/conflicting fills, restart, broker mismatch, and unknown order outcomes are safe and observable.
9. Paper fills use realistic costs and latency, and replay is deterministic.
10. Full quant/backend/broker/frontend/parity gates pass from a clean checkout.
11. Paper acceptance evidence exists for both NSE and MCX sessions.
12. Live remains off until a human owner signs the final GO decision.
