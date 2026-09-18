# AMT Live Safety Remediation Design

**Date:** 2026-09-18
**Status:** Approved design
**Scope:** AMT signal integrity, live exposure reconciliation, durable lifecycle state, and architecture documentation

## Goal

Prevent unverified AMT flow from creating live orders, preserve directional signal correctness, and ensure broker exposure cannot become locally invisible through partial fills, timeouts, restart, or event persistence failure.

## Decisions

- Proxy AMT evidence may be displayed and used in paper/replay analysis.
- Live entries requiring AMT flow evidence are blocked unless the required evidence is `TICK_EXACT`.
- Numerical AMT parity is a separate follow-up project with frozen source vectors.
- The deterministic strategy and gate pipeline remain the sole entry authority.
- Narrative/advisor output remains advisory-only and cannot approve or reject an entry.
- The durable lifecycle/event projection is the authority for displayed position state.
- Existing unrelated worktree changes must not be reverted or folded into this work.

## Current Problem

The current system has a coherent AMT-to-decision spine, but several boundaries are unsafe or semantically inconsistent:

```text
Market data -> AMTAnalyzer -> AMT DTO -> DecisionContext -> GatePipeline -> SignalBuilder -> OMS
```

The AMT path can use inferred candle-based footprint, CVD, OFI, and absorption values as decision inputs. CVD confirmation is direction-blind in `IMBALANCED` state, and the active analyzer path does not pass direction and signed flow values into the direction-aware aggression scorer. The UI can therefore show `IMBALANCED` or strong aggression while the deterministic gate later rejects the setup, or while a proxy-based setup reaches the live decision seam.

The broker path can also observe a partial or unknown fill while local state is treated as flat. Event side effects may occur before durable event append, and snapshot fallback can hide an event-fold failure.

The implementation is Fabio-inspired rather than numerically source-equivalent. Value area, LVN, absorption, range-bar, and exact-flow differences are intentionally not changed in this remediation.

## Target Architecture

```text
Market feed
  -> timestamped observation/provenance normalization
  -> AMT analyzer
  -> provenance-aware AMT DTO
  -> immutable DecisionContext
  -> deterministic GatePipeline
  -> SignalBuilder
  -> risk authority
  -> durable order intent
  -> PaperOMS / LiveOMS
  -> normalized fill or reconciliation obligation
  -> PositionManager / ExitEngine
  -> ordered durable event log
  -> canonical state projection
  -> WebSocket/API/UI
```

The narrative branch is explicitly non-authoritative:

```text
DecisionContext -.-> RULE_TABLE / advisor -> narrative UI and journal
```

## Component Design

### Provenance-Aware AMT Evidence

The AMT DTO carries provenance for decision-critical evidence. Each relevant evidence family must identify whether it is `TICK_EXACT`, `CANDLE_DISTRIBUTED`, or `UNKNOWN`/degraded. The implementation should preserve existing DTO compatibility while adding a single normalized quality decision for entry gating.

Required evidence families:

- footprint imbalance
- CVD/delta
- OFI/depth
- absorption
- stacked imbalance

Paper/replay may emit decisions with `PROXY_MODE` metadata. Live entry submission must reject a decision when a required evidence family is not exact. The rejection must be observable through the existing decision/event telemetry and must not be confused with a generic `NO_EDGE`.

### Directional Flow

The active analyzer path must preserve the candidate trade direction through order-flow computation. Direction-aware scoring receives:

- candidate direction
- CVD slope
- normalized delta
- OFI value
- absorption side

CVD confirmation must only confirm flow aligned with the candidate direction. An opposing slope must not confirm a setup and must not contribute to the directional aggression score.

### Live Exposure Lifecycle

Broker outcomes are normalized into explicit states:

```text
FLAT
  -> ENTRY_INTENT
  -> SUBMITTED
  -> OPEN
  -> PARTIAL_OR_UNKNOWN
  -> RECONCILIATION_REQUIRED
  -> RECONCILED_OPEN | RECONCILED_FLAT
```

While `RECONCILIATION_REQUIRED` exists:

- new entries are blocked;
- the risk reservation is retained;
- the local system cannot report a clean flat state;
- restart restores the obligation;
- broker reconciliation must resolve exposure before normal trading resumes.

Close retries and market fallbacks use one durable economic close identity so a late fill from the original order cannot be counted as a second close.

### Durable Event Projection

The lifecycle event append and state projection must define failure behavior. A lifecycle transition that cannot be durably appended cannot be reported as canonical success. Projection and WebSocket consumers must identify degraded/unreconciled state instead of silently substituting mutable operational state.

Unmatched partial/reduction events must produce diagnostics sufficient to identify symbol, position/order identity, event type, and sequence.

### Architecture Documentation

After implementation and tests, update `quant/decision/gap_architecture.workflow.html` to include OMS, broker, fill normalization, reconciliation, EventStore, canonical projection, and WebSocket/UI boundaries. The narrative edge must be dashed and labeled advisory-only. The diagram must not claim numerical AMT parity that the runtime does not implement.

## Testing Contract

Each behavior change starts with a failing test and follows red-green-refactor. Required tests include:

### AMT

- opposing CVD cannot confirm a LONG or SHORT setup;
- opposing delta, OFI, or absorption cannot earn directional aggression credit;
- analyzer passes directional evidence into the active scorer;
- proxy evidence is visible in paper/replay;
- proxy evidence blocks live entry submission;
- the block is observable and has a distinct reason.

### Broker and Reconciliation

- partial entry retains risk and creates a reconciliation obligation;
- unknown broker response is not a clean rejection;
- restart restores unresolved exposure;
- reconciliation resolves to either broker-open/local-open or broker-flat/local-flat;
- new entries remain blocked until resolution;
- close fallback and late original fill share one economic close identity.

### Events and Projection

- EventStore append failure cannot silently advance canonical lifecycle state;
- projection indicates degraded state when canonical fold is unavailable;
- unmatched partial/reduction events emit diagnostics;
- position, risk, broker exposure, and UI state retain a common lifecycle identity.

### Architecture and Regression

- narrative output cannot approve or reject an entry;
- the documented workflow edges map to tested runtime boundaries;
- existing AMT, gate, OMS, exit, recovery, and certification suites remain green except for explicitly documented pre-existing skips.

## Rollout and Safety Gates

1. Paper/replay remains available with explicit `PROXY_MODE` decisions.
2. Live entry remains blocked for non-exact required evidence.
3. Live trading remains unavailable until partial/unknown exposure tests pass across restart and reconciliation.
4. Numerical AMT parity is not claimed until a separate vector-validation project passes.
5. The final verification report must separate test-passing internal behavior from live-readiness evidence.

## Out of Scope

- replacing all inferred flow with exchange-native tick/L2 data;
- changing value-area, LVN, absorption, or range-bar thresholds;
- broad architectural rewrites unrelated to the four safety boundaries;
- frontend redesign;
- reverting unrelated worktree changes.
