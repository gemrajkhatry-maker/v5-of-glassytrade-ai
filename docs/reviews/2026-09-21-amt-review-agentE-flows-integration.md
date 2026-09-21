# Agent E — Pipeline & Integration Seams Review vs docs/amt

**Auditor:** Agent E (pipeline / integration seams assignment: ingestion → bars → analyzer → DecisionContext → decision → OMS)
**Date:** 2026-09-21
**Spec under review:** `docs/amt/` — `AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md` (§2, §3, §11, §15, §16), `fabio_decision_pipeline.md` (field table + Gate 3), `multi_symbol_isolation.md`, `TIMESFM_INTEGRATION.md`
**Code under review:** the 8 seams — `quant/brokers/*`, `quant/{ws_adapter,ws_contract,aggregator,bars}.py`, `quant/amt/{analyzer,triple_a,dto}.py`, `quant/amt_engine.py`, `quant/decision/{context,context_builder,signal_builder,decision_service,pipeline,data_quality}.py`, `quant/decision/gates*`, `quant/engine/{decision_loop,submission_handler,tick_handler}.py`, `quant/execution/{oms,live_oms,risk,exits,broker_mapper}.py`, `quant/runtime.py`, `quant/multi_engine.py`, `quant/state.py`, `backend/app/api/websocket/gameloop.py`, `backend/app/api/routers/trading.py`

## Verdict: FAIL

The transport and aggregation plumbing is sound: the delta sign convention is consistent end-to-end (tick → bar → analyzer → CVD → footprint, no flip anywhere), the Triple-A machine is genuinely live and reset on session rollover, TimesFM is correctly fire-and-forget and never in the gate path, the multi-symbol isolation contract holds (one feed, per-symbol gateways, per-symbol engines, one thread each), and the backend gameloop is a thin transport over the engine's own snapshot.

But **the DecisionContext contract is broken at three independent points**: two gate inputs have no producer at all (`cvd_divergence`, `bias_direction`/`bias_confidence`), two more context fields are read by `va_fade` but never populated (`session_extreme_low`/`session_extreme_high`), and two data-quality provenance branches are unreachable because of a name drift and an unpassed parameter. Every one of these fails *open* — the gate or consumer silently treats the missing value as "no conflict" / "no data" and lets the trade through. A pipeline whose safety guards can be silently disabled by a typo is not production-grade.

**Defect count: 9** — 3 CRITICAL, 4 HIGH, 2 MEDIUM

---

## Seam Map

| # | Seam | Producer (file:line) | Consumer (file:line) | Status |
|---|---|---|---|---|
| 1 | Tick ingestion → gateway | `multiplexed_feed.py` (up-tick → `buy_volume`) | `aggregator.py:132-133` | **PASS** — sign convention consistent, see Verified Correct |
| 2 | Bars → AMT analyzer | `aggregator.py` (`bar.delta`), `amt_engine.py:441-449` (`FloatOHLC(delta=bar.delta)`) | `analyzer.analyze()` → `cvd.py:111-113` (`self._cvd += candle.delta`) | **FAIL** — `cvd_source` never passed (D-E5); footprint name drift (D-E4) |
| 3 | Analyzer → DTO | `analyzer.py:_build_result` → `dto.py:amt_result_to_dto` | `context_builder.py:584-600` | **FAIL** — `session_extreme_low/high`, `bias_*` absent from DTO (D-E2) |
| 4 | DTO → DecisionContext | `context_builder.py:build()` | `gates_edge.py`, `va_fade.py`, `gates_rr.py` | **FAIL** — `cvd_divergence` never set (D-E1); `session_extreme_*` never set (D-E2); `bias_*` never set (D-E3) |
| 5 | Context → gates → signal | `gates_edge.py:gate_triple_a_edge` | `signal_builder.py` | **FAIL** — CVD conflict thresholds inverted vs spec (D-E6) |
| 6 | Signal → OMS | `signal_builder.py`, `broker_mapper.py:29-36` | `oms.py` / `live_oms.py` | **FAIL** — live pyramiding hard-disabled (D-E7) |
| 7 | Engine state → UI | `multi_engine.py:984 snapshot()` / `_compose_view_state:954` | `gameloop.py` (thin transport) | **PASS** |
| 8 | Multi-symbol isolation | `multi_engine.py:395` (one `MultiplexedMarketFeed`), `:397` (per-symbol `LiveGateway`), `:1830 _spawn_engine` | per-symbol `QuantEngine` on own thread | **PASS** — verified by `tests/quant/coordinator/test_multi_symbol_isolation.py` (9 passed) |

---

## Defects

### D-E1 — CRITICAL: `cvd_divergence` gate input is dead code (gate fails open)

**Spec:** `fabio_decision_pipeline.md:106-107` Gate 3 guard "CVD conflict" is the veto that blocks an entry when order flow opposes the trade direction. The divergence sub-check is part of that guard family.

**Code:** `quant/decision/gates_edge.py:200-205` reads it:
```python
cvd_divergence = getattr(ctx, "cvd_divergence", "")
if cvd_divergence:
    if ctx.agent_direction == "LONG" and cvd_divergence != "BULLISH_DIV":
        return GateResult(3, False, f"CVD divergence {cvd_divergence} conflicts with LONG")
    if ctx.agent_direction == "SHORT" and cvd_divergence != "BEARISH_DIV":
        return GateResult(3, False, f"CVD divergence {cvd_divergence} conflicts with SHORT")
```

**Producer:** none. `quant/decision/context.py` declares no `cvd_divergence` field (verified: `'cvd_divergence' in ctx` → `False` for a constructed context). `context_builder.py` never sets it. The AMT analyzer *does* compute real divergences (`quant/amt/compute.py:221-224`, genuine half-window swing comparisons — confirmed correct by Agent A), and the DTO carries a `cvdSlope` key, but the divergence *string* is never mapped into the context.

**Impact:** `getattr(ctx, "cvd_divergence", "")` evaluates to `""` on every bar of every session. The entire divergence-alignment guard is dead. Because the guard only ever *blocks*, a permanently-empty value means the check can never fire — silent fail-open. This is the textbook defect this assignment was told to hunt (`Optional=None` / `getattr` default read by a gate).

**Fix:** add `cvd_divergence: str = ""` to `DecisionContext` and populate it in `context_builder.build()` from the DTO's divergence field (map the `compute.py` `"BULLISH_DIV"`/`"BEARISH_DIV"` strings verbatim — they already match what the gate compares against).

---

### D-E2 — CRITICAL: `session_extreme_low`/`session_extreme_high` declared, consumed, never produced

**Spec:** `fabio_decision_pipeline.md` field table lists session extremes as VA-fade inputs; `va_fade.py` uses them to reject fades that have already extended to the session edge.

**Code — declaration:** `quant/decision/context.py:168-169`
**Code — consumer:** `quant/decision/va_fade.py:64-65`
```python
session_low = getattr(ctx, "session_extreme_low", 0.0) or 0.0
session_high = getattr(ctx, "session_extreme_high", 0.0) or 0.0
```

**Producer:** none. An AST-level diff of the fields `context_builder.build()` sets against the fields `context.py` declares yields exactly four missing names: `bias_direction`, `bias_confidence`, `session_extreme_low`, `session_extreme_high`. The DTO is not a producer either: `'session_extreme_low' in dto` and `'session_extreme_high' in dto` both → `False` (`amt_result_to_dto` has no such keys).

**Impact:** both guards degenerate to `0.0`, so every "price at session extreme, fade invalid" check compares against zero and never trips. Fail-open again. The `or 0.0` double-default makes it worse: even if the field were later added to the dataclass as `float | None`, a `None` would still read as `0.0`.

**Fix:** emit `sessionExtremeLow`/`sessionExtremeHigh` in `amt_result_to_dto` from the analyzer's tracked session high/low, and map them in `context_builder`.

---

### D-E3 — CRITICAL: `bias_direction` / `bias_confidence` never resolved

**Spec:** `fabio_decision_pipeline.md` — 15m bias is a required context input; `FABIO_BIAS_OVERRIDE_THRESHOLD = 0.60` (`constants.py:236`) exists to gate bias overrides.

**Code:** `quant/decision/context.py` declares both fields. `quant/decision/context_builder.py:12` imports `BiasResolver` — but never instantiates it and never calls it. No other module sets these fields.

**Impact:** the 15-minute bias is a *declared* concept with a resolver import and a threshold constant and zero producers. Any downstream consumer reading bias sees the dataclass default (empty/zero), i.e. "no bias," which is not the same as "bias unknown — refuse to trade." The dangling import is the smoking gun: the wiring was written and then abandoned.

**Fix:** construct `BiasResolver` in `ContextBuilder.__init__`, call it in `build()` with the 15m series, and populate both fields. If 15m data is unavailable in live, the honest default is to fail closed (block the override path), not to report a synthetic zero-confidence bias.

---

### D-E4 — HIGH: footprint provenance can never be `TICK_EXACT` (attribute name drift)

**Code:** `quant/amt/analyzer.py:1007` passes the footprint into provenance computation:
```python
evidence_provenance = self._compute_evidence_provenance(
    getattr(self, '_footprint_accumulator', None), cvd_state, order_book, ...
```
but `_footprint_accumulator` is **never assigned on `AMTAnalyzer`** (proved: `re.search(r'self\._footprint_accumulator\s*=', analyzer source)` → no match; `hasattr(analyzer, '_footprint_accumulator')` → `False`). The analyzer's `analyze()` signature has a real `footprint_accumulator` parameter used at `analyzer.py:557`, and `AMTEngine` correctly passes it (`amt_engine.py:479`: `footprint_accumulator=self._footprint`, where `self._footprint = TickFootprintAccumulator()` at `:156`). So `_build_result` name-drifts away from a value the caller actually supplied.

**Impact:** `_compute_evidence_provenance` (`analyzer.py:938`) reads `if footprint_accumulator and _footprints:` with a permanently-`None` first argument → `footprint_imbalance` provenance is capped at `CANDLE_DISTRIBUTED` (`:941`) even when live tick footprints exist. The live-safety data-quality contract (`data_quality.py`) therefore understates the evidence quality on every live bar.

**Fix:** in `_build_result`, reference the parameter name in scope (the `footprint_accumulator` argument passed into `_build_result`), not `self._footprint_accumulator`.

---

### D-E5 — HIGH: `cvd_source` is never passed, so `cvd_delta` provenance can never be `TICK_EXACT`

**Code:** `quant/amt/analyzer.py:946`
```python
if cvd_state and cvd_source in ("underlying", "option"):
    provenance["cvd_delta"] = DataQuality.TICK_EXACT
```
`cvd_source` defaults to `""` (`analyzer.py:409`). `AMTEngine` calls `analyze()` twice — at seed (`amt_engine.py:367`) and per bar close (`:465`) — and **never passes `cvd_source`** (proved: `'cvd_source' in amt_engine source` → 0 occurrences). `AMTEngine` always knows which it is: `self._underlying()` vs `self.symbol`.

**Impact:** the second TICK_EXACT branch is unreachable; live CVD is reported `CANDLE_DISTRIBUTED` forever. Same silent-understatement class as D-E4, and the two compound: `DataQuality` gating that the spec says should reflect live tick evidence instead reports candle-level for *both* order-flow families.

**Fix:** pass `cvd_source="underlying" if self._underlying_gateway is not None else "option"` at both `AMTEngine` call sites.

---

### D-E6 — HIGH: CVD conflict thresholds are inverted vs spec, in two independent places

**Spec:** `fabio_decision_pipeline.md:106-107`
```
| CVD conflict (LONG)  | cvd_slope < -0.3 (NSE) or < -0.5 (MCX) |
| CVD conflict (SHORT) | cvd_slope > 0.3 (NSE) or > 0.5 (MCX)   |
```
So NSE = ±0.3, MCX = ±0.5.

**Code (a) — the constant table:** `quant/contracts/constants.py:232-233`
```python
FABIO_CVD_THRESHOLD_NSE: float = 0.5     # CVD slope threshold for NSE
FABIO_CVD_THRESHOLD_MCX: float = 0.3     # CVD slope threshold for MCX
```
Swapped relative to the spec.

**Code (b) — the duplicated source in the gate:** `quant/decision/gates_edge.py:192-193`
```python
cvd_block_neg = -0.3 if str(market).upper() == "MCX" else -0.5
cvd_block_pos = 0.3 if str(market).upper() == "MCX" else 0.5
```
These literals are *also* inverted vs the spec, and they ignore the constants entirely — two independent sources of truth for one number, both wrong, neither matching the spec, and no test pins either.

**Consumer of the constants:** `context_builder.py:181`
```python
cvd_threshold = FABIO_CVD_THRESHOLD_MCX if str(market).upper() == "MCX" else FABIO_CVD_THRESHOLD_NSE
```
used by `_resolve_direction` for the *direction* resolution thresholds. So the constants are live in the signal path, and the gate that is supposed to veto conflicts hardcodes its own different values. Fixing only the constants leaves the gate literals wrong; fixing only the gate leaves the constants wrong.

**Impact:** on NSE, the CVD-conflict veto needs a much larger opposing slope (0.5) to fire than the spec's 0.3 — i.e. the veto is *harder* to trip than designed on the primary exchange, and on MCX it is *easier* (0.3 vs 0.5). A safety veto with exchange-dependent sensitivity inverted from spec.

**Fix:** set `FABIO_CVD_THRESHOLD_NSE = 0.3`, `FABIO_CVD_THRESHOLD_MCX = 0.5`, delete the literals in `gates_edge._check_guards`, and import the constants there so there is one source of truth.

---

### D-E7 — HIGH: pyramiding is hard-disabled under LiveOMS, contradicting spec §13.2

**Spec:** `AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md §13.2` requires pyramiding as part of the scaling-out/scaling-in model.

**Code:** `quant/execution/live_oms.py` (~line 485)
```python
raise ValueError("E9: pyramids disabled under LiveOMS")
```
The pyramid-authorization path that reaches it depends on `ExitEngine.is_risk_free` (`quant/execution/exits.py:108`, the 0.8R breakeven floor), which is computed correctly — but the LiveOMS branch rejects the request outright.

**Impact:** any pyramid signal generated in live trading (paper mode permits it) raises instead of executing. In live, an in-flight pyramid attempt becomes an exception inside the submission handler, which is exactly the kind of unhandled seam failure that can take an engine thread down mid-position. This is a live/paper behavior asymmetry, not a stub: paper trains a behavior live refuses to perform.

**Fix:** either implement live pyramiding (the risk floor already exists) or make LiveOMS return a structured rejection the decision loop handles gracefully instead of raising; and until then, prevent the pyramid signal from being generated at all in live mode so paper and live agree.

---

### D-E8 — MEDIUM: forming-candle footprint is absent at bar-close analyze time (footprints always N-1)

**Code:** `quant/amt/orderflow/footprint.py` — `TickFootprintAccumulator.on_tick` finalizes a candle only when `candle_time` *changes* on a subsequent tick. `AMTEngine.analyze(bar)` runs on the bar-closed callback (`runtime.py:1078`), and `get_all()` therefore returns footprints up to the *previous* candle; the just-closed candle's footprint is not yet in the list.

**Impact:** footprint evidence used at the decision instant is one bar stale, and the just-closed bar's intra-bar aggression distribution is unavailable to the very gate that needs it. Not a crash and not a silent default — a structural one-bar lag in one evidence family. Also interacts with D-E4: the provenance branch that would report `CANDLE_DISTRIBUTED` for this data is the honest label, but it's mislabeled as unreachable for a different reason.

**Fix:** finalize the current candle when the bar-close callback fires (flush on close), or key the footprint accumulator off the bar-close event rather than off the next tick's timestamp.

---

### D-E9 — MEDIUM: the 1-minute micro-aggregator entry trigger is never constructed in default configuration

**Code:** `quant/runtime.py:386-391`
```python
MICRO_SEC = 60
self._micro_aggregator = (
    BarAggregator(interval_seconds=MICRO_SEC)
    if interval_seconds > MICRO_SEC
    else None
)
```
The coordinator default is `"interval_seconds": 60` (`multi_engine.py:266`), and `60 > 60` is `False`, so `_micro_aggregator is None`. The comment at `runtime.py:385` states the intent: "60s micro aggregator drives 1-min entry triggers while 5-min aggregator retains macro AMT context." At the default interval the micro path is inert, and the decision path falls back to `_on_bar_closed`'s `elif self._micro_aggregator is None: self._decide(amt_dto, bar)` (`runtime.py:1087`), i.e. entries evaluate on the macro bar only.

**Impact:** the 1-minute trigger cadence the design calls for is only active when an operator configures an interval *strictly greater* than 60s (e.g. 300s, as one test does). Nothing warns the operator that the default silently disables it. This is a configuration-seam trap rather than a wrong value: the code is correct at 300s and inert at 60s, and the default picks the inert branch.

**Fix:** either make the default honor the documented design (construct the micro aggregator when `interval_seconds >= MICRO_SEC` is intended to be a macro interval, or default `interval_seconds` to a macro value), or log an explicit one-time warning when `interval_seconds == MICRO_SEC` that micro triggers are disabled.

---

## Verified Correct

These were checked seam-by-seam and are correct as implemented. They are listed because they are the load-bearing parts of the pipeline that the defects above sit on top of — and because a FAIL verdict must be specific about what is *not* wrong.

**1. Delta sign convention is consistent end-to-end (Seam 1 → 3).** `multiplexed_feed.py` classifies an up-tick as buy aggression; `aggregator.py:132-133` computes `bar.delta = buy_volume - sell_volume`; `amt_engine.py:441-449` maps it into `FloatOHLC(delta=bar.delta)`; `cvd.py:111-113` does `self._cvd += candle.delta`; `footprint.py` indexes the ask side at 1 and sets `FootprintLevel.delta = ask - bid`. Positive delta means buy aggression at *every* layer, with no sign flip anywhere. Verified by reading all five sites, not by inference.

**2. The Triple-A machine is genuinely live, not a stub.** `analyzer.py:331` constructs `TripleAMachine()`, `:814` calls `.update()` per bar, and `:1121-1122` propagates `triple_a_phase` / `triple_a_signal` into the result; `dto.py:259` maps them into the DTO; `context_builder.py:584-600` maps them into the context; `gates_edge.py` Phase B path 2 consumes `triple_a_phase == "AGGRESSION"`. The full chain is wired in both directions, and `analyzer.py:380` resets it on session rollover together with the IB tracker, AR engine, LVN tracker, value migration, drive tracker, CVD tracker, VARS detector, and VWAP.

**3. TimesFM is advisory-only and never in the gate path.** `timesfm_advisor.py:169` uses fire-and-forget `on_context`; `runtime.py:606-610` defaults the advisor to `None`; `multi_engine.py:274` gates it behind `advisor_enabled: False` with the comment "the Fabio AMT strategy is fully deterministic; the LLM advisor is advisory-only … and must not participate in trading decisions." No gate, guard, or signal builder imports TimesFM. The TimesFM historical pre-seed (`multi_engine.py:1912-1928`) is best-effort with a bare `except Exception: pass`, which is correct for a non-authoritative warm path.

**4. There is exactly one stop-loss implementation.** `structural_stop` is defined once and shared by `signal_builder.py:9` and `position_manager.py:15,612`. No duplicated stop computation, no divergent stop between entry and management.

**5. Quantity is carried, never re-derived.** `broker_mapper.py:29-36` (`to_broker_signal`) places the already-sized quantity in the signal metadata; the OMS reads it rather than recomputing size from a second formula. Sizing authority stays with the risk module.

**6. The UI sees engine state, not a parallel computation.** `backend/app/api/websocket/gameloop.py` is a thin transport over `multi_engine.py:984 snapshot()` / `_compose_view_state` (`:954`), which is built from `EventStore.fold()` plus the engine's own `latest_amt` / `latest_quant_decision`. `AmtUpdated` is emitted in `_on_bar_closed` (`runtime.py:1078-1081`) *before* the decision call, from the same DTO object the decision path uses — the banner and the decision see identical evidence for the same bar. `LiveQuoteCache` (`state.py:234-243`) holds only ltp/oi/depth and the forming candle, and its own docstring correctly disclaims position authority: "positions, risk, portfolio, amt, decisions all come from `EventStore.fold() → project_state()` or the engine's own `latest_*` attributes."

**7. Multi-symbol isolation holds.** One `MultiplexedMarketFeed` (`multi_engine.py:395`), a per-symbol `LiveGateway` dict (`:397`), one `QuantEngine` per symbol on its own bounded thread (`_spawn_engine:1830`, with an explicit pool-ceiling refusal *before* construction at `:1838`), and a **shared** `SessionLevelStore` (`:392`, `:1882`) that is keyed per-symbol at the API boundary. `tests/quant/coordinator/test_multi_symbol_isolation.py` → 9 passed. Cross-symbol state leakage was specifically hunted (shared mutable defaults, shared accumulators) and not found: `AMTAnalyzer` is per-engine (`amt_engine.py:154`), the footprint accumulator is per-engine (`:156`), and each engine has its own aggregators.

**8. Leg-LVN resolution has exactly one producer spelling.** `quant/amt/profile/leg_lvn.py` resolves from the DTO's `legLvns` list only, and its docstring explicitly records that the singular `legLvn` fallback was dead and removed. This is the correct fix for the exact class of defect D-E1/D-E2 represent, and it is already applied here — the same treatment is needed for the four context fields.

---

## Suspicious / Needs Human Eyes

1. **`gate_edge.py` vs `gates_edge.py`.** `quant/decision/gates/gate_edge.py` is a three-line re-export shim: `gate_edge = gate_triple_a_edge`, with a docstring asserting the canonical implementation lives in `gates_edge.py`. That is a deliberate indirection, not an accident, but it means the spec's file pointer (`fabio_decision_pipeline.md:85`: "`quant/decision/gates/gate_edge.py` → `gate_triple_a_edge(ctx)`") names the shim while the code lives next door. Confirm no caller imports the shim *and* the canonical module and gets two objects; and confirm the shim still has a reason to exist (it currently adds a name and no behavior).

2. **`QuantEngine._on_bar_closed` exits before deciding when a position is open.** At `runtime.py:1083-1090`, if `state.position is not None` the engine calls `_manage_exit` and returns — `_decide` is never reached for that bar. That is intended (no pyramiding on the macro bar), but combined with D-E7's hard-disabled live pyramiding and D-E9's inert micro aggregator at the default interval, it means the *only* live entry path at default config is the flat-position macro-bar branch. Worth confirming that is the intended live trading posture and not an over-restriction.

3. **`TickHandler` has two parallel decision call shapes.** `_process_futures_tick` (`tick_handler.py:235-241`) decides on the micro bar with `self._amt_engine.last_amt_dto`; `_process_option_tick` (`:144-155`) decides with a cached `self._underlying_amt_dto` and `self._last_underlying_bar`. Both are correct for their topology, but the two paths cache DTOs differently (`last_amt_dto` property vs. an instance slot set by `_underlying_amt_dto_setter`). A future change to one cache invalidation strategy will not apply to the other. Unify or document.

4. **The `LiveQuoteCache` forming candle is the only tick-granularity UI state.** It is correct for the stated purpose, but the same object is the natural place a future feature would reach for "current price" inside a decision — and its docstring explicitly says it is not a position authority. Worth adding a comment at the single read site that this must never feed a gate, since the fold is authoritative.

5. **`_DEFAULT_CONFIG["interval_seconds"] = 60` and D-E9.** Either 60s is the intended live macro interval (in which case the micro trigger is disabled by default and D-E9 stands as written), or 60s is a test convenience that leaked into the production default (in which case the intended live value is 300s and the default should be changed). The comment at `runtime.py:385` implies the design expects a macro interval larger than 60; the default does not provide one. A human must decide which is true — the code cannot say.

---

*All file:line citations refer to the working tree at branch `architecture/design-level-refactoring`, 2026-09-21. Tests run to confirm the audited modules and the isolation contract: `tests/quant/coordinator/test_multi_symbol_isolation.py` → 9 passed; `tests/quant/decision/` → 384 passed. All findings were verified by executing probes against the live modules (field membership on constructed `DecisionContext`, AST-level field-coverage diff of `context_builder.build()`, regex/`hasattr` checks for the unassigned attributes, and direct inspection of both `AMTEngine.analyze` call sites), not by inspection alone.*
