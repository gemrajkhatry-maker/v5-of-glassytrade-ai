# AMT Production Confidence Review & Certification Plan

## Goal

Answer with evidence: *when the system encounters conditions Fabio would trade, does it consistently reach the same conclusion, take the same trade, size/manage/pyramid/trail/exit identically across replay, paper, and live?*

Deliverables:
1. Certification infrastructure (replay driver, payload-exact golden gates, decision-trace export, audit events, session corpus, CI parity job)
2. Executed certification battery mapped to review Steps 1–15, with scored results
3. Joint expert review document (Fabio Valentini × Dr. Venkat Subramaniam transcript format), every claim cited `file:line`, per-defect template (root cause / risk level / real-money impact / fix / verification), accuracy percentages, Production Confidence Score, APPROVE/REJECT verdict
4. Bounded remediation of verified critical defects + re-certification proving zero unintended drift

## Non-goals

- Full UI workstation redesign (separate plan; only certification-serving UI noted below)
- Unifying the AuctionCoordinator/AMTAnalyzer split-brain (PRINCIPAL_REVIEW P2) unless review escalates it
- Upstox integration; tick-level persistence; new strategy logic beyond defect fixes

## Verified evidence baseline (all personally inspected or explorer-cited)

| # | Finding | Evidence |
|---|---|---|
| E1 | No conviction engine: `_DETERMINISTIC_CONVICTION=0.7` declared, assigned to `agent_probability`, consumed by nothing | quant/runtime.py:74, quant/decision/context_builder.py:24,327 |
| E2 | Direction = discrete priority ladder (initiative → Triple-A → absorption → OBI → CVD), auditable but unscored | context_builder.py:98-136 |
| E3 | Evidence inflation: `tripleAPhase=="AGGRESSION"` ⇒ SetupEvidence with `acceptance=True` unconditionally | context_builder.py:169-174 |
| E4 | VA-fade direction tautology: BALANCED branch condition ≈ fade trigger itself | context_builder.py:128-129 vs va_fade.py:50 |
| E5 | All-gates-pass-but-builder-drops yields `GATE_REJECTED` with empty `block_reasons` | decision_service.py:85-87 |
| E6 | Market state = BALANCED/IMBALANCED only (+DEAD override). No trend/double-distribution/neutral day types | amt/market/state_engine.py:62-104 |
| E7 | Balance-threshold inconsistency: `BALANCE_RATIO_THRESHOLD=0.55` imported, literal `0.5` used | constants.py:93 vs state_engine.py:72 |
| E8 | RegimeDetector (failed-auction re-entry block, contraction filter, squeeze, stop circuit-breaker) implemented+tested but NOT wired into production | amt/market/regime.py; analyzer.py wiring :555-699 |
| E9 | LiveOMS pyramids are ghosts: add_pyramid builds in-memory Position; nothing calls submit for pyramids; PositionOpened fires anyway | live_oms.py:268-312; runtime.py:868-873 |
| E10 | Documented base-SL ratchet after pyramid absent (frozen dataclasses, caller told to ratchet, caller doesn't) | oms.py:86-89 |
| E11 | Pyramids never reserve portfolio open risk (acknowledged shortcut) | runtime.py:812-815 |
| E12 | Stop moves silent: trail ratchet/BREAKEVEN arm emit no event; reason recorded only when moved stop is hit | exit_checks.py:62-123, exits.py:89-182 |
| E13 | Determinism edges: `random.uniform`+wall-clock in history seeding; contract-expiry year from `datetime.now(IST)`; `SessionRisk._today()` wall-clock date; `_to_ist` now() fallback | amt_engine.py:61-67; session_gates.py:88-95; risk.py:16-17; amt/session/context.py:77-97 |
| E14 | Replay tests compare event-type sequences / digests / `(type,time)` tuples — never full payloads | test_golden_tape.py:26-51; test_golden_replay.py:225-241; test_paper_protocol.py:385-389 |
| E15 | 66 fsync JSONL journal days (Aug 23–26) with full decision reasoning exist; no driver replays them through QuantEngine; `replay_journal.py` checks integrity only | backend/journals/; tests/quant/replay_journal.py |
| E16 | Golden dataset (`amt_dataset/live_aligned`) = 750 rows, 100% BALANCED, TRIPLE_A/NO_EDGE only — cannot certify other day types | amt_dataset/live_aligned/*.jsonl |
| E17 | Dhan-only; order terminal state via 0.5s polling; partial fills resolved only at terminal poll (no incremental accumulation); states PENDING/OPEN/FILLED/CANCELLED/REJECTED/CLOSED (no SUBMITTED/ACCEPTED/PARTIALLY_FILLED distinction) | dhan_broker_adapter.py:549-602; shared/entities/models.py:40-47 |
| E18 | Prior audits: split-brain divergence accepted (VAL up to 16% on clamp bars); OHLC.create() Decimal TypeError latent; two audits conclude NOT PRODUCTION READY; acceptance gate report UNMET (304 exits all harness artifacts) | docs/AMT_UNIFICATION.md §3-4; docs/audit/PRODUCTION_REWORK_AUDIT_2026-08-24.md; docs/ACCEPTANCE_GATE_REPORT.md |
| E19 | Strong core: no wall-clock in `_decide`; LLM layer deleted from path; bus synchronous ordered; risk budget persists across restarts; fail-closed live reconciliation | runtime.py:542-593; wiring_advisor.py:20-27; events.py:124-178 |

Expected verdict shape: REJECT for live capital today — driven by E9 (money-loss risk), E3/E4 (wrong trades), E14/E16/E15 (unproven determinism) — convertible toward conditional approval after W4 + re-run.

## Workstream 1 — Certification infrastructure

New code under `tests/quant/certification/` + minimal instrumentation in `quant/`. No behavior change to decision math.

1. **JournalReplayDriver** — read a `backend/journals/*.jsonl`, extract `BarClosed` (+ depth where present), feed through existing SyntheticGateway → QuantEngine, capture complete event trace. CLI: `python -m tests.quant.certification.replay <journal.jsonl>` → exit 0 iff zero divergence vs embedded expectations.
2. **Payload-exact golden assertion** — replace/augment digest comparisons: normalized deep equality of full event payloads (normalize only `event_id`, `correlation_id`, ingest timestamps, PIDs). Any drift in signal math, sizing, stops, trails fails.
3. **DecisionTrace exporter** — per closed bar append the review STEP-1 record: timestamp/symbol/market_data/profile_data/context(market_state, inventory_state, day_type, auction_phase)/setup_candidates/selected_setup/direction_ladder_trace/risk inputs/position_size/trade_decision/block_reasons. Written alongside journals; feeds S1/S7/S8.
4. **Audit events** — new typed events emitted on bus + journaled: `StopMoved{old,new,reason}`, `BreakevenArmed`, `TrailArmed`, `PyramidProposed{evidence}`, `PyramidFilled`, `PyramidOrderRejected`. Wire emission points in ExitEngine/PositionManager/runtime.
5. **Session corpus builder** — script using brokers' Dhan historical service to pull ≥40 recent NSE sessions (NIFTY/BANKNIFTY + 1 MCX) → same bar JSONL format as journals. Companion ground-truth manifest `tests/quant/certification/corpus/manifest.json`: `{date, symbol, expected_day_type, expected_context, expected_bias, labeled_by}`. Prelabel with existing classifiers, flag `labeled_by: "classifier"`; human AMT review is an explicit follow-up task (open question Q2).
6. **CI parity job** — extend `.github/workflows/test.yml` (or Makefile target `make parity`): replay determinism (same journal ×2 engines, payload-exact), 10-run repeat (Step 13), corpus regression subset. Gate must fail on any drift.

## Workstream 2 — Execute certification battery (Steps 1–15)

Runner produces `docs/reviews/certification-results-<date>.md` + machine json. Each step: procedure, PASS/FAIL, metric, evidence links.

- S1 Trace completeness (W1.3 records present for every post-open bar; no field without provenance)
- S2 Market-state accuracy % vs corpus manifest — expect low score honestly reported (only 2 states exist, E6)
- S3 Auction-hypothesis certification: before every approved trade, extractable hypothesis+evidence list; Fabio-agreement checklist in review doc
- S4 Context validation: prior-session levels, gap type, opening bias actually populated at session start (E18 notes functions exist but uncalled in legacy stack — verify v5 path; fix wiring if trivially missing, else defect entry)
- S5 Conviction audit: show exact mechanism (E1/E2). Expected FAIL as "conviction engine"; document ladder as the de-facto model with per-decision trace
- S6 Qualification matrix: per setup type × condition-missing → expect NO_TRADE. Must include E3 inflation case (AGGRESSION without acceptance ⇒ currently TRADES) and E4 tautology case
- S7 False-positive report from journals: trades lacking hypothesis evidence/context agreement
- S8 Missed-opportunity report: strong-context bars with NO_EDGE; classify missing-context vs bad-threshold
- S9 Risk recalculation: independently compute size = equity×risk_pct×expiry_factor / loss_per_lot from journal fields; assert match (tolerance 0) for every entry
- S10 Pyramid audit: every add justified by risk-free base + LVN proximity + fresh absorption + confirming candle (position_manager.py:202-304); live-path ghosting (E9) = automatic FAIL
- S11 Trail certification: every stop move has reason event (requires W1.4)
- S12 OMS lifecycle matrix: full/partial/reject/cancel/modify/disconnect/duplicate/out-of-order callback — scripted against PaperOMS + Dhan adapter mocks; document polling-based partial-fill gap (E17)
- S13 Replay determinism ×10 on ≥5 sessions: payload-exact identity
- S14 Live-vs-replay parity: same recorded session through paper-mode boot path vs replay driver; diff context/signals/stops/exits (broker-dependent steps excluded and listed)
- S15 Journal explainability: sample 20 trades; verify all nine required explanation fields reconstructable without chart

## Workstream 3 — Joint review document

`docs/reviews/2026-08-26-amt-production-confidence-review.md`

Format: ongoing Fabio/Venkat dialogue (not bullets/checklists), organized by the review phases (market understanding → context → conviction → setups → risk → pyramiding → management → OMS → broker → testing → certification → production readiness). Requirements:
- Every technical claim cites `file:line` or battery result ID
- Each defect uses the template: Root Cause / Risk Level (critical-major-minor) / Real Money Impact / Recommended Fix / Verification Method
- Ends with: accuracy table (S2/S4/S5/S6/S9/S10/S11/S12/S13/S14 percentages), Production Confidence Score (0-100), explicit APPROVE/REJECT for live capital
- Defect register seeded from E1-E19 plus anything W2 uncovers; criticals must map to W4 items or carry explicit deferral rationale

## Workstream 4 — Critical defect remediation + re-certification

Bounded to verified defects; each lands with its own test, then full battery re-run. Payload-exact gates (W1.2) prove no unintended drift; intentional behavior changes are listed in the review doc.

1. **Pyramid live path (E9)** — fail-safe default: disable pyramids under LiveOMS until broker submission is implemented end-to-end (propose→submit→fill→linked-close). Alternative (if preferred): wire submit path. Either way `PyramidProposed`/`PyramidFilled` events journaled; test asserts a broker order exists for every live pyramid PositionOpened.
2. **Base-SL ratchet (E10)** — implement ratchet at pyramid fill (base SL → new_sl) or delete the false docstring claim + spec reference. Implementing preferred; frozen-dataclass constraint means rebuilding Position (pattern already used in partial fills).
3. **Pyramid risk reservation (E11)** — register add-on open risk with PortfolioRiskAuthority at fill.
4. **Evidence inflation (E3)** — `acceptance` flag sourced from AcceptanceRejectionEngine output only; AGGRESSION phase no longer implies acceptance. Update affected gate tests; expect trade-count change — captured in S6/S7 delta report.
5. **Empty block_reasons (E5)** — builder drops (thin stop, monotonicity, inverted RR) append `SIGNAL_BUILDER: <reason>`.
6. **Threshold unification (E7)** — single named constant used at state_engine.py:72.
7. **RegimeDetector decision (E8)** — wire failed-auction re-entry block + stop circuit-breaker into runtime guards (they are pure/bar-index-friendly), or formally retire with rationale in review doc. Contraction/squeeze stay advisory-only this pass.
8. **Determinism edge hardening (E13)** — inject date provider into parse_contract_expiry/SessionRisk; deterministic seed policy for history warm-up; `_to_ist` fallback removed in favor of explicit failure.
9. **Stop-move audit (E12)** — consume W1.4 events; S11 passes only with reasons on every move.

## Validation

- `make test` — backend + tests/ + brokers + frontend suites green (baseline ~2,700 passing must not regress)
- `make parity` (new) — journal replay ×2 engines payload-identical; 10-run determinism; corpus subset stable
- `pytest tests/quant/test_certification.py` — S-battery green where applicable, honest FAILs published otherwise
- `python -m tests.quant.certification.replay <journal>` — exit 0 on recorded days Aug 23–26
- `ruff check quant tests` clean
- Review doc published with verdict; every critical defect either fixed or explicitly deferred with rationale

## Failure modes / risks

- **Corpus labeling quality**: classifier prelabels ≠ Fabio ground truth. Manifest carries `labeled_by`; S2 accuracy reported against classifier labels with caveat, human relabel tracked as follow-up.
- **Dhan historical limits**: backfill may need chunked requests/throttling; builder must resume idempotently.
- **Behavior-change blast radius**: E3 fix reduces trade frequency by design; battery deltas quantify it before/after so the review documents intent.
- **Scope creep**: split-brain unification, UI redesign, Upstox stay out; if battery exposes them as blockers, they become defect entries with deferral rationale, not inline work.

## Open questions (defaults chosen; non-blocking)

1. Execute W4 now or after review sign-off? Default: now — every item independently verified as defective; re-certification proves safety.
2. Who performs human AMT labeling of the 40-session manifest? Default: ship classifier prelabels + empty human-review column; labeling is a follow-up task for the user/domain owner.
3. Pyramid live path: hard-disable vs implement broker submission? Default: hard-disable (smallest safe change); implementing submission is offered as alternative within W4.1.
