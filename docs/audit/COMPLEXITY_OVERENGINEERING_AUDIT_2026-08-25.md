# Complexity & Over-Engineering Audit — stable_7

**Date:** 2026-08-25 · **Scope:** `backend/app` (24.3k), `quant` (23.1k), `brokers` (22.1k), `frontend` (11.9k), `shared` (0.7k) · **Tests:** 19k LOC
**Tools:** radon (cyclomatic, Python) · eslint-plugin-sonarjs (cognitive, TS/TSX) · cognitive-complexity lib (Sonar cognitive, Python) · graphify knowledge graph

---

## 1. Cyclomatic Complexity (radon)

Python blocks analyzed: 2,608. Distribution by risk grade:

| Grade | CC range | Count |
|---|---|---|
| A | 1–5 | ~2,440 |
| B | 6–10 | ~130 |
| C | 11–15 | 30 |
| D | 16–20 | 10 |
| E | 21–30 | 2 |

**Worst offenders (CC ≥ 20):**

| CC | Location |
|---|---|
| 63 | `backend/app/config_models/validator.py:22` `validate_config` |
| 31 | `quant/runtime.py:515` `QuantEngine._decide` |
| 31 | `backend/app/application/services/trade_journal.py:900` `summary_from_entries` |
| 30 | `backend/app/api/websocket/gameloop.py:223` `_coordinator_viewer_loop` |
| 29 | `quant/runtime.py:358` `_run_inner` |
| 23 | `trade_journal.py:963` · `dhan_adapter.py get_nearest_futures` · `multiplexed_feed._consume_loop` · `position_manager.check_pyramid` |
| 21–22 | `trading_query_service.build_lifecycle_summary` · `dhan_broker_adapter.execute_order` |

## 2. Cognitive Complexity — Python (Sonar rules)

2,171 functions analyzed. 109 functions exceed the Sonar default threshold of 15 (~5%).

Top offenders are the real decision paths of the trading system:

| CC | Function |
|---|---:|
| 132 | `quant/decision/context_builder.py:98 build()` |
| 119 | `quant/execution/exits.py:89 evaluate()` |
| 111 | `brokers/broker/dhan/application/services/options_service.py:38 get_option_chain_async` |
| 106 | `quant/amt/session/scanner.py:356 scan_top_n` |
| 98 | `backend/app/config_models/validator.py:22 validate_config` |
| 77 | `backend/app/api/websocket/gameloop.py:223 _coordinator_viewer_loop` |
| 69 | `quant/decision/gates_edge.py:19 gate_triple_a_edge` |
| 64 | `quant/amt/market/break_detector.py:28 detect_break` |
| 61 | `quant/runtime.py:358 _run_inner` |
| 57 | `backend/app/main.py:152 create_application` |
| 55 | `quant/brokers/multiplexed_feed.py:300 _consume_loop` |

Note the duplication signature: `detect_displacement_leg` exists in both `quant/amt/profile/displacement.py` (43) and `quant/amt/market/displacement.py` (102).

## 3. Cognitive Complexity — Frontend TS/TSX (threshold 15)

29 functions over threshold across 18 files.

| CC | Function |
|---|---:|
| 74 | `components/ai/OrderFlowCard.tsx:19` (JSX ternary pyramids for OFI/CVD bars) |
| 69 | `components/chart/AMTLevelsOverlay.ts:73` |
| 59 | `components/MarketSidebar.tsx:33` |
| 38 | `OrderFlowCard.tsx:83` |
| 36 | `ai/DiagnosticsPanel.tsx:212` |
| 32 | `chart/CandleSeriesManager.ts:92` · `DiagnosticsPanel.tsx:114` |
| 28 | `ai/QuantDecisionCard.tsx:32` |
| 25 | `ModelStateBanner.tsx:17` |
| 23–16 | useServerTradingSystem.ts (3 fns), ChartScene.tsx (5 fns), remaining AI cards |

Root causes: inline ternary ladders in JSX instead of small render helpers or lookup maps, and monolithic overlay managers.

## 4. Over-Engineering Findings (ranked)

### OE1 — Config layer sprawl (HIGH)
~1,475 LOC across `backend/config/*.py` + `backend/app/config_models/*` + YAML envs + feature flags + instruments.json + strategy_resolve + mode_config, fronting a system that runs one strategy on one broker. The 63-CC / 98-COG `validate_config` is the smell's center of gravity. For a single-strategy scalper, a flat typed dataclass + one loader would remove ~1,000 LOC.

### OE2 — Hand-rolled DI container (MEDIUM-HIGH)
`application/di/container.py` implements thread-safe lazy singleton resolution with circular-dependency detection, transient scopes, plus a separate `composition_root.py` (166 LOC). The container docstring says it replaced "if/elif chains in ServiceGraph._create_service()". A dict of factories used once at startup would do; this is framework-building for a fixed wiring problem.

### OE3 — Duplicated quant module pairs (MEDIUM)
Five basename pairs in `quant/amt/**`: `market/displacement.py` vs `profile/displacement.py`, `market/structure.py` vs `session/structure.py`, `session/npoc.py` vs `contracts/ports/npoc.py`, `compute.py` at two levels, `context.py` twice. Some layering is intentional (ports vs impl) but displacement is genuinely duplicated logic with independent complexity scores.

### OE4 — Abstraction budget vs team size (MEDIUM)
24 Protocols, 9 ABCs, 59 @abstractmethod, ~65 registry/factory hits, 93 deferred imports inside functions. Hexagonal architecture around one broker adapter (Dhan) means most ports have exactly one implementation and no test double that couldn't be a monkeypatched function.

### OE5 — Frontend JSX ternary pyramids (LOW-MED)
Not architectural over-engineering but accidental complexity: every AI card re-implements signed-value bar/color/arrow rendering with nested ternaries (CC 74 in OrderFlowCard). One `<SignedBar value={...}/>` primitive deletes hundreds of lines.

### Non-findings (healthy)
- No import cycles (graphify).
- Re-export shims from the stable_4 era are gone; only empty `__init__.py`s remain.
- `handlers/` and `domain/models/` are empty shells (just `__pycache__`) - delete candidates.
- Frontend state management is proportionate: zustand + one 709-line hook.
- Test-to-code ratio ~0.39 is reasonable for this domain.

---

## 5. Top 10 Refactor Targets (complexity × criticality)

1. `validate_config` (63/98) - split per-section validators; shrinks with OE1 fix
2. `context_builder.build` (132 COG, 12 params) - introduce a `DecisionInputs` struct; kill field-by-field copying
3. `exits.evaluate` (119) - extract per-exit-rule predicates into a rule list
4. `get_option_chain_async` (111) - decompose fetch/parse/retry stages
5. `scan_top_n` (106) - extract scoring vs selection phases
6. `_coordinator_viewer_loop` (77/30) - extract message-type handlers
7. `AMTLevelsOverlay.ts:73` (69) - split level classification from drawing
8. `MarketSidebar.tsx:33` (59) - extract row renderers
9. `OrderFlowCard` (74/38) - shared SignedBar component
10. `runtime._decide`/`_run_inner` (42/61) - gate pipeline already exists; route through it

## 6. Verdict

The architecture is fundamentally sound post-consolidation (no cycles, no shim layer, layered cleanly). Complexity concentrates in ~15 hot functions rather than being spread evenly, which is good news: targeted extraction fixes it. The over-engineering that remains is concentrated in infrastructure-for-infrastructure's-sake: the config stack and DI container together cost roughly 1,800 LOC serving wiring that could be nearly static. Neither hides bugs today, but both tax every future change.

---

## Addendum — Second-Pass Findings (verified against source)

A second graph-traversal/deep-analysis pass produced additional claims. Each was verified line-by-line before inclusion:

| Finding | Verdict | Evidence |
|---|---|---|
| `LLMAdvisor` instantiated in engine hot path (daemon thread, MLX model, queue+lock) | ✅ Confirmed | `quant/runtime.py:268`, thread at `quant/llm/advisor.py:45`, MLX imports at `advisor.py:91,125` |
| Gate exceptions swallowed and reported as legitimate rejects | ✅ Confirmed | `quant/decision/pipeline.py:33` → `GateResult(gate_no, False, f"error: {exc}")` |
| `ExitEngine.evaluate` takes 16 parameters | ✅ Confirmed | exactly 16 params, `quant/execution/exits.py` |
| Duplicate `Position` entity models | ✅ Confirmed | `quant/contracts/entities.py:86` vs `quant/execution/order.py:14`; dual port stack (`IBrokerPort` ABC at `brokers/broker/ports.py:87` wrapping broker-level `IBroker`) |
| Dead speculative OMS (`LiveOMS`) never wired | ✅ Confirmed | `quant/execution/live_oms.py` has zero importers; `close()` raises NotImplementedError |
| Thread-per-symbol engines + multi-lock hierarchy | ✅ Confirmed | `_lock`, `_lifecycle_lock` in `quant/multi_engine.py`; worker spawn at `multi_engine.py:524` |
| Stringly-typed session phase (`"OPENING_NOISE"`) | ✅ Confirmed | raw string compare at `quant/llm/advisor.py:233` |
| `__del__` GC-based finalizer on broker | ✅ Confirmed | `brokers/broker/dhan/application/broker.py:352` |
| Mega-hook WS handler (~300-line inline closure, 5-deep nesting) | ✅ Confirmed | `frontend/hooks/useServerTradingSystem.ts:335` (~375-line span) |
| `AMTAnalyzer.analyze` mega-signature / god object | ✅ Confirmed | 18 params, `quant/amt/analyzer.py` (1,033 LOC) |
| Position triple-state desync risk (`_position` / `_pyramid_count` / `_pyramid_positions`) | ✅ Confirmed | three manually-synced fields, `quant/runtime.py:250-256,345` |
| Sidecar background event loop (`_run_async` persistent loop thread) | ❌ **Stale** | already removed; `quant/contracts/sync_boundary.py` is 43 lines, zero threading. Leftover `backend/app/core/async_boundary.py` is now a pure re-export shim (deletion candidate) |

Protocol inventory correction: the interface count is higher than first audited — ~24 Protocols + 9 ABCs across `quant/contracts/ports/config_port.py` (9 interfaces), `brokers/broker/dhan/ports/` (6), `brokers/broker/ports.py` (5+). Most are single-implementation property bags (YAGNI). Covered by WS4/WS6 collapse.
