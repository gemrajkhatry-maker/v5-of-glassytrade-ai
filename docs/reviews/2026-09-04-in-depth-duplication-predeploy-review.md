# In-Depth Review — Consolidated Report

> **Date:** 2026-09-04 · **Branch:** `feat/fractal-half-trend-signals`
> **Pinned at:** `32e723af` (HEAD at write time) · **Tree:** clean
> **Consolidates:** pre-deployment system review (Release-Manager lens), the 6-step in-depth
> review, and the core-engine/backend duplication review, all conducted this week but previously
> delivered only in chat. Evidence was re-verified against the tree at write time (module reads,
> caller scans, `git merge-tree`, CI config, worktree inventory).

---

## 1. What was reviewed and where it was recorded

| Review | Lens | Recorded |
|---|---|---|
| Pre-Deployment System Review (`b1410214` state) | Release Manager — what breaks, what fails silently, timing assumptions, Day-1 alerts | Chat only → consolidated here (§3–§8) |
| 6-step in-depth review | Mandatory process: reconstruct → trace → shotgun → eliminate → boundaries → test readiness | Chat only → consolidated here |
| Core Engine + Backend Duplication Review | Principal Engineer — duplication, ownership, "how it must have been implemented" | Chat only → consolidated here |
| Common-interface (ports & adapters) deep-dive | How `IOMS`/`IBroker`/`IBrokerPort`/`IMarketData`/`IStorage` actually wire | Chat only → condensed to §4 |
| Earlier formal reviews | Prior sessions | On disk: `2026-08-24-principal-rearchitecture.md`, `2026-08-28-principal-architecture-review.md`, `reviews/fabio_amt_architecture_review.md` |

**Gap closed by this document:** the three most recent in-depth reviews had no file artifact.

## 2. System intent

Single-process Indian index-options trading system (NSE/MCX): broker WS ticks → per-underlying
5-min AMT bar fold → deterministic gate pipeline (Triple-A / LVN Sniper / VA Fade) → exactly one
pre-sized, lot-aligned order per approved signal → `LiveOMS` → `DhanBrokerAdapter` → Dhan, every
order-state transition durable in SQLite, exits computed by one `ExitEngine`, engine/state
event-sourced, frontend a read-only WS consumer that never computes a decision.

## 3. Verified-good architecture spine (do NOT refactor)

These were traced hop-by-hop in code this week and are genuinely consolidated:

- **Exit logic: one spine.** `runtime._manage_exit`/`_manage_tick_exit` (thin locks+guards) →
  `PositionManager.manage_exit` (`position_manager.py:119`) → single injected `ExitEngine`
  (`execution/exits.py`: `evaluate`/`stop_state`/`pop_trail`) → leaf helpers `exit_checks`
  (tp2 level) + `exit_rules` (session-time stop). One instance per engine, injected into both PM
  and strategy — no split-brain exit configuration.
- **Entry + thesis-flip share one decision seam.** `_decide()` and `_check_thesis_flip()` both
  route through `self._strategy.should_enter(ctx)` → `DecisionService.evaluate`. Flip uses an
  explicit `allow_positioned=True`; basis-parity rule documented in code. Recent polarity fix
  (`5ec7caca`, `f51ad811`) landed in this one seam, not a second implementation.
- **Live/paper OMS selection is loud and guarded.** `multi_engine.py:1356-1373`: live+broker →
  `LiveOMS` assigned post-construction with an explicit log line; refuse-to-start when
  `live_oms_enabled` without a broker. No silent paper fallback in live mode.
- **Risk config chain is single-authority** (after `6adf6b8f`): YAML → loader (fails live boot on
  missing keys) → validator (bounds) → composition root (raises on missing value; the
  `getattr(..., 0.005/0.02/3)` literal fallbacks are gone).
- **Position sizing fail-closed** (B1): adapter accepts only the risk-approved
  `metadata["order_quantity"]`, validates finite/positive/integer, refuses to call Dhan otherwise.
  Second broker-side sizing algorithm removed.
- **Ledger truthfulness at the timeout boundary** (B3, `b1410214`): cancel-fail → durable
  `UNKNOWN`; fill raced cancel → `FILLED` (position honored); partial frozen by cancel → `FILLED`
  fractional; clean cancel → `CANCELLED`. Duplicate WS fill updates converge idempotently
  (absolute values, no accumulation).
- **Restart-stable signal identity** (B2, `193bc147` + `5ec7caca`): `signal_id` = `uuid5` over
  canonical decision content (explicit ids still win), `compare=False` so replay-parity equality
  stays exact; broker `correlationId` dedup now survives process restart, mirroring the existing
  content-derived close ids.

## 4. Duplicate / divergent representations — inventory & owners

| Concept | Definitions | Verdict | Authority |
|---|---|---|---|
| `Position` | `execution/order.Position` (engine, float, frozen) · `contracts/entities.Position` (broker-boundary, Decimal) · `shared/entities/models.Position` (SDK) · `state_machine.PositionState` | Layered anti-corruption is intentional (converter hops exist per boundary: `fills.broker_position_to_fill`, `transitions`). KEEP layers; DELETE `PositionState` projections only when event-sourced merge makes StateProjector authoritative | One converter per boundary |
| `Signal` | `decision/signal_builder.Signal` (engine) · `contracts/entities.Signal` (broker) | Dual definitions justified by Decimal/float boundary; `to_broker_signal` preserves identity explicitly (`broker_mapper.py:40,54`) | Engine-side builder |
| Paper execution | `PaperOMS` (`quant/execution/oms.py`) vs `PaperBrokerAdapter` (`backend/.../paper_broker.py`) | **Real duplication.** Verified: paper mode injects `PaperOMS`; engine orders never route through `IBroker`/`PaperBrokerAdapter`. The adapter path is reached only by startup reconciliation/one-shot flows. Two simulators with different fill semantics = two answers to "what would paper have done" | **DECISION REQUIRED at G2** — route paper through `IBroker`, delete one simulator; or keep `PaperOMS` for replay/tests where no DI exists and delete the adapter |
| Journals | `Journal` (JSONL, replay) vs `TradeJournal` (read-only analytics aggregator over stored rows) | Distinct roles — writer vs derived reader. KEEP | — |
| Bar engines | one-minute bar engine + RL observation builder | Already deleted (`fc35eb56`) | — |
| OMS/IBroker idioms | ABC (`IBroker`, 3 methods) vs `@runtime_checkable` Protocol (`IOMS`) + conformance suite | Two idioms for one concept — mild style duplication, not logic. Documented dual-port decision (WS4) justifies `IBroker` vs `IBrokerPort` split | Keep; conformance suite is the behavioral contract |

## 5. Dead / legacy / unmerged code — DELETE list

| Item | Status | Action |
|---|---|---|
| `.worktrees/event-sourced` + `.worktrees/w5` (`fix/event-sourced-architecture`, `fix/w5-money-safety`) — transport-unknown handling, shared capital book, restart restore, tick-drop counters | **Unmerged; re-verified conflict-free today** (`git merge-tree`: 0 conflict markers) | **BLOCKER — merge w5 first, then event-sourced.** Every day unmerged, this branch re-implements their fixes blind |
| `load_inflight_orders()` restart-restore caller | Exists only in unmerged `w5` worktree — **no production caller on this branch** | Merge w5 (restore path), then it has an owner |
| `runtime_audit/` system-test tree | Not executed anywhere: absent from CI commands, hangs standalone (boots real app with lifecycle) | Either fix + add to CI, or state explicitly it is a manual suite. Currently a silent gap |
| `tests/e2e` | Excluded from CI (`--ignore=tests/e2e`) | Document as manual, or gate it |
| `/private/tmp/fb-baseline` worktree | Stale | Delete |
| `coordinator_view` / `ws_contract` legacy seams | Suspected unimported (caller scans pending) | Verify importers at G2 gate, then delete |
| Risk literal fallbacks in composition root | Already removed (`6adf6b8f`) | Done |
| One-minute bar / RL observation modules | Already deleted | Done |

## 6. Execution-flow validation (money path, as traced)

```
Dhan WS tick → gateway → BarAggregator → runtime._decide()
  Guard 0: SessionRisk.can_trade (halt/cooldown BEFORE context)
  → DecisionContextBuilder → strategy.should_enter → DecisionService.evaluate
  → Signal (uuid5 content id) → portfolio_risk.can_accept → register_open (reserve)
  → LiveOMS.submit → to_broker_signal (identity preserved)
  → DhanBrokerAdapter.execute_order → _pre_sized_quantity (fail-closed)
  → dedup guard (_executing_signal_ids + correlationId == signal_id)
  → _persist_order_submitted (SUBMITTED before place_order)
  → place_order → _poll_for_terminal_status (WS push + REST pull)
  → FILLED → Position honored; cancel-fail after timeout → UNKNOWN durable
  → PositionOpened → EventBus → journal + HotPathSubscriber (passive trace)
```
Reservation unwind verified: `LiveOMS.submit` raises on broker rejection → engine `except` path
releases the reservation. Partial fills release fractions. Engine never constructs its own OMS;
coordinator injects it.

## 7. Integration boundaries & silent-failure surface

State-transition honesty per hop was the week's theme and is now explicit at the broker
(submitted-before-send, UNKNOWN-after-ambiguous, fill-race honored) and engine (raises, never
silent `None`) boundaries.

**Remaining silent-failure risks (all merge-gated):**
1. WS tick drop with no counter/alert (w5 carries the counters) — a dropped feed with a healthy
   process = no entries, no alarms.
2. No system/transport-level test executed anywhere (`runtime_audit` not in CI).
3. `IMarketData` error semantics (raise vs `[]` vs `0.0`) live only in docstrings — not all
   conformance-tested.
4. Restart position restore absent until the event-sourced/w5 merge lands.

## 8. Required before deploy + Day-1 observability

**Merge order (sequential):** w5 → event-sourced → full regression (quant 1,742 + backend unit
697 + e2e). Then G1 gate: crash-window restart-restore test; single active position per
underlying root (new `32e723af` behavior) with multi-root regression.

**Tests that MUST pass before GO:** crash-window/restart restore parity; transport-UNKNOWN
round-trip; one paper answer (post-G2 consolidation); `runtime_audit` executed green.

**Day-1 alert set:** (1) any `UNKNOWN` durable row; (2) engine/broker/ledger position-set delta
≠ 0; (3) SessionRisk daily loss vs `absolute_ceiling_pct` approaching ceiling; (4) tick-drop /
stale-feed counter (w5); (5) WS disconnect/reconnect events.

## 9. Verdict

**NO-GO for real capital on this commit alone** — money-boundary defensible (B1/B2/B3/B7,
risk-chain, ledger truthfulness, identity all landed and regression-green) but deploying without
the w5 + event-sourced merges ships without transport-unknown safety, restart position restore,
shared capital authority, and any executed system-test suite. **Conditional GO** once both merges
land clean (verified conflict-free today), the five tests above pass, and a paper shadow day shows
trace parity.

---
*Uncommitted on HEAD: none (tree clean). Everything through `32e723af` is committed locally;
nothing pushed to origin.*
