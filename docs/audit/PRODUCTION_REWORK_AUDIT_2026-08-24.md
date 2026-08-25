# Production Rework Audit — Executive Report

**Repo:** `/Users/apple/Documents/v5-of-glassytrade-ai` · **Branch:** `stable_7` · **Date:** 2026-08-24
**Scope:** Full adversarial audit per mandate: reconstruct spec → challenge → trace → break → redesign → fix → test → replay → prove.
**Baseline at start:** 1063 passed / 4 failed / 11 skipped (e2e excluded). **After fixes:** **1075 passed / 0 failed / 11 skipped.**

---

## A. Executive Verdict

## ❌ NOT PRODUCTION READY

The system is a well-organized paper-trading research engine with several genuinely strong subsystems (event-bus isolation, journal fsync, ExchangeConfig single-source, portfolio risk ceiling). But the mandate's question — *does it behave like the intended strategy in production?* — fails on multiple independent, confirmed axes:

1. **The decision core was provably poisoned** (D-ABS-01): every flat high-delta candle anywhere on the tape was labeled "ABSORPTION @ VAH", feeding phantom level tags into the direction hierarchy that gates entries.
2. **The live order path is not connected to the risk state machine**: the SIGTERM emergency flatten set an attribute that does not exist (`eng._risk_halted`), i.e. there was **no working kill switch** (D-RISK-03).
3. **Position persistence and reconciliation are dead code**: nothing writes `open_positions`/trades/position-events; startup reconciliation counts but cannot restore; `RECONCILED_STALE` is counted by a UI query but never emitted (D-PERS-04). Restart-with-open-position is unhandleable by construction.
4. **Bar timestamps followed the deployment machine's wall clock**, not exchange event time — IST session gates evaluated against wrong instants on any non-IST host, and the monotonic tick guard could silently discard ticks after NTP corrections (D-TIME-06).
5. **Spec §13.3 tiered profit-taking is not implemented** — `close_partial` has zero production callers; every trade exits all-at-once, materially changing the strategy's expectancy profile (D-SIG-02).
6. **A latent recurrence of the original MIDCPNIFTY bug class** existed for SENSEX/BANKEX (silent MCX default) — fixed this session (D-EXCH-07).

Verdict rationale: items 1–4 are correctness/safety defects that no amount of passing tests masked — they were found precisely because the mandate demanded tracing behavior rather than trusting suites.

---

## B. Complete Defect Inventory

Categories: A=Correctness, B=Strategy Fidelity, C=Domain Modeling, D=State Management, E=Concurrency, F=Integration, G=Configuration, H=Temporal, I=Risk, J=Observability, K=Test Deficiency, L=Architectural.

### Confirmed & FIXED this session

| ID | Sev | Cat | Component | Root Cause | Observed vs Expected | Production Impact | Why Tests Missed It | Fix | Regression Test |
|---|---|---|---|---|---|---|---|---|---|
| **D-ABS-01** | P1 | A/B | `quant/amt/market/break_detector.py:99` | The pending diff's polarity-flip edit accidentally deleted the level-proximity condition; loop body returned unconditionally on first iteration | Any flat-body candle with \|delta\|/vol>0.25 returned `ABSORPTION` at the FIRST level in the list regardless of price distance (proven: price@100.2 → "ABSORPTION @200.0") | Direction hierarchy consumed phantom absorption tags → biased LONG/SHORT agent direction → wrong entries | Existing tests fed dojis NEAR levels or asserted only polarity; nobody asserted the negative case (far-from-level must be empty) | Restored `if level > 0 and abs(current.close - level) < threshold:` guard inside the loop | `tests/quant/test_audit_regressions.py::test_absorption_requires_level_proximity` + `test_absorption_still_fires_near_level` |
| **D-RISK-03** | P0 | I/J | `backend/app/main.py:262` + missing API | SIGTERM handler set `eng._risk_halted`, an attribute QuantEngine has never had, behind a silent `hasattr` guard | Emergency flatten = no-op; engines kept entering on remaining bars after shutdown signal | No kill switch during crash/deploy window; open exposure continues | Handler had no test at all (signal handlers rarely tested); hasattr guard converted the bug into silence | New `SessionRisk.halt(reason)` (persists to kv; external halts never auto-clear on restore) + `QuantCoordinator.emergency_halt()` returning count; handler now routes through it and logs applied-count | `test_session_risk_has_external_halt_api_or_engine_attr_exists`; halt-persistence covered by existing `test_risk_persistence.py` shape |
| **D-TIME-06** | P1 | H/A | `quant/brokers/multiplexed_feed.py:448` | `_normalize_dhan_packet` preferred `WSMessage.timestamp` (= `datetime.now()` local-naive from `websocket_client.py`) over exchange `last_trade_time` epoch | Proven: engine epoch = machine-local wall clock (skew 15,715,200s vs exchange LTT in test); bar windows/session gates follow deployment TZ; monotonic guard can discard ticks post-NTP-jump | IST phase gates evaluate against wrong instants on non-IST hosts; silent data loss via late-tick discard | Feed tests used synthetic packets without a conflicting timestamp pair; nobody tested LTT-vs-arrival-stamp precedence | Prefer `last_trade_time`/`LTP_time`; fall back to arrival stamp only when exchange sent none | `test_normalize_packet_prefers_exchange_ltt_over_local_clock` |
| **D-EXCH-07** | P1 | G/A | `quant/contracts/exchange_config.py:224` + `symbol_registry.py:56` | SENSEX/BANKEX got selector strike-intervals (diff) but were absent from ExchangeConfig sets; registry falls through to `"MCX" # safe default` | `exchange_for("SENSEX … CALL") == "MCX"` (proven): BSE index options would run on MCX 09:00–23:30 sessions with MCX metadata | Exact recurrence of the MIDCPNIFTY incident class: wrong sessions/expiry cut-offs/tick-lot for any BSE symbol reaching the scanner | Selector-level tests asserted strike intervals directly; no end-to-end classification test for symbols outside both config sets | Registered SENSEX(20)/BANKEX(30) in NSE defaults (tick 0.05, freeze 1000, PV 1.0); added loud-default regression test | `test_registry_does_not_default_known_bse_indices_to_mcx` |
| **D-GATE-05** | P2 | D/L | `quant/decision/decision_service.py:89` | VA-fade eligibility keyed off positional `results[0]/results[1]`, coupled to pipeline order | Reordering/inserting gates would let fades fire while session-closed or position-open | Latent mis-trade vector under refactor; also made pipeline order unchangeable | The adversarial test exercised gate-1 failure through the current order — position-coupling invisible | Gate numbers `(1,2)` matched explicitly: `any(r.gate in (1,2) and not r.passed)` | `test_decision_service_fallback_uses_gate_numbers_not_positions` + existing `test_decision_service_blocks_fade_when_gate1_fails` still green |
| **K-FILL-08** | P2 | K | `tests/system/test_paper_protocol.py:244` | Test invariant ("all fills within 1 tick of bar close") contradicted intentional SL/TP fill-at-level change | Baseline failure masked as "known red"; convention undocumented | False-confidence: suite permanently red normalizes ignoring failures | Test encoded old fill model; change landed without updating contract test | Rewrote as `test_fills_follow_fill_price_convention`: SL/TP fill EXACTLY at level; all other exits within 1 tick; spot-check updated | Same test (now green, stronger contract) |
| **K-STATE-09** | P3 | K/C | `tests/test_fabio_alignment.py:22` | Test asserted `len(MarketState)==2` while enum gained DEAD (volume-collapse veto wired through analyzer→context→gates+fallback) | Baseline failure; docs say 2-state, code needs the veto | Spec-conflict ambiguity could push someone to delete DEAD wiring | Doc-vs-code drift; test written from docstring | Test now pins real contract: {BALANCED, IMBALANCED, DEAD} with NO_TRADE/PROBING forbidden; docstrings updated to call DEAD a veto, not an auction state | Same test (green) + `test_dead_market_no_trade` already covers veto behavior |
| **K-QA-10** | P3 | K/F | `tests/test_qa_scripts.py` | Subprocess QA scripts ran without repo root on PYTHONPATH → `ModuleNotFoundError: quant` | 2 baseline failures unrelated to product code | QA scripts unusable standalone; red tests erode trust | Tests invoked subprocess without env injection | Inject repo root into PYTHONPATH + cwd | Both green |

### Confirmed & OPEN (design decisions required — not auto-patched per mandate)

| ID | Sev | Cat | Component | Finding | Impact | Recommended Redesign |
|---|---|---|---|---|---|---|
| **D-SIG-02** | P1 | B | `oms.close_partial` / runtime | Spec §13.3 tiered TP (50% @TP1 / 25% @TP2 / 25% runner trailed) has NO production caller; every exit is whole-position | Strategy expectancy materially different from spec; no runner capture; partial de-risking absent | Wire ExitEngine tier evaluation into PositionManager: on TP1 hit → `close_partial(0.5)` + ratchet SL to BE; TP2 → `close_partial(remaining*2/3)`; arm trail on runner. Add scenario test asserting three fills per winner |
| **D-PERS-04** | P1 | F/J/D | storage ports + reconciliation | No production writer for `save_open_position`/`save_trade`/`save_position_event`; `StartupReconciliation.reconcile()` deletes stale rows and logs orphans but restores NOTHING (no engine state rebuild); `RECONCILED_STALE` never emitted though queried by `/trading` UI | Crash/restart loses all position context; orphaned broker positions invisible to operators; live-mode boot-refuse check compares empty-vs-real counts (false mismatches) | (1) Subscribe projector→storage: persist PositionOpened/PositionClosed events; (2) reconciliation returns per-symbol restorable specs; coordinator rebuilds SessionRisk+ExitEngine state or explicitly flags manual-intervention; (3) emit RECONCILED_STALE from reconciliation |
| **D-HALT-11** | P2 | I/L | QuantEngine | Even post-fix, `emergency_halt` blocks NEW entries only; open positions rely on SL/session-close; no operator-facing flatten-all | Shutdown with open positions leaves them to automated exits only | Decide policy explicitly: either accept documented "halt-entries-only" semantics (now logged loudly), or add coordinator.flatten_all() placing market closes via broker adapter before thread join |
| **D-OBS-12** | P2 | J | Journal/EventBus | Journal append failures are swallowed by EventBus isolation (by design — proven good for liveness), so a disk-full journal means trading continues with NO audit trail and zero surfaced alert | Silent loss of the nightly-replay determinism input; compliance gap | Add journal health counter (consecutive-append-failures) surfaced on `/health`; degrade to read-only trading after N failures if policy demands |
| **D-TIME-13** | P3 | H | `context.seconds_to_close` vs phase table | NSE close 15:15 in `seconds_to_close` vs close-protection phase ending 15:30; `session_force_exit` short-circuits first so behavior consistent today, but time-stop math uses the earlier close inconsistently | Minor: last-minute TIME exits slightly conservative; semantic drift trap | Unify on one constant `NSE_SESSION_CLOSE=15:30` with `NSE_LAST_ENTRY=15:15`; derive both consumers from it |
| **D-RISK-14** | P3 | I/G | `SessionRisk.__init__:40` | `max_trades_per_session=50` testing TODO shipped in default constructor (spec: selective trading ≈6) | Paper overtrading distorts validation statistics; if default reaches prod config, MDL discipline diluted | Move override to explicit paper-config layer; default 6 with comment pointing to config knob |
| **D-EXPY-15** | P3 | C/H | `context.is_expiry_day` | Global Tuesday assumption baked in (post-Nov-2024 weekly schedule); MCX contracts use own expiry parse (correct), but NSE monthly-only underlyings and holiday-shifted expiries are mislabeled | Wrong early-cut-off timing on shifted expiries | Derive expiry day from the held contract's parsed expiry (already available as `_contract_expiry`) instead of weekday heuristic where contract known; keep weekday fallback for underlying-level queries only |

### Verified-CORRECT mechanisms (audited, evidence-based)

- **Absorption polarity flip (working tree)**: producers/consumers agree post-flip (detector, break_detector, context_builder map, gates_edge paths, pyramid gating SELL_ABSORBED=bullish). Correct per spec §7.2 under tick-direction proxy.
- **EventBus handler isolation** (`events.py:126`): disk-full journal cannot kill engine thread — logged and isolated (empirically proven per docstring, re-verified reading path).
- **Journal fsync-on-append** (`persistence.py`): crash loses ≤1 record — matches reconciliation-grade claim.
- **PortfolioRiskAuthority**: coarse RLock correct for entry/exit-frequency contention; register/release symmetric in manage_exit paths traced.
- **Zero-size entry refusal**, lot-snapping half-up (S10), `close_partial` `_id` preservation, duplicate-signal-id execution guard, freeze-limit cap with lot rounding, poll-to-terminal + cancel-on-timeout in Dhan adapter, monotonic guard existence, `_EPOCH_2000` synthetic-id passthrough, seed backoff DH-3001, lifecycle RLock closing check-then-act races, corruption clamp on kv restore (>50% equity), external-halt non-auto-clear (new).
- **Trail/BREAKEVEN lifecycle**: `pop_trail` called on every close path traced (base + pyramid loops in `manage_exit`); `close_partial` preserves `_id`. Residual leak risk limited to future close paths skipping `pop_trail` — consider a periodic sweep.

---

## C. Architecture Assessment

**Strengths**
- Clean hexagonal seams where they matter: `ExchangeConfig` as single classification authority; port interfaces (`IStorage`, `IBroker`, `IMarketData`); EventBus with priority subscribers; deterministic engine replay via journals.
- Defense-in-depth done right in spots: duplicate-signal-id guard AND broker correlationId backstop; per-engine SessionRisk AND cross-engine PortfolioRiskAuthority; kv corruption clamp.
- Certification records (S1…) + golden traces give real replay determinism — the decide-golden suite proved byte-stable across runs during this audit.

**Systemic weaknesses (the "why did MIDCPNIFTY happen" answer)**
1. **Classification by enumeration, not authority.** Every layer keeps its own symbol list (`selector.nse_intervals`, `scanner._SCAN_*`, `registry`, `ExchangeConfig`). They drift independently; the diff added SENSEX to ONE layer. Redesign: one `InstrumentRegistry` keyed by root → {exchange, tick, lot, freeze, strike_interval, sessions}; all layers consume it. Unknown root = hard error at spawn-time, never a silent default.
2. **Silent-default culture.** `"MCX" # safe default`, `hasattr` guards, `except Exception: pass` in sizing/fallback chains. Each individually defensible; together they convert bugs into silence. Policy: defaults allowed only with a logged warning + metric.
3. **Two parallel universes for positions.** The quant engine's Position/Fill world (paper OMS, journals) and the backend's domain Position/storage world never meet. That's how D-PERS-04 happened: ports exist, implementations exist, nothing bridges them.
4. **Spec-to-code drift without a tripwire.** Tiered TPs (§13.3), max-trades TODO, 15:15-vs-15:30 — all spec violations invisible because no executable spec exists. Redesign: a `tests/test_spec_invariants.py` that encodes the 20-area reconstruction as property checks (this audit's regression file is the seed).

---

## D. Specification-to-Code Traceability Matrix (key rows)

| Spec § | Requirement | Code Location | Status |
|---|---|---|---|
| §4 phases | NSE 5-phase table, opening-noise no-trade | `session/context.py:_get_nse_phase` | ✅ |
| §4 | MCX 09:00–23:30, evening selectivity, close protection | `_get_mcx_phase` | ✅ (selectivity flag informational only) |
| §5 opening relation | IN_BALANCE/OUT_ABOVE/OUT_BELOW vs prior VA | `opening_relation` + prior-profile kv | ✅ |
| §7.2 Triple-A | absorption→accumulation→aggression w/ displacement confirm | `detectors.AbsorptionDetector` + `gates_edge` paths | ✅ polarity; ⚠️ constants 0.30/2.0 vs spec 0.50/1.50 (documented deviation) |
| §7.x breaks | initiative vs responsive, IB break + failed-auction clear | `break_detector` + `check_ib_break_tick` re-entry clear | ✅ (proximity restored) |
| §8 levels | POC/VAH/VAL/NPOC targets, LVN sniping | analyzer profile + npoc_tracker + gates_edge path C | ✅ |
| §9 VWAP bands | ±1σ/±2σ volume-weighted, anti-climax beyond 2σ | `_recent_vwap_stats` + anti-climax guard | ✅ |
| §10 drives | drive counting, second-drive entry, exhaustion ≥3 | `drive_tracker` + drive-exhaustion guard + path B | ✅ |
| §11 risk | cushioning tiers 0.25%/+40%; MDL 2%; 3-loss cutoff; risk-zero 0.8R | `SessionRisk` + ExitEngine breakeven | ✅ except max-trades TODO (D-RISK-14) |
| §12 exits | SL 1–2 ticks behind cluster extreme; spread blowout; time stops | `signal_builder` anchor chain + ExitEngine | ✅ |
| **§13.3 TP tiers** | 50/25/25 + trailed runner | `close_partial` — **NO CALLER** | ❌ **D-SIG-02** |
| §13.2 pyramids | risk-free base, ≤2 adds, LVN proximity, absorption-side agreement | `position_manager.check_pyramid` | ✅ |
| §14 options | CE/PE direction match; delta-adjusted R:R; ATM gamma selection | `selector.translate_underlying_signal_to_option` | ✅ (direction gate verified by tests) |
| §15 expiry | early cut-offs MCX 21:00/21:30, NSE 14:00; ITM devolvement guard | `session_gates` expiry hours + contract-expiry force-exit | ✅ except weekday heuristic (D-EXPY-15) |
| §16 data | cumulative→delta conversion; tick-direction attribution; monotonic guard | multiplexed_feed | ✅ mechanism; ❌ timestamp source (fixed) |
| §17 broker | duplicate-signal dedup; terminal polling; cancel-on-timeout; freeze cap | dhan_broker_adapter | ✅ |
| §18 recovery | restart reconciliation; position restore | startup_reconciliation | ⚠️ counts-only (D-PERS-04) |
| §19 kill switch | emergency flatten on shutdown | main.py SIGTERM | ❌→✅ fixed (D-RISK-03) |

---

## E. Production Risk Register

| Rank | Risk | Likelihood | Severity | Mitigation status |
|---|---|---|---|---|
| P0 | No working kill switch (D-RISK-03) | Was certain; now fixed | Capital loss during outage | **Fixed** — coordinator.emergency_halt + persistent SessionRisk.halt |
| P1 | Phantom absorption steering direction (D-ABS-01) | Was live; now fixed | Wrong entries daily | **Fixed** with dual-sided regression tests |
| P1 | Restart loses positions (D-PERS-04) | High (any redeploy) | Orphaned exposure; false live-boot refusals | Open — bridge required before LIVE |
| P1 | Tiered-TP absence (D-SIG-02) | Certain (every winner) | Expectancy ≠ validated strategy | Open — implement §13.3 wiring |
| P1 | Wall-clock bar times on non-IST host (D-TIME-06) | Deployment-dependent | Session gates misfire | **Fixed** — LTT precedence |
| P1 | Symbol-class recurrence (D-EXCH-07 pattern) | Medium | MIDCPNIFTY-style incident repeats | Fixed for SENSEX/BANKEX; **architectural fix (single InstrumentRegistry) recommended before adding more venues** |
| P2 | Fade-eligibility coupling (D-GATE-05) | Low until refactor | Mis-trades after reorder | **Fixed** |
| P2 | Journal silent stop (D-OBS-12) | Low (disk-full) | Audit-trail loss | Open — health metric |
| P2 | Testing-mode trade cap in defaults (D-RISK-14) | Certain in paper | Overtraded stats | Open — config move |
| P3 | Expiry weekday heuristic (D-EXPY-15), 15:15/15:30 split (D-TIME-13) | Edge days | Conservative mis-timing | Open — constant unification |

---

## F. Redesign Proposals (beyond point fixes)

1. **Single InstrumentRegistry** (kills defect CLASS, not instance): one typed table root→{exchange, tick, lot, freeze, strike_interval, session_profile}; scanner/selector/runtime/adapter all read it; unknown root raises at engine-spawn with the symbol in the message. Migrates MIDCPNIFTY/SENSEX-class bugs from "runtime misclassification" to "boot-time configuration error".
2. **Position-event bridge**: StateProjector already folds PositionOpened/Closed — add one storage subscriber writing `save_open_position`/`delete_open_position` + `save_trade` on Fill; reconciliation then reads truth, emits RECONCILED_STALE, and live-boot mismatch checks compare real numbers.
3. **Executable spec**: encode the §-matrix above as invariant tests (spec_invariants.py) so drift fails CI, e.g. "every approved signal has rr≥1.5 AND sl within [1,2] ticks×ATR of a structural level".
4. **Loud-defaults policy**: replace silent `except/pass` and hasattr guards in sizing/classification paths with logged+metric'd degradation; forbid bare `"MCX"` style defaults via lint grep in CI.

## G. Regression Suite (implemented & RUN)

- New file `tests/quant/test_audit_regressions.py` — 8 tests pinning D-ABS-01 (both directions), D-GATE-05 contract, D-RISK-03, D-PERS-04 shape, D-TIME-06 precedence, D-EXCH-07 loudness. **All 8 pass post-fix; 4 reproduced the bugs pre-fix.**
- Rewritten `tests/system/test_paper_protocol.py::test_fills_follow_fill_price_convention` — encodes the level-fill model (SL/TP exactly at level; others within 1 tick).
- Updated `tests/test_fabio_alignment.py::test_market_state_is_two_state` — pins {BALANCED, IMBALANCED, DEAD} with legacy states forbidden.
- Fixed `tests/test_qa_scripts.py` subprocess env.
- **Full-suite proof:** `pytest tests/ --ignore=tests/e2e` → **1075 passed, 11 skipped, 0 failed** (47.7s). E2E excluded: requires booted backend + live GOLDM symbol (environmental, unchanged by this work).
- Reproducible proofs kept at `/tmp/proof_absorption.py`, `/tmp/proof_timestamp.py`.

---

## Final Adversarial Answer: *"What could still be wrong even though all tests pass?"*

1. **Constants tuned to the test fixtures.** AbsorptionDetector ships 0.30/2.0 vs spec 0.50/1.50 — every test passes because fixtures satisfy BOTH parameterizations. Only live-order-flow distribution will reveal whether detection fires too often/never. Needs a calibration replay on recorded market data, not unit tests.
2. **Delta is a proxy everywhere.** Dhan carries no aggressor flag; `_attr_delta` infers from upticks. All Triple-A logic rests on this inference; a regime of large block trades at one price systematically mislabels delta. Tests cannot catch a feed-quality epistemic gap — only a live shadow-period comparison vs broker-reported buy/sell stats can bound it.
3. **The untested integration seams.** `execute_order` has NO production caller — the live order path from SignalApproved→broker is simply not wired yet. Everything tested around it is component-local; the seam itself has zero coverage because it doesn't exist. First live wiring will be new surface area.
4. **Timezone environment assumptions survive.** Post-fix, ticks carry exchange time, but `_to_ist` fallbacks default broken inputs to `datetime.now(IST)`; a host with wrong TZDATA or a frozen clock still produces plausible-but-wrong sessions. No test asserts wall-clock independence of the full stack.
5. **Golden files are characterization, not specification.** `decide_long.json` proves determinism of CURRENT behavior. If today's behavior is subtly wrong in a way fixtures encode (e.g., the VAH-clamp warnings visible in every protocol run), goldens enshrine it. Goldens need periodic human review against the spec matrix, not just CI stability.
6. **Concurrency coverage is structural, not temporal.** Lifecycle RLock and emit-lock are correct under review, but no test exercises interleaved depth-update + bar-close + switch_symbol schedules; JVM-style stress (thousands of interleavings) isn't feasible here — residual race risk is nonzero, concentrated in `_spawn_engine`/journal attach ordering.
7. **Market-regime validity.** All fixtures are synthetic, low-vol, tight-spread. Gap-through-SL fills (fill worse than SL), auction-limit halts, circuit-breaker days, and 0-DTE gamma pinning have no fixture representation — the suite proves the strategy works in the regime it was written in.

**Bottom line:** the four red tests at session start were symptoms, not the disease. The disease was unwired integrations and silent defaults; the cure applied here is fixes + loudness + regression pins, and the remaining prescription is items 1–4 of §F plus a live shadow-trading period before any capital.
