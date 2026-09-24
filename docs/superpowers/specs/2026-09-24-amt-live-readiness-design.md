# AMT Live Readiness Design

**Date:** 2026-09-24
**Status:** Approved design
**Branch:** `feat/amt-live-readiness`
**Scope:** AMT strategy alignment, evidence provenance, live OMS safety, options/risk integration, deterministic verification, and documentation

## Goal

Make the AMT strategy end-to-end spec-aligned and verifiable for a future live rollout without changing the deterministic strategy architecture or claiming unsupported broker readiness.

The implementation must leave the system in one of two explicit states:

- **Eligible for live execution:** every required invariant is enforced and the deterministic release gates pass.
- **Safely blocked:** any missing evidence, broker capability, reconciliation state, or certification condition prevents live entry.

There is no silent fallback from a failed safety invariant to a proxy path.

## Decisions

- The canonical AMT behavior is the behavior in `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md` and the related decision-pipeline documents.
- Required evidence is fail-closed for live entries. Only explicitly documented, field-level proxy evidence may be used in paper/replay or display paths.
- Missing depth is not synthesized for strategy decisions.
- Triple-A Aggression requires the documented directional CVD condition and documented breakout conditions. LVN proximity is reserved for LVN-specific paths.
- The deterministic `AMTAnalyzer -> DecisionContext -> GatePipeline -> SignalBuilder -> OMS` path remains the only entry authority.
- Live execution requires real stop support, actual broker fills, durable close identity, and reconciliation obligations.
- Live pyramiding follows the documented 50%/25% sequence; a broker that cannot represent the required orders is blocked rather than silently degraded.
- Option AMT requires a valid underlying observation. Premium-only fallback is not an eligible AMT entry path.
- Risk configuration must have one effective authority. The effective HMP tier is observable at startup and tested against the shipped live configuration.
- Verification uses deterministic mocks, replay/golden tapes, and pure local tests. No broker credentials or live order are used.
- The work happens on `feat/amt-live-readiness` with staged commits. The branch is pushed only after the complete local release gate passes.

## Current Baseline

The review at commit `24f1bd78` found a coherent AMT analytical spine and substantial paper/replay coverage, but not a clean live-readiness release:

- `tests/quant/amt`: 635 passed, 3 failed, 2 skipped.
- AMT/decision/execution/runtime focused suite: 1,645 passed, 8 failed, 3 skipped.
- `make parity`: 20 passed, 6 failed.
- `make test-quant` completed its pytest phase with 2,818 passed, 33 failed, 11 skipped, then did not exit cleanly because feed threads continued retrying.
- `make lint` and the frontend test suite passed.

The graph map identifies `AMTAnalyzer`, `TripleAMachine`, `DecisionLoop`, `PositionManager`, `LiveOMS`, and `PortfolioRiskAuthority` as the main decision and safety boundaries. The graph is a navigation aid; every behavior below is verified against source and tests.

## Target Data Flow

```text
Market feed
  -> provenance-preserving observation
  -> AMT analyzer
  -> provenance-aware AMT DTO
  -> immutable DecisionContext
  -> deterministic GatePipeline
  -> SignalBuilder
  -> SessionRisk and PortfolioRiskAuthority
  -> durable order intent
  -> PaperOMS or LiveOMS
  -> actual fill / reconciliation obligation
  -> PositionManager and ExitEngine
  -> durable event log
  -> canonical state and UI projection
```

The advisory/narrative branch remains non-authoritative. It may explain a decision but cannot approve, reject, size, or exit a position.

## Component Design

### 1. Evidence and Data Quality

Add one normalized evidence-quality decision used by the live entry seam. Decision-critical families retain their provenance:

- footprint imbalance;
- CVD/delta;
- OFI/depth;
- absorption;
- stacked imbalance.

`TICK_EXACT` is required for every family used by a live AMT entry unless the AMT policy explicitly names a field-level proxy. A proxy must be identified in the DTO/context and surfaced in telemetry; it cannot be silently relabeled as exact.

The allowed proxy policy is limited to documented cases where the feed cannot provide a field. A missing order book, invalid depth, or absent underlying observation is a typed data-quality failure, not a synthetic-book or premium-only setup.

`DecisionLoop` must block the entry with a distinct, observable reason for:

- missing required evidence;
- invalid provenance;
- missing or invalid depth;
- missing option underlying data;
- unsupported or failed broker capability.

The same decisions remain available in paper/replay with explicit proxy metadata, so historical analysis remains possible without weakening the live gate.

### 2. Triple-A and Decision Gates

`TripleAMachine` becomes a literal implementation of the documented state conditions:

- LONG Aggression requires a close above the absorption cluster, price above VWAP, and expanding/positive CVD.
- SHORT Aggression requires a close below the absorption cluster, price below VWAP, and contracting/negative CVD.
- Absorption must be causally tied to the current setup; prior-session or stale drive state cannot satisfy a live trigger.
- Aggression does not require LVN proximity unless the setup is explicitly classified as an LVN/retest path.

Add boundary tests for zero, mildly adverse, and strongly adverse CVD. Add an organic path test where a valid Playbook A setup has no nearby LVN and must still be evaluated according to the documented rule.

### 3. Live OMS Safety

Live execution is refused unless the broker capability contract is explicit.

#### Stop lifecycle

- The broker must support a native protective stop or an explicitly supported OMS-managed stop implementation.
- A missing or `NotImplementedError` stop capability is a hard failure; it is never represented as a successful stop.
- The stop order ID and stop state are persisted with the position.
- Full close, partial close, emergency flatten, and restart reconciliation cancel or resolve the protective stop through a durable identity.
- A stop failure marks the position/exposure as unsafe and blocks further entries until resolved.

#### Fill and close identity

- OMS state uses broker-reported filled quantity, not requested quantity.
- P&L, fill size, remaining position, and partial-tier state derive from the actual fill.
- A close retry for the same economic intent is idempotent.
- A later TP stage or independent close has a distinct durable intent and fill identity.
- Unknown, partial, or contradictory broker outcomes retain risk and create a reconciliation obligation; they are not reported as clean flat.

#### Pyramiding

Live pyramiding uses the documented 50%/25% base-size sequence. Each add has a unique order identity and must pass the same risk, lot, stop, and reconciliation rules as the initial order. A broker or OMS that cannot represent the add sequence blocks the pyramid path explicitly.

### 4. Options and Risk

Option AMT is eligible only when the option has valid contract metadata, a valid underlying observation, and sufficient delta/spread data. The option path must not fall back to an independent premium tape.

The implementation aligns option and future policy to the AMT documentation, including spread limits, stop distance, and any expiry-specific adjustment. Any remaining proxy deviation is documented with its exact field, scope, and test.

Risk configuration has one effective authority. The startup log and runtime state report the effective HMP tier, per-trade risk, daily-loss limit, and consecutive-loss limit. Tests pin the shipped live configuration and prove the configured values are honored or explicitly transformed by a named policy.

The paper 50/25/25 TP ladder and 50%/25% pyramid ratios are tested by resulting position quantities, not only by checking a passed fraction argument. Lot-rounding policy is explicit and covered for both paper and live-equivalent sizing calculations.

## Phases and Commits

Each phase is independently reviewable and must leave its relevant tests runnable.

### Phase 0 — Baseline and contracts

- Create the feature branch from the current review commit.
- Add characterization tests for current successful AMT behavior and release commands.
- Record known failures and feed-thread shutdown behavior.
- Do not alter strategy behavior in this phase.

### Phase 1 — Execution safety

- Add stop-capability and stop-lifecycle regression tests.
- Fix `LiveOMS` stop persistence/cancellation and fail-closed handling.
- Fix actual-fill accounting and close identity.
- Add partial/unknown fill and restart reconciliation tests.
- Implement the documented live 50%/25% pyramiding sequence; block it explicitly only when the broker capability contract cannot represent that sequence.

### Phase 2 — AMT decision alignment

- Add provenance and evidence-quality tests.
- Remove synthetic depth from decision input.
- Implement strict directional Triple-A predicates.
- Add Playbook A and LVN-path boundary tests.
- Verify the active analyzer and DTO path uses the same rule engine as direct Triple-A tests.

### Phase 3 — Options and risk

- Remove premium-only AMT eligibility.
- Require underlying option observations and explicit contract/Greek metadata.
- Align spread and expiry policy with the AMT docs.
- Make effective risk configuration observable and test the shipped live values.
- Add quantity-level TP and pyramid tests.

### Phase 4 — Release gates and documentation

- Resolve the three AMT analyzer failures and the AMT/decision/execution failures.
- Make parity and full quant tests exit cleanly.
- Update `docs/amt/`, stale walkthrough/review claims, and architecture diagrams.
- Record any remaining proxy deviations and the exact conditions that make them acceptable.
- Run the complete verification matrix, commit the final docs/test changes, and push the branch.

## Testing Contract

### AMT analytics

- VA and regime-collapse behavior is tested at recent-regime and session-extreme boundaries.
- CVD EMA direction, persistence, and divergence are independently calculated.
- Absorption thresholds, LVN floor/convexity, profiles, footprint, and session context remain covered.
- Triple-A tests include both states, direction-specific CVD, cluster close, VWAP, and setup causality.

### Decision and options

- Required evidence families are tested one by one.
- Proxy evidence is visible in paper/replay and blocked at the live seam.
- Missing depth and missing underlying data cannot produce eligible signals.
- Organic multi-engine fixtures exercise at least one valid AMT setup without relying on a nearby LVN.

### Broker and OMS

Use deterministic fake brokers to cover:

- unsupported/native-stop failure;
- stop acceptance, persistence, cancellation, and restart;
- full fills, partial fills, zero fills, timeouts, and unknown outcomes;
- close retries versus distinct TP stages;
- late fills after a close;
- live pyramid adds and rollback on failure.

Every unsafe outcome must leave a durable reconciliation state and block new entries.

### Release commands

The final branch must run successfully:

```text
make lint
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt
make parity
make pre-release
make test-quant
(cd frontend && npm test -- --run)
```

The verification report must distinguish test pass/fail counts from live-readiness evidence. A green internal test suite alone is not a live deployment approval.

## Documentation and Branch Operations

- Keep the canonical AMT policy and implementation wording synchronized.
- Remove stale claims such as “100% complete” unless the corresponding current command evidence supports them.
- Document every remaining proxy explicitly, including its scope and why it cannot authorize a live entry.
- Commit only intended source, test, and documentation files; do not stage `automation/reports/`.
- Create the branch before implementation, make staged commits, and push normally only after all final local gates pass.
- Do not force-push, create a PR automatically, or use live broker credentials.

## Acceptance Criteria

The work is complete only when:

1. The new branch exists and all intended changes are committed.
2. The final verification commands exit successfully.
3. No known P0/P1 live-safety finding remains open.
4. Required live evidence is exact or explicitly blocked; no synthetic depth authorizes an entry.
5. Triple-A behavior matches the canonical AMT rules and has boundary regression tests.
6. Live stop, partial fill, close identity, reconciliation, and pyramid tests pass with deterministic mocks.
7. Option AMT cannot use premium-only fallback.
8. Effective live risk configuration is observable and covered by tests.
9. AMT docs and review artifacts describe the actual implementation and current evidence.
10. The branch is pushed only after verification; no live order is placed.

## Out of Scope

- Replacing all candle-derived data with exchange-native tick/L2 data.
- Changing already agreed numerical AMT thresholds without a separate parity decision.
- Frontend redesign or unrelated UI refactoring.
- Live broker credentials, live orders, or broker sandbox integration.
- Reverting or folding unrelated untracked worktree changes.
