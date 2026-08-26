# Complexity & Over-Engineering Audit — stable_7 (verified re-run)

**Date:** 2026-08-25 (re-run, numbers re-measured against current source)
**Scope (production):** `backend/app` (8.3k), `backend/config` (0.3k), `quant` (23.4k), `brokers` (14.9k), `shared` (0.7k), `frontend` (8.2k) · ~55.7k LOC · **Tests:** 18.4k LOC (ratio ≈ 0.33)
**Tools:** radon (cyclomatic, Python) · cognitive-complexity lib (Sonar cognitive, Python) · eslint-plugin-sonarjs (cognitive, TS/TSX) · graphify knowledge graph (10,352 nodes / 20,524 edges)
**Exclusions:** `backend/venv`, `node_modules`, `tests/`, `test_*`, `conftest.py`, `.hypothesis`

> Re-run note: the first pass under-reported cyclomatic (it missed `context_builder.build` / `exits.evaluate` at the top). All figures below were re-measured on current source with venv properly excluded. Frontend `OrderFlowCard` dropped from 74 → 43 since the first pass (code drifted); `build` cognitive is 154, not 132.

---

## 1. Cyclomatic Complexity (radon)

Python blocks analyzed: **2,033**. Distribution by risk grade:

| Grade | CC range | Count | % |
|---|---|---:|---:|
| A | 1–5 | 1,642 | 80.8% |
| B | 6–10 | 219 | 10.8% |
| C | 11–15 | 73 | 3.6% |
| D | 16–20 | 48 | 2.4% |
| E | 21–30 | 34 | 1.7% |
| F | 31+ | 17 | 0.8% |

**Worst offenders (CC ≥ 40):**

| CC | Location |
|---:|---|
| 164 | `quant/decision/context_builder.py:98` `build` (class `DecisionContextBuilder` = 165) |
| 86 | `quant/execution/exits.py:89` `evaluate` (16 params) |
| 73 | `quant/llm/advisor.py:162` `_rule_based_narrative` |
| 63 | `backend/app/config_models/validator.py:22` `validate_config` |
| 60 | `quant/amt/session/scanner.py:356` `scan_top_n` |
| 54 | `brokers/broker/dhan/application/services/options_service.py:38` `get_option_chain_async` |
| 54 | `quant/amt/analyzer.py:353` `analyze` (20 params) |
| 54 | `quant/decision/gates_edge.py:19` `gate_triple_a_edge` |
| 49 | `quant/probability/features.py:76` `extract_features` |
| 42 | `quant/decision/stops.py:19` `structural_anchor` |
| 41 | `quant/amt/orderflow/compute.py:21` `compute_order_flow_metrics` |
| 40 | `quant/amt/market/break_detector.py:28` `detect_break` |

Next tier (CC 29–34): `runtime._decide` (34), `market/displacement.detect_displacement_leg` (33), `profile/displacement.detect_displacement_leg` (32), `trade_journal.summary_from_entries` (31), `acceptance_rejection.update` (30), `gameloop._coordinator_viewer_loop` (30), `runtime._run_inner` (29), `signal_builder._structural_tp` (29), `volume_profile.compute_value_area` (29), `exit_rules.check_time_stop_with_price` (29).

## 2. Cognitive Complexity — Python (Sonar rules)

**1,641** functions analyzed; **118** exceed the Sonar default threshold of 15 (**7.2%**).

| Cog | Function |
|---:|---|
| 154 | `quant/decision/context_builder.py:98 build()` |
| 119 | `quant/execution/exits.py:89 evaluate()` |
| 113 | `quant/amt/session/scanner.py:356 scan_top_n` |
| 111 | `brokers/broker/dhan/application/services/options_service.py:38 get_option_chain_async` |
| 98 | `backend/app/config_models/validator.py:22 validate_config` |
| 77 | `quant/llm/advisor.py:162 _rule_based_narrative` |
| 77 | `backend/app/api/websocket/gameloop.py:223 _coordinator_viewer_loop` |
| 64 | `quant/amt/market/break_detector.py:28 detect_break` |
| 61 | `quant/runtime.py:366 _run_inner` |
| 59 | `quant/decision/gates_edge.py:19 gate_triple_a_edge` |
| 57 | `backend/app/main.py:152 create_application` |
| 55 | `quant/brokers/multiplexed_feed.py:300 _consume_loop` |
| 52 | `brokers/broker/dhan/infrastructure/symbol_mapper.py:156 get_security_id` |
| 52 | `quant/probability/features.py:76 extract_features` |
| 49 | `quant/llm/bridge.py:82 extract_llm_json` · `volume_profile.compute_value_area` · `exit_rules.check_time_stop_with_price` · `runtime._decide` |

Duplication signature confirmed: `detect_displacement_leg` exists in both `quant/amt/market/displacement.py:102` (CC 33) and `quant/amt/profile/displacement.py:39` (CC 32).

## 3. Cognitive Complexity — Frontend TS/TSX (threshold 15)

**25** functions over threshold.

| Cog | Function |
|---:|---|
| 67 | `components/chart/AMTLevelsOverlay.ts:73` |
| 54 | `components/MarketSidebar.tsx:33` |
| 43 | `components/ai/OrderFlowCard.tsx:19` |
| 34 | `components/ai/OrderFlowCard.tsx:83` |
| 31 | `components/ai/DiagnosticsPanel.tsx:212` |
| 30 | `components/ai/DiagnosticsPanel.tsx:114` |
| 27 | `components/chart/CandleSeriesManager.ts:92` |
| 26 | `components/ai/QuantDecisionCard.tsx:32` |
| 24 | `components/ai/AgentProbabilityCard.tsx:12` |
| 23 | `components/ai/OverseerCard.tsx:11` · `components/ModelStateBanner.tsx:17` |
| 22 | `components/ai/RecentExitsCard.tsx:18` |
| 20 | `hooks/useServerTradingSystem.ts:335` |
| 16–20 | `AggressionCard`, `InitialBalanceCard`, `ChartScene.tsx` (×2), `textSanitizer`, `DecisionCard`, `AIAdvisorCard` |

Root cause unchanged: inline ternary ladders in JSX instead of small render helpers / lookup maps, and monolithic overlay managers. Seven AI cards each re-implement signed-value bar/color/arrow rendering.

## 4. Over-Engineering Findings (ranked, verified against source)

### OE1 — Config layer sprawl (HIGH)
~1,437 LOC across `backend/config/*` + `backend/app/config_models/*` + YAML envs + feature flags + instruments.json + strategy_resolve + mode_config, fronting a system that runs one strategy on one broker. The 63-CC / 98-Cog `validate_config` is the smell's center of gravity. For a single-strategy scalper, a flat typed dataclass + one loader would remove ~1,000 LOC.

### OE2 — Hand-rolled DI container (MEDIUM-HIGH)
`application/di/container.py` (157 LOC) implements thread-safe lazy singleton resolution with circular-dependency detection and transient scopes, plus a separate `composition_root.py` (166 LOC) — 342 LOC for a fixed startup-wiring problem. A dict of factories used once at startup would do; this is framework-building for a static wiring problem.

### OE3 — Duplicated quant module pairs (MEDIUM)
Five basename pairs in `quant/amt/**`: `market/displacement.py` vs `profile/displacement.py` (genuinely duplicated logic, independent CC 33/32), `market/structure.py` vs `session/structure.py`, `session/npoc.py` vs `contracts/ports/npoc.py`, `compute.py` at two levels (`amt/compute.py` vs `amt/orderflow/compute.py`), `context.py` twice (`session/context.py` vs `decision/context.py`). Some layering is intentional (ports vs impl); displacement is real duplication.

### OE4 — Abstraction budget vs team size (MEDIUM)
24 Protocols, 5 ABC files, 60 `@abstractmethod`. Hexagonal architecture around one broker adapter (Dhan) means most ports have exactly one implementation and no test double that couldn't be a monkeypatched function. Interface clusters: `quant/contracts/ports/config_port.py` (9 interfaces), `brokers/broker/ports.py` (6), `brokers/broker/dhan/ports/` (6). Most are single-implementation property bags (YAGNI).

### OE5 — Dead code (LOW, easy wins)
- `quant/execution/live_oms.py` — zero importers; referenced only as `"unwired"` flag strings (`health.py:86`, `composition_root.py:144`, `multi_engine.py:167,500,504`). `close()` raises NotImplementedError. Delete.
- `backend/app/application/handlers/`, `backend/app/domain/models/`, `backend/app/infrastructure/strategies/` — empty shells (only `__pycache__` / `__init__.py`). Delete.
- `backend/app/core/async_boundary.py` — 9-line pure re-export shim of `quant/contracts/sync_boundary.py`; 4 importers (`health.py`, `trading.py`, `main.py`, `startup_reconciliation.py`) to repoint, then delete.

### OE6 — God objects (MEDIUM)
- `AMTAnalyzer` — 1,033 LOC, 185 graph edges, `analyze()` takes 20 params.
- `DecisionContextBuilder.build` — CC 164 / Cog 154, field-by-field copying; wants a `DecisionInputs` struct.
- `ExitEngine.evaluate` — 16 params, CC 86 / Cog 119; extract per-exit-rule predicates into a rule list.

### OE7 — Frontend JSX ternary pyramids (LOW-MED)
Not architectural over-engineering but accidental complexity: every AI card re-implements signed-value bar/color/arrow rendering with nested ternaries (Cog 43+34 in OrderFlowCard). One `<SignedBar value={...}/>` primitive deletes hundreds of lines.

### Non-findings (healthy)
- No import cycles (graphify).
- Re-export shims from the stable_4 era are gone; only empty `__init__.py`s remain.
- Frontend state management is proportionate: zustand + one large hook.
- Test-to-code ratio ~0.33 is reasonable for this domain.
- 80.8% of Python blocks grade A — complexity is concentrated, not systemic.

---

## 5. Top 10 Refactor Targets (complexity × criticality)

1. `context_builder.build` (CC 164 / Cog 154) — introduce a `DecisionInputs` struct; kill field-by-field copying
2. `exits.evaluate` (86 / 119, 16 params) — extract per-exit-rule predicates into a rule list
3. `validate_config` (63 / 98) — split per-section validators; shrinks with OE1 fix
4. `scan_top_n` (60 / 113) — extract scoring vs selection phases
5. `get_option_chain_async` (54 / 111) — decompose fetch/parse/retry stages
6. `analyzer.analyze` (54, 20 params) — collapse the mega-signature into a context object
7. `_rule_based_narrative` (73 / 77) — table-drive the narrative branches
8. `_coordinator_viewer_loop` (30 / 77) — extract message-type handlers
9. `AMTLevelsOverlay.ts:73` (67) — split level classification from drawing
10. `OrderFlowCard` + AI cards — shared `<SignedBar/>` component (deletes OE7)

## 6. Verdict

The architecture is fundamentally sound post-consolidation (no cycles, no shim layer, layered cleanly; 80.8% of blocks grade A). Complexity concentrates in ~15 hot functions rather than spreading evenly, which is good news: targeted extraction fixes it. The remaining over-engineering is infrastructure-for-infrastructure's-sake — the config stack and DI container together cost roughly 1,800 LOC serving wiring that could be nearly static, and the port/Protocol budget is sized for a multi-broker future that doesn't exist.

**The structural irony:** the codebase is over-engineered where it's safe (config, DI, ports for a live path that isn't wired) and under-engineered where it matters. Per `docs/architecture/2026-08-24-principal-rearchitecture.md`, live fills never leave `PaperOMS`, `IBroker.execute_order` has no production caller, and the engine never persists positions. The abstraction budget should move from wiring infrastructure to the money path.

---

## Addendum — Revalidation 18:45 IST (multi-agent execution pass)

Corrections to this audit discovered while executing the refactor program:

1. **"Dead `allow_trend`/`allow_reversion` payload" is RESOLVED — and was a live regression, not just dead code.** Commit `ae0d832` rebuilt the gates without consumers of `SessionInfo.allow_trend/allow_reversion`, so midday consolidation approved TRIPLE_A trend entries that the Fabio methodology requires blocking (`test_scenario_midday_blocks_trend_continuation`). Fixed at `7e7ee97`: gate 1 now enforces phase setup permissions (momentum family vs `VA_FADE`), unit guard at `tests/quant/decision/test_gate1_phase_permissions.py`. Do **not** delete these fields from `DecisionContext`.

2. **"Dual broker abstraction / delete `quant/contracts/ports/broker.py`" was WRONG.** `IBroker` (quant port) is implemented by `app.infrastructure.adapters.dhan_broker_adapter.DhanBrokerAdapter` AND `paper_broker.PaperBrokerAdapter`, resolved through `composition_root`, consumed by `backend/app/main.py`. It is a genuine 2-implementation seam. Corrected annotation committed at `c6ede83`. What *is* still dead: the `LiveOMS` class itself (plus its test), pending spec open-decision #1 — note OE5's "referenced only as unwired flag strings" detail for the cleanup.

3. **Baseline drift:** known failures are now 1 deterministic (none — midday fixed) + 2 load flakes (`test_vah_always_geq_val` hypothesis deadline; `test_seed_starts_staggered_across_engines` timing). Fresh full-suite numbers recorded in the refactor-program spec.

4. **Complexity figures unchanged** on re-measure (lizard): `build` CCN 164/16 params (grew to 304 NLOC), `evaluate` 86/17, `_rule_based_narrative` 73, `scan_top_n` 60, `analyze` 54 + `_build_result` 66 params.

## Addendum — Deep validation pass (Block 0 post-execution)

Findings from the independent validation pass over the landed Block-0 commits (`f26dceb`, `a2ece59`, `04a345b`, `35e6015`):

1. **The `decide_long.json` 154→307 regolden was MIS-ATTRIBUTED to F2** (including in the `a2ece59` commit message — corrected here; history left intact). Evidence: replaying HEAD with explicit legacy knobs (`time_stop_bars=60, cooldown_bars=5`) reproduces 307/0 identically; a full 85-commit scan shows the old signature (154 decisions, 1 approval) intact through `968819a`, and commits `58a0abf`..`7e7ee97` cannot even be checked out standalone (imports of not-yet-committed modules — see item 4). Mechanism: the old engine stopped deciding after its single bar-154 approval opened a position (154 decide-calls then exit-only); today's engine never fills, so it decides every bar (307). The approval vanished because `ae0d832`'s Triple-A decision-core rework makes this synthetic fixture never form a valid setup (all decisions `NO_EDGE: No Triple-A edge`). Combined with `7e7ee97`'s deliberate SESSION_PHASE tightening, the new trace is the expected product of intended gate hardening — **the regolden itself remains accepted**, but its stated cause was wrong.

2. **Coverage gap (pre-existing, now explicit): there is no end-to-end positive approval test.** Every `SignalApproved` assertion in runtime tests is negative (`not any(...)`); gate units pass only with hand-injected AGGRESSION contexts. Since `ae0d832`, nothing proves the engine can approve and fill from organic data. WS2-A should add a positive-path fixture before further extraction refactors.

3. **F1/F3/F4 verified clean beyond suites:** zero bare-UTC constructions remain in ChartScene (9 `toISTTimestamp` sites, incl. the live tick handler recovered during execution); zero MLX env reads outside `quant/wiring_advisor.py`; advisor shutdown wired defensively in `_stop_engine`. F2 derivation is behavior-neutral at current live config (`interval_seconds=60` derives exactly the legacy 60/5) and protective only for future timeframe changes. Residual F2 loose end: `AmtScalpingStrategy(time_stop_bars=60)` keeps a literal default for standalone constructions (engine path always injects derived values) — fold into WS2-B.

4. **Pure HEAD does not collect, and worse:** `tests/quant/test_compression_box.py` and `tests/quant/test_range_bars.py` are tracked but their modules were deleted in `ae0d832` (2 collection import errors on any clean checkout). After dropping those two, pure HEAD still fails **15 tests** across llm/gates/session/system/e2e — every sampled case is a paired change split at the commit boundary: committed tests reference `DecisionContext(recent_decisions=...)`, a gate4 anchor retune (80.0), and post-hardening registry expectations whose code/test halves ride in the uncommitted working tree. None involve Block-0 files (`ChartScene.tsx`, runtime knob derivation, advisor injection/shutdown — all verified green against the working-tree baseline, which is the effective development state). Orphaned tests dropped in a follow-up chore commit; the remaining 15 resolve when the pending WIP halves are committed, and are recorded here so nobody mistakes them for regressions from the refactor program.
