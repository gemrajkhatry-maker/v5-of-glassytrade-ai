# AMT Implementation Plan — Validated Findings → Prioritized Repairs

Date: 2026-09-22 · Branch: `architecture/design-level-refactoring` @ `72a4fff2` + working tree
(Waves 0–8 of `amt_fidelity_repair` uncommitted).

Inputs: `docs/reviews/amt-fidelity-audit-20260922.md` (R3),
`docs/reviews/amt-math-debt-20260922.md`, playbook `docs/amt/*.md`, graphify map
(`graphify-out/`). Method: read-only tracing of every audit claim against the current tree,
two live reproductions (OpportunityAuction starvation, DecisionLoop translation), and one
targeted suite run this pass:
`pytest tests/quant/decision tests/quant/test_session_gates.py tests/quant/test_decision_loop.py tests/quant/execution/test_exits.py tests/quant/execution/test_sizing_invariants.py tests/quant/amt/profile`
→ **653 passed / 2 failed** — the stale session-gates pair, disposition **P0-2**. Findings
beyond the audits: NEW-P0-1, NEW-P0-2; §8.1 corrected to CONFIRMED; the 15 math-debt §1.7
rows re-adjudicated in §3. Citations re-located against this tree (several files were edited
after the cites were first written). **No production code was modified by this pass; this
document is the only artifact.**

Verdict legend:
**CONFIRMED** = defect still live · **REPAIRED** = defect fixed in current tree (audit was
written against the pre-wave tree) · **PARTIAL** = fixed in core, residual remains ·
**CARRY** = tracked by math-debt, not independently re-verified here ·
**REFUTED** = the claim is false as written — code or docs contradict it.

---

## 0. HEADLINE — new P0 found during validation (not in either audit)

**NEW-P0-1 · `OpportunityAuction.propose()` never settles for a single proposing engine —
every entry is starved.**
`quant/execution/opportunity_auction.py:propose()` overwrites `self._pending[symbol]` with a **fresh** proposal each call, so `oldest = min(created_at)` is always the caller's own timestamp and `(now - oldest) < hold_sec (0.25s)` always holds → `(False, "auction hold — competing opportunities")` forever; `_expire()` purges any aged entry first, so a pending entry can never age past the hold. `SubmissionHandler` builds a new `OpportunityProposal` per bar and calls `propose()` once — no retry (`submission_handler.py:334-343`) — so the denial latches as `SignalBlocked`. The coordinator wires the auction into **every** engine (`multi_engine.py:465/:2098`, `runtime.py:874`, `decision_loop.py:172` → `submission_handler.py:326`): coordinator-mode entries are starved.
LIVE REPRO (real classes, in-process):
```
attempt1: (False, 'auction hold — competing opportunities')
attempt2: (False, 'auction hold — competing opportunities')   # 0.30s later, same symbol
attempt3: (False, 'auction hold — competing opportunities')
open_risk after: 0.0                                          # register_open never called
```
This is the money-path blocker of the current tree, superseding audit P0-1 (which is fixed).
Plan item **P0-1** below.

**NEW-P0-2 · On translated option engines every approved entry is blocked as
OPPOSING_TYPE — `ctx.option_delta` is always `None` on the faithful path.**
(**e2e-CONFIRMED at the DecisionLoop surface — rerunnable repro below**)
`DecisionLoop._build_context` evaluates on the *underlying* symbol whenever an underlying
gateway is wired (`decision_loop.py:445-449`; dep supplied at `runtime.py:884/938` —
`self._underlying` whenever `underlying_gateway is not None`).
`DecisionContextBuilder.build` then sets `option_delta = DEFAULT_OPTION_DELTA if
is_option_contract(symbol) else None` (`context_builder.py:643-645`) — the underlying is not
an option, so `ctx.option_delta is None`. `_translate_signal_for_option` passes that `None`
into `OptionSelector.translate_underlying_signal_to_option` (`decision_loop.py:491-507`),
whose delta-validation gate rejects `delta=None` first (reproduced below: `[OPTION
TRANSLATE] … explicit option Greek delta is required` → returns `None`), so the decision is
replaced with a blocked **OPPOSING_TYPE** ("Signal direction opposes option contract type")
— a missing delta mislabelled as a direction conflict. Existing tests inject `option_delta` directly (`test_option_signal_translation.py:20,42,62,71`) or never translate (`test_decision_loop.py:207/:246`) — the seam is untested; NEW-P0-1 fixed or not, this starves the faithful path. Plan item **P0-3**.

**E2E REPRO (run from repo root, stdin only — no file committed):**
`PYTHONPATH=. .venv/bin/python - <<'EOF' … EOF`

```python
import dataclasses, importlib.util, sys

spec = importlib.util.spec_from_file_location("tdl", "tests/quant/test_decision_loop.py")
tdl = importlib.util.module_from_spec(spec)
sys.modules["tdl"] = tdl              # dataclass machinery looks the module up by name
spec.loader.exec_module(tdl)

bar = tdl.FakeBar()

def run(gateway, label):
    oms = tdl.FakeOMS()
    strat = tdl.FakeStrategy()
    emitted = []
    loop = tdl.make_decision_loop(strategy=strat, oms=oms,
                                  underlying_gateway=gateway, emit=emitted.append)
    dec = loop.evaluate({}, bar)
    return {
        "label": label,
        "ctx_symbol": strat.last_ctx.symbol if strat.last_ctx else "<no ctx>",
        "ctx_delta": getattr(strat.last_ctx, "option_delta", "<missing>"),
        "approved": dec.approved,
        "reason": dec.reason,
        "block": dec.block_reasons,
        "submitted": len(oms.submitted),
        "emitted": [(type(e).__name__, getattr(getattr(e, "decision", None), "reason", None)) for e in emitted],
    }

A = run(None, "A control: gateway=None")
assert A["approved"] is True and A["submitted"] == 1, A

B = run(object(), "B translated: gateway set, eval=NIFTY, delta unset")
assert B["ctx_symbol"] == "NIFTY" and B["ctx_delta"] is None, B
assert B["approved"] is False and B["reason"] == "OPPOSING_TYPE" and B["submitted"] == 0, B
assert any("opposes option contract" in b for b in B["block"]), B["block"]

# C — counterfactual = the P0-3 fix shape: key delta off the CONTRACT
from quant.decision.context_builder import DecisionContextBuilder
_orig = DecisionContextBuilder.build
DecisionContextBuilder.build = lambda self, *a, **kw: dataclasses.replace(
    _orig(self, *a, **kw), option_delta=0.5)

C = run(object(), "C translated + forced option_delta=0.5")
assert C["approved"] is True and C["submitted"] == 1, C

for r in (A, B, C):
    print(r)
```

**Observed outcome (2026-09-22, exit 0, all asserts passed):**
```
{'label': 'A control: gateway=None', 'ctx_symbol': 'NIFTY24JAN100CE', 'ctx_delta': 0.5, 'approved': True, 'reason': 'Triple-A', 'block': (), 'submitted': 1, 'emitted': [('DecisionProduced', 'Triple-A'), ('SignalApproved', None), ('PositionOpened', None)]}
{'label': 'B translated: gateway set, eval=NIFTY, delta unset', 'ctx_symbol': 'NIFTY', 'ctx_delta': None, 'approved': False, 'reason': 'OPPOSING_TYPE', 'block': ('Signal direction opposes option contract type (Call vs Put)',), 'submitted': 0, 'emitted': [('DecisionProduced', 'OPPOSING_TYPE')]}
{'label': 'C translated + forced option_delta=0.5', 'ctx_symbol': 'NIFTY', 'ctx_delta': 0.5, 'approved': True, 'reason': 'Triple-A', 'block': (), 'submitted': 1, 'emitted': [('DecisionProduced', 'Triple-A'), ('SignalApproved', None), ('PositionOpened', None)]}
stderr: [OPTION TRANSLATE] NIFTY24JAN100CE: explicit option Greek delta is required
```

Interpretation: A — control works (delta=0.5 flows; signal reaches `oms.submit` →
`PositionOpened`). B — production wiring (`runtime.py:884` dep, eval on underlying):
identical input, zero submits, blocked OPPOSING_TYPE. C — P0-3 fix shape restores
`PositionOpened`: **delta=None is the sole blocker, and the fix passes e2e.**

---

## 1. Stage-by-stage pipeline trace (where each step actually lives)

| # | Stage | Primary code (class → function) | Notes |
|---|-------|--------------------------------|-------|
| 1 | Market data | `quant/brokers/multiplexed_feed.MultiplexedMarketFeed` (`_route` → `_convert` → `_normalize_dhan_packet`, `_cum_to_delta`, `_attr_delta`, `_route_depth`) → `quant/brokers/live_gateway.LiveGateway` → `quant/engine/tick_handler.TickHandler` | bounded per-symbol queues, drop-oldest; baseline committed post-validation; depth cache cleared when `stream_depth` dies |
| 2 | Bar build + AMT analysis | `quant/amt_engine.AMTEngine` (`seed`, `analyze`, `persist_session_levels`) → `quant/amt/analyzer.AMTAnalyzer.analyze` → `_build_result` / `_compute_evidence_provenance` | session-scoped `_warm_bars`; VA clamp + recent-window VWAP bands; provenance grades per evidence family |
| 3 | Stock/contract selection | `quant/amt/session/scanner.OptionScannerService` (`scan_top_n`, `_process_contract`, `_detect_momentum`, `_score_contract`) + `quant/amt/session/selector.OptionSelector` (`select_strike`, `translate_underlying_signal_to_option`) + `quant/multi_engine.QuantCoordinator` (`check_and_rotate_dead_symbols`, `_scan`) | premium band 20–800 NSE at scan only; direction filter native+stamped only |
| 4 | Entry decision | `quant/engine/decision_loop.DecisionLoop` (`_build_context`, `_translate_signal_for_option`) → `quant/decision/context_builder.DecisionContextBuilder.build` → `quant/strategies/amt_scalping` → `DecisionService.evaluate` → `GatePipeline` (Gates 1–4) → `SignalBuilder.build_or_reason` → `va_fade.detect_va_fade` fallback | data-quality gate lives ONLY in DecisionLoop (live allows TICK_EXACT or PRICE_DIRECTION_PROXY) |
| 5 | Position sizing | `quant/execution/risk.SessionRisk.position_size` (single sizing authority; House-Money tiers `_risk_per_trade_pct`/`_cushion_tier`) + `quant/engine/submission_handler.SubmissionHandler.submit` (`_apply_risk_ceilings`) | base 0.25–0.50% + 0.40×cushion capped at 30% of profit; Mon/Fri ×0.5 with 1-lot floor |
| 6 | Portfolio risk | `quant/execution/portfolio_risk.PortfolioRiskAuthority` (`can_accept`, `register_open`, `record_close`) + **new** `quant/execution/opportunity_auction.OpportunityAuction` (`propose`, `score_opportunity`) | 2% portfolio MDL, 25% open-risk, 50% hard notional, max-concurrent, one-active-per-root — **auction currently starves all entries (NEW-P0-1)** |
| 7 | Pyramiding | `quant/position_manager.PositionManager.check_pyramid` (risk-free gate, LVN retest, floor-to-lot) → `PaperOMS.add_pyramid` / `LiveOMS.add_pyramid` + base-SL ratchet (`StopMoved PYRAMID_RATCHET`) | sub-lot add-ons skip, never upsize |
| 8 | Stop/TP | `quant/decision/stops.structural_anchor/structural_stop` (single source shared by Gate4 + SignalBuilder + pyramids) → `quant/execution/exits.ExitEngine` (`evaluate`, `resolve_protective_stop`, `_breakeven/_trail/_tp_tier`, `restore_stop_state`) + `exit_checks.*` | cluster-first anchors, no synthetic anchor, BE/trail on actual fill; TimesFM no longer writes stop state |
| 9 | Exits | bar path `PositionManager.manage_exit` → `ExitEngine.evaluate` → `close_partial`/`_execute_full_close`; tick path `manage_tick_exit`/`_tick_tp_touch`; coordinator backstops `multi_engine.eod_square_off` + `session_gates.session_force_exit` | tiers committed only after OMS fill (`apply_pending_tp`); double-close guard |
| 10 | Persistence/recovery | `quant/events.py` event types → `quant/transitions.apply_event` fold → `quant/event_store.EventStore` → `quant/persistence_bridge.PositionStorageBridge` (Opened/Reduced/Closed/**StopMoved**) → `session_levels.SessionLevelStore` (dated levels + NPOC + kv) → restart: `multi_engine._spawn_engine` restore loop (fill-ledger reconstruction + quarantine) → `runtime.restore_position` → `ExitEngine.restore_stop_state` | journals `f"{IST-day}_{symbol}.jsonl"` |

---

## 2. Findings inventory — fidelity audit R3, verdict + citation

### P0-1 · analyzer NameError
**REPAIRED.** `quant/amt/analyzer.py:582` defines `recent_window` in scope for `:742/:744`;
the VA-clamp block the audit's edit deleted is restored (`:583-596`, with rationale
comment). Matches math-debt "Wave 0". The empty-DTO/NO_EDGE cascade is therefore dead.

### §1 Inputs / feed
| # | Verdict | Evidence |
|---|---------|----------|
| 1.1 vol_cap deletes volume | **REPAIRED** | `multiplexed_feed._cum_to_delta` docstring: "Deltas are never capped… Silent vol_cap deleted"; no `cap`/`pvol*0.05` anywhere in file (grep) |
| 1.2 baseline committed pre-validation | **REPAIRED** | `_normalize_dhan_packet` only computes `_pending_baseline`; `_convert` commits `self._prev_cum[symbol]` **after** `ltp>0` and monotonic-late checks ("Commit baselines only for packets that survive validation"); exchange LTT preferred (`last_trade_time`/`ltt`); arrival-clock packets skip the monotonic guard (`used_arrival_clock`) so the `stream_poll` fallback (still present, `backend/app/infrastructure/adapters/dhan_adapter.py:470`) can no longer poison LTT comparisons |
| 1.3 depth cache never aged | **REPAIRED (core)** | `stream_depth` death → `self._depth_cache.clear()` (`multiplexed_feed.py:365-372`); `unsubscribe` pops cache. Residual: no timestamp expiry while the stream is alive but stalled (`ts` written, never read) — minor |
| 1.4 TICK_EXACT from symbol | **REPAIRED** | `analyzer._compute_evidence_provenance` stamps `cvd_delta = PRICE_DIRECTION_PROXY` (comment: "Never stamp TICK_EXACT from instrument class"); `DecisionLoop` live set `{TICK_EXACT, PRICE_DIRECTION_PROXY}` blocks candle/UNAVAILABLE grades (`decision_loop.py:405-430`). Qualified: live now admits proxy grade by design (documented) |
| 1.5 duplicate spawn no guard | **REPAIRED** | `multi_engine._spawn_engine` refuses duplicate under `_lock` + bounded pool ceiling (`:1857-1872`) |
| 1.6 unbounded queues / dequeue-time freshness | **REPAIRED** | `Queue(maxsize=_QUEUE_MAXSIZE)` everywhere + `_put_tick` drop-oldest; `runtime.py:1031` `_last_tick_wall = tick_epoch if tick_epoch > 1e9 else time.time()` (exchange epoch, not dequeue wall clock) |
| 1.7 AMT-math carry table | **Re-adjudicated in §3** — every row carries a code citation; only `1m-on-stale-5m` stays CARRY; LVN + drive-tracker CONFIRMED (math-debt's "addressed" claims refuted) |

### §2 Entry / gates
| # | Verdict | Evidence |
|---|---------|----------|
| 2.1 Gate1 4% / fail-open | **REPAIRED** | `gate_session_phase.py:104-133`: no-book → `passed=False "No bid/ask book…"` (:109-113); spread on the **book mid** (:117-121), not an underlying bar; options `max(10*tick, 1.5%, ₹2.00)` (:124), futures `max(2*tick, 0.1%, ₹0.50)` (:127). Comment (:104) still claims the playbook's ₹0.40 — three-way conflict, see §7.5/§8.1 |
| 2.2 fade skips stop-width cap | **REPAIRED** | `DecisionService.evaluate` fade branch: `fade.sl <= 0` reject, `is_min_stop_met`, then explicit Gate-4-equivalent cap (`cap_ticks` options `entry*0.30/tick`, futures `max(200, entry*0.0075/tick)`); production `DecisionService(min_rr=1.5)` (`runtime.py:306,488`) |
| 2.3 warm-up credited unscoped bars | **REPAIRED** | `AMTEngine.seed`: `_warm_bars = len(ohlcs)` where `ohlcs = session_scope(candles)` ("session-scoped history only so multi-day seed cannot mark warmup complete on session bar 0") |
| 2.4 stop ignores bubble cluster | **REPAIRED** | `stops._anchor_candidates` puts `absorption_cluster_low/high` first (§11.1); `structural_anchor` returns `None` when nothing clears the floor instead of fabricating a 5-tick anchor; Gate4/SignalBuilder both reject `anchor is None` |
| 2.5 LONG stop on entry side | **REPAIRED** | `structural_stop`: LONG `sl = anchor − offset` with `sl >= entry → entry − step` clamp; module docstring explicitly resolves §11.1 (stops behind) vs §11.2 (TP shield inside) |
| 2.6 option translation pre-clamp RR | **REPAIRED (math)** — path blocked downstream, **see NEW-P0-2** | `OptionSelector.translate_underlying_signal_to_option`: rejects `opt_sl <= tick_size`, computes `actual_risk = entry − sl` post-clamp, `rr = opt_reward/actual_risk`, rejects `rr < MIN_RR_RATIO`; invalid delta → reject — but translated engines pass `delta=None` exactly, so this gate currently rejects every faithful-path entry |
| 2.7 hygiene (verified-correct set) | **CONFIRMED healthy** | `pipeline.py:24-36` all 4 gates, exception → failed gate; fade keyed on `r.gate in (1,2)`; full cited keep-list: §10 |

### §3 Exits
| # | Verdict | Evidence |
|---|---------|----------|
| 3.1 tighten exits at 0.0 | **REPAIRED** | `exit_checks.check_stacked_imbalance_tighten` returns `bool`; `ExitEngine` Rule 2b runs **after** the protective stop and arms `self._breakeven[id] = entry` — never `ExitDecision(..., 0.0)` |
| 3.2 tier rounding / ghost position | **REPAIRED (core)** | `PaperOMS.close_partial` floors (`close_lots = int(lots*fraction)`; 1-lot partial ⇒ full close); `manage_exit` only partials when `lots >= 2` and converts `remaining < 0.5 lot` to a full close (no size-0 survivor). Residual notes: exact §13.3 50/25/25 only for ≥4-lot multiples (inherent to integer lots); a 1-lot TP1 touch is a full close that counts as a trade |
| 3.3 BE anchored on signal entry | **REPAIRED** | `ExitEngine.evaluate`: `fill = position.open_price; entry = fill if fill > 0 else signal.entry` ("BE / R / risk-free use the actual fill") |
| 3.4 restart loses ratcheted stops | **REPAIRED** | bridge subscribes `StopMoved` (`persistence_bridge.attach`, `on_stop_moved` persists stop_loss/breakeven/trail/tp_tier); `position_to_row` carries `stop_meta` (`order.py:66-86`); `runtime.restore_position` → `ExitEngine.restore_stop_state` + `entry_time_epoch` fallback parsed from `open_time` |
| 3.5 tier written before fill | **REPAIRED** | `ExitDecision.pending_tp_tier/pending_breakeven` committed by `apply_pending_tp` **after** OMS success (bar path), tick path already set post-fill |
| 3.6 VWAP-drift 150× too wide | **CONFIRMED** | `exits.py:71` default `vwap_adverse_drift_pct=0.03`; trail giveback halved at `> 0.03` (`exit_checks.py:141`), exit at `> 2.0 * 0.03` = 6% of entry (`exit_checks.py:167`); comment `exits.py:81` still claims "1 VA-width" vs Gate-4 risk ≤0.75% |

### §4 Risk / sizing / portfolio
| # | Verdict | Evidence |
|---|---------|----------|
| 4.1 pyramid snap-UP + pre-snap reserve | **REPAIRED** | `lots.snap_to_lot_floor`; `check_pyramid` skips sub-lot ("not upsizing"); `add_pyramid` raises on sub-lot; `add_risk` computed with the **post-floor** `pyramid_size`. `SessionRisk.pyramid_position_size` still has no production caller (dead authority, but policy mirrored by floor+skip) |
| 4.2 30%-profit cap kills trading after a win | **REPAIRED** | `_risk_per_trade_pct` CUSHION_TIER_1: `base 0.0025 + cushion_add` where `cushion_add = min(0.40×pnl/E0, 0.30×pnl/E0)` caps the **add-on only**; MOMENTUM flat 0.40% "no whole-pct profit cap" |
| 4.3 SessionRisk never rolls over | **REPAIRED** | `ensure_session_date()` called from `can_trade()` (`risk.py:300`) and `multi_engine.py:1211` (EOD); rolls date + weekday, per-day storage key |
| 4.4 2% kill vs hard-coded ₹1M; concurrent cap dead | **REPAIRED** | `runtime` passes `starting_equity = portfolio._starting_equity or INITIAL_CAPITAL`; coordinator builds authority with `config starting_equity`, `max_portfolio_daily_loss_pct` default **0.02** (was 0.15), `max_concurrent_positions` from config (`multi_engine.py:455-463`) and **enforces** it (`portfolio_risk.register_open`/`can_accept`); `composition_root.py:271` now forwards `max_concurrent_positions` |
| 4.5 Mon/Fri zeroes 1-lot trades | **REPAIRED (production)** | House-Money branch: `if floored <= 0 and qty > 0: floored = lot_size`. The **aggressive** branch (`base >= 0.05`) still floors to 0 with no min-1-lot — only reachable if a config ships ≥5% risk (see §5 hygiene) |
| 4.6 half-lot scanner blind | **PARTIAL** | Quantity read fixed (`scan_half_lot_rejections.py:97-101`, `fill.position.size` fallback). Still broken: `root_of` at `:39-40` applied to journal names `{IST-day}_{symbol}.jsonl` (`multi_engine.py:2093`, day fmt `:2089`) → `"2026-09-22_NIFTY"` → `KNOWN_LOTS` never hits → GCD fallback; `KNOWN_LOTS["NIFTY"]=75` vs registry `lot=65` (`instrument_registry.py:77`); report emits blind verdicts at `:109` |

### §5 Persistence / fold / journals
| # | Verdict | Evidence |
|---|---------|----------|
| 5.1 phantom fill id quarantines recovery | **REPAIRED** | `close_partial` stamps `_id=position._id` on the fill position ("audit §5.1" comment); restore reconstructs via `load_fills(position_id=…)`, quarantines mismatch, and no longer breaks after the first row (`multi_engine` restore loop: "Restore every open row… no first-row break") |
| 5.2 fold ignores partial PnL | **REPAIRED (fold)** — trace residual **CONFIRMED** | `transitions` `PositionReduced` branch adds `fill.pnl` to `realized_pnl` (base + pyramid). BUT the WS snapshot still computes `equity = balance(≡INITIAL_CAPITAL, `state.py:77`) + sum(closed_trades[-50:]) + open` (`multi_engine._recompute_portfolio_equity:807-820`, window at `transitions.py:274`) → third number after >50 closes; `state.py:78` itself uses `INITIAL + realized(full)` — a third basis coexisting in one payload |
| 5.3 undated kv clobbers dated levels | **REPAIRED** | `runtime.attach_storage`: "Dated SessionLevelStore is the sole prior-levels authority. Do NOT overwrite with undated prior_profile kv (audit §5.3)" — loads dated incl. close into `set_prior_profile` |
| 5.4 levels persist only on next bar | **REPAIRED** | three writers now: cold-start seed (`AMTEngine.seed` persists prev-session levels), rollover writer (`analyze`), and an EOD hook (`multi_engine.py:1207-1213 → AMTEngine.persist_session_levels:582`) + `risk.ensure_session_date()` at EOD |
| 5.5 option NPOC poisons underlying | **REPAIRED** | rollover guard `if not is_option_contract(self.symbol): add_session_poc(...)` ("audit §5.5"); `load_levels` root-prefix match prefers futures. Residual: `save_npoc` first-record-wins per date — acceptable with a single underlying writer |
| 5.6 journal filed under machine-local date | **REPAIRED** | `day = _dt.now(tz=_IST_TZ).strftime("%Y-%m-%d")` (`multi_engine.py:2089`), path `f"{day}_{safe}.jsonl"` (`:2093`); backend `trade_journal` uses `_now_ist()` throughout (no `date.today()`) |

### §6 TimesFM
| # | Verdict | Evidence |
|---|---------|----------|
| 6.1 quantile stop preempts deterministic rules | **REPAIRED** | `exits.evaluate` comment: "TimesFM is advisory only — never write stop state or force exits from forecasts (Wave 6)"; `TimesFMRiskAuthority.evaluate_exit` has **no production caller** (tests only); `ExitEngine` keeps only `session_budget_multiplier`, which is consumed by logging, not sizing |
| 6.2 fallback band sold as native | **REPAIRED** | `build_forecast`: `source = "FALLBACK_BAND"`, `q_spread = band*2` ("honest spread, not 0.0 which lied as certain"); `result_factory.py:74` now `getattr(forecast, "source", …)` |
| 6.3 VELOCITY_DECAY guaranteed on fallback | **REPAIRED** | `timesfm_risk.evaluate_exit`: `if src == "FALLBACK_BAND": pass  # advisory only`; plus no production caller (6.1) |
| 6.4 unstamped forecasts exempt from staleness; unauthorized direction consumer | **PARTIAL** | scanner `_detect_momentum` now requires `src != "FALLBACK_BAND" and asof >= 0` (unstamped/fallback → volume fallback) — direction filter defused; config contradiction fixed (multi_engine + scanner default `false`; `start.sh` ships both off). **Residual:** `runtime._fresh_forecast` (runtime.py:1218-1244) still passes forecasts with `asof < 0` through ("predate freshness tracking"); `TimesFMForecast.asof_bar` defaults to −1 (`timesfm_agents.py:53`); only `timesfm_engine.py:542` ever stamps it — forecasts built by `build_forecast` in multi/scanner paths stay unstamped |
| 6.5 retrieval drops observation identity | **REPAIRED** | `fresh_forecast` calls `getter(symbol, observation_id=bar_index)` with `TypeError` fallback to legacy getters |
| 6.6 `build_forecast(vah=, val=)` unused | **CONFIRMED** | `timesfm_forecast_factory.py:42-43` params still unread by the body; comment `:67` claims "A step-by-step band when vah/val are supplied" — no such path exists |

### §7 Options domain
| # | Verdict | Evidence |
|---|---------|----------|
| 7.1 | = P0-1 → **REPAIRED** |
| 7.2 5-tick fallback emits ≤0 stop | **REPAIRED** | `structural_anchor → None` when no level clears the floor; Gate4 rejects `sl <= 0` ("Stop at/below zero"); SignalBuilder rejects `sl <= 0`/no-anchor; options cap 30% of premium |
| 7.3 Gate4 option cap inverted | **REPAIRED** | `gates_rr`: options `scaled_cap_ticks = max(1.0, (entry*0.30)/tick)`; futures unchanged `max(200, entry*0.0075/tick)`; fake-2R comment removed — "SignalBuilder is the sole R:R qualifier" |
| 7.4 σ message prints rupees as sigmas | **REPAIRED (message)** | `gates_edge._check_guards`: `sigma_mult = abs(close − vwap)/vwap_std`, reason prints true σ-multiples. Structural half (premium-series bands on independent option engines) remains — see 7.7/G9 |
| 7.5 Gate1 admits spreads the exit force-closes | **PARTIAL** | entry fail-closed on the book spread is in (§2.1) but the bases diverge three ways: options `max(10t, 1.5%, ₹2.00)` (`gate_session_phase.py:124`), futures `max(2t, 0.1%, ₹0.50)` (`:127`), comment+playbook ₹0.40 (`:104`, playbook :755-756); exit 3% (`exits.py:69`), expiry 1.5% (`exit_checks.py:19`). The options ₹2.00 floor exceeds the 3% exit for premiums < ₹66.67 (expiry < ₹133.33) → entry admitted, next-bar force-close churn (playbook §15b.5 "same basis" unimplemented) |
| 7.6 expiry year discarded / +1y roll | **PARTIAL** | (a) gate layer fixed: `session_gates.parse_contract_expiry` never rolls — refused past/expired parse → `None` (:112-115) — and accepts a `today=` injection (:60) for deterministic tests; **but 2 tests are still RED** (failure lines and details: G14) → disposition **P0-2**. (b) **qualified:** options already fail *closed* — `_contract_for`'s option branch raises "Missing option contract metadata" when parse+config yield no expiry (`multi_engine.py:1695-1707`, docstring `:1690`) — the `year+1` month-token roll (`:1742`) survives only on the **non-option** path, final fallback `today` (:1747) which arms every expiry-day rule daily. (c) `contract_expiries` read at `:1695/:1711`, never written anywhere (grep) |
| 7.7 options trade their own premium tape | **PARTIAL** | `_spawn_engine` now builds an `underlying_gateway` from the root futures engine when present ("Options: thesis from underlying auction"); translation path (`decision_loop:431`) reachable then. Fallback remains: with no root futures engine the runtime explicitly runs "AMT directly on option premium" (logged as not-faithful). `DEFAULT_OPTION_DELTA=0.5` with comment "No chain-Greek producer exists" (`context_builder.py:643-645`); the scanner computes a per-contract `delta_val` (`scanner.py:111-173`, attached to the scan result) that is never wired to the selector — **and on this path `ctx.option_delta` keys off `eval_symbol`=underlying → always `None` → translate rejects (NEW-P0-2)** |

### §8 Doc conflicts
1. Gate-1 rule — **CONFIRMED** (was wrongly RESOLVED): comment `gate_session_phase.py:104` and playbook :755-756 say `max(2t,0.1%,₹0.40)`, code ships futures `₹0.50` (:127) + options-only `max(10t,1.5%,₹2.00)` (:124), and playbook claims exit shares the basis while exit is 3%/1.5% — details §7.5 → P1-4.
2. Stop side convention — **RESOLVED** (`stops.py` docstring: behind for stops, inside for TP shields).
3. Cushion arithmetic — **PARTIAL** (code implements §12.2 exactly: 0.25%+0.40×cushion capped 0.30×profit ≤0.50%, `risk.py:616-626`; spec §2's "0.35–0.50×Cushion" text stale — so are risk.py's own docstrings `:601-604` "0.35% + 20% of session profit" → G15).
4. E0 basis — **PARTIAL** (sizing equity = configured `starting_equity` + portfolio realized (`risk.py:411-412`) — a third basis; the others are `state.py:74-78` (INITIAL + full realized) and the 50-trade snapshot (§5.2)).
5. Tier percentages — **PARTIAL** (50/25/25 holds modulo integer floors, `oms.py:264-271`; TP2 geometry is still `entry±2R` via `exit_checks.py:54-60 tp2_level`, not playbook §13.3 "Macro Value area extreme" :450).
6. TimesFM advisory-only vs three consumers — **RESOLVED** (code matches `TIMESFM_INTEGRATION.md`; scanner direction use gated).
7. `balance_ratio` 0.55 vs 0.70 — **CONFIRMED**: `base.yaml:62` 0.55; 0.70 at `:152,201,250,298`; 0.55 again at `:355,403,451,499`. Impact is confidence-only — balance_ratio no longer flips market state (`state_engine.py:89` transition = displacement/VA only) — a config/documentation defect, not a state-machine one.
8. ATR range bars — **CARRIED** (declared architectural choice, §16).
9. "spec contains zero options text" — **REFUTED** (playbook now has **§15b Options Domain Policy**).
10. `gate_position_cooldown` docstring over-promises family limit — **CONFIRMED**: module docstring `gate_position_cooldown.py:1-5` and function docstring `:17` claim "maximum 2 concurrent open contracts per root family"; the body (:14-37) checks only cooldown + position_open; real enforcement is `PortfolioRiskAuthority` one-active-per-root via `_active_roots` (`portfolio_risk.py:59`).
11. CVD veto inverted — **REPAIRED** (`gates_edge.py:197`: `-0.5 if MCX else -0.3` = doc table).

### §9 / §10
**§9 carried unchanged** (source: fidelity-audit `:607-608`, not re-litigated): execution-economics figures; code anchors `DEFAULT_OPTION_DELTA = 0.50` (`context_builder.py:36`) and the 0.25% hard-code (`risk.py:614`, partially superseded by strategy configs shipping `0.0025`).

**§10 verified-correct — the canonical keep-list (§6 points here; source: fidelity-audit `:614`):**
- GatePipeline fail-closed → `pipeline.py:24-36`.
- Option buy-only → `signal_builder.py:113-114` ("option scalping is buy-only"); fade and selector carry the same rule (§2 rows).
- Tick-size authority raises → `instrument_registry.py:212-215` (`get_tick_size`, resolve-or-raise).
- Whole-lot entry snap → `lots.py:21` (`snap_to_lot_floor`).
- Halt latching + per-day persistence → `risk.py:167` (restore), `:243` (persist).
- PositionReduced monotonic stop merge → `transitions.py:208`.
- IST window math → `timezones.py:14-47` (IST, `today_ist`, `epoch_to_iso`) + `session_gates.py:21-70`.

---

## 3. math-debt §1.7 verdicts — fully re-adjudicated (every row read in code)

| Item | Verdict here |
|---|---|
| `recent_window` NameError + VA clamp | **REPAIRED** (`analyzer.py:582` def; clamp `:583-596`; consumed `:742/:744`) |
| CVD `state()` advancing on read | **REPAIRED** (`cvd.py:129-135` pure read; mutation only in `update` `:101`; slope-advance gated by `advance_persistence` flag in `_compute_slope` `:147`) |
| LVN cluster keeps weakest trough | **CONFIRMED — math-debt's "addressed (keep_highest=True)" refuted.** Strength is now inverted `1 - vol/mean` (`lvn.py:205`) but the production call is `_cluster_nodes(..., keep_highest=False)` (`:221`) → survivor = min strength = **highest-volume (weakest)** trough; helper docstring `:97-105` now misleading. → P1-6 (test note corrected there) |
| Drive tracker departure-before-re-approach | **CONFIRMED — math-debt's "addressed" refuted.** No departure/price-left-zone check exists anywhere in `quant/amt/orderflow/drive.py` (locus corrects the earlier "analyzer.py" note); `classify_touch` increments `drive_count` on every same-direction touch while price merely stays within `proximity_ticks ≤ 5` (`quant/amt/orderflow/compute.py:258-264`); the ≥180 s decay gate only protects the D1-rejected D2 branch, so three minutes of *residence* next to a level still yields a valid D2. → P2-7 |
| 1m-decision-on-stale-5m-DTO | **CARRY** — not locatable either way (multi-TF wiring at `runtime.py:381-402` + `decision_loop.py:329 interval_seconds`); remains math-debt's row |
| Session-rollover retention | **PARTIAL**: rollover now saves prev levels, guards option NPOC, reloads prior, resets candle ring + incremental profile + `analyzer.reset_session()` (`amt_engine.py:445-474`) — the core retained-state defect is gone; residual: `TickFootprintAccumulator` `_footprint`/`_prev_ltp` are never rolled across the date change (bounded at 200 candles, `footprint.py:181-195`) |
| Cold CVD/IB/session-VWAP after seed | **REPAIRED** (math-debt's still-open row is stale): `warmup_candles` (`analyzer.py:437-446`) feeds CVD/VWAP/IB trackers for every seed bar, called in `AMTEngine.seed` (`amt_engine.py:381`) before `analyze`'s <5-bar early return |
| VA desert under-coverage | **REPAIRED** (`volume_profile.py:141-145` desert guard with audit comment; `test_soft_shell_reaches_value_area_pct` green) |
| balance-ratio OR state flip | **REPAIRED** (`state_engine.py:89` transition = `displacement or not inside_session_va` only; balance_ratio now confidence text `:98/:121/:134`) |
| B-shape forced BALANCED | **REPAIRED / claim obsolete** — no profile-shape→state override exists; `effective_profile_shape` feeds DTO fields only (`analyzer.py:734` → `:931/:1049/:1105/:1312`); `classifier.py` can emit B but nothing consumes it for state |
| Sticky/both-sides acceptance flags | **REPAIRED** (`acceptance_rejection.py:109-117` `active_side` is single-valued above/below/""; flags `:127-136` require the matching side → both-sides impossible; inside-VA close clears both) |
| Forming-footprint overwrite | **REPAIRED** (`footprint.py:134-161` pops/regenerates only the last key for forming/appended bars; completed entries survive) |
| Epoch-vs-ISO candle keys | **REPAIRED** (`footprint.py:191` normalizes `epoch_to_iso(candle_time)`; keys `:142/:164`; `cvd.py:107` likewise) |
| Clamped σ | **REPAIRED** (`vwap.py:148` raw √variance documented, no floor/cap; the ±4σ clamp at `:201-204` clamps the displayed deviation multiple, not σ; `test_vwap_stats` green) |
| Gaussian rounding conservation | **REPAIRED** (`footprint.py:94-131` per-side residual reconciliation: POC absorbs positive remainder, heaviest strips absorb negative) |
| Flat-price incremental profile (+0.5 offset, forced 50/50) | **REPAIRED** (buy-ratio inference `volume_profile.py:277-290`; `test_identical_ltp_conserves_volume_in_one_bucket` green) |
| Duplicate-timestamp CVD | **REPAIRED** (`cvd.py:107-108` same-time → pure `state()` return; backwards time → reset) |

Only `1m-on-stale-5m` stays CARRY; LVN + drive-tracker are CONFIRMED (both math-debt
"addressed" claims refuted); one PARTIAL; the other twelve are REPAIRED.

---

## 4. Playbook divergences the audits did NOT cover (incl. mission focus areas)

**Capital → highest-quality opportunity**
- **G1:** the mechanism built for this very goal (OpportunityAuction) starves all entries — NEW-P0-1, story and repro in §0.
- **G2:** `score_opportunity` is fed only `setup_key` + `rr` from
  `submission_handler._apply_risk_ceilings`; `absorption_vol_ratio`, `spread_quality`,
  `drive_entry_valid` keep their defaults (1.0/…/False) although the analyzer DTO carries
  all three → ranking is nearly a setup-label sort.
- **G3:** no marginal-headroom sizing: `SessionRisk.position_size` sizes per-engine and the
  portfolio only *refuses* over-limit entries — it never re-sizes a candidate down to the
  remaining budget, so the best setup can be rejected while a lesser one takes the last
  rupee (first-come outside the auction hold).
- **G4:** `SessionRisk.is_pyramiding_unlocked()` ("pyramiding only in Tier 2") has **zero
  production callers**; pyramids gate solely on `is_risk_free` — two contradictory
  authorization policies in code, one of them dead.

**Total portfolio risk control**
- **G5:** restored positions register **0.0** open risk
  (`runtime.py:780` in `restore_position`: `self._portfolio_risk.register_open(0.0, symbol=…)`) → after
  any restart the aggregate open-risk budget under-counts live exposure by the full
  restored book.
- **G6:** WS/snapshot equity is a third authority (see §5.2): `balance ≡ INITIAL_CAPITAL`
  + last-50 closed trades + open PnL — disagrees with both the fold's `realized_pnl` and
  `SessionRisk` equity after 50+ closes.
- **G7:** `backend/config/base.yaml` top-level `risk:` block (`:534-536`) still ships `risk_per_trade_pct: 0.95, max_daily_loss_pct: 0.50,
  max_consecutive_losses: 5` while
  strategy overlays ship sane `0.0025/0.02/3`. The no-overlay path (any strategy file
  missing a key) silently inherits 95%-risk defaults; loader defaults only fill *absent*
  keys, they don't cap present absurd ones.
- **G8:** risk config keys `kelly_*`, `portfolio_notional_cap`, `per_symbol_notional_cap`,
  `max_drawdown_pct` are loaded/validated but have **no consumer** in `quant/` (only
  `max_concurrent_positions`, `max_portfolio_*`, `starting_equity` are forwarded by
  `composition_root`) — config promises the code doesn't keep.

**Options-specific sizing/execution vs playbook §15b**
- **G9:** §15b.1 says the option leg is *never* an independent premium-tape story, but
  `runtime` still launches "independent scalping … AMT directly on option premium" whenever
  no root futures engine exists — policy-violating mode ships.
- **G10:** delta translation uses constant `DEFAULT_OPTION_DELTA=0.5` ("No chain-Greek
  producer exists") although the scanner already computes per-contract `delta_val` and
  engines carry GEX (`set_gex`) — stops/targets can be off by ~2× vs true delta.
- **G11:** entry-time premium floor: the ₹20–800 band exists only at scan
  (`scanner._process_contract`); nothing re-checks premium scale at entry (a rotated or
  drifted contract can enter below band).
- **G12:** §15b.5 "mid-trade blowout uses the same basis" not implemented (fixed 3%/1.5%)
  — overlaps §7.5.
- **G13:** contract expiry identity: `contract_expiries` config read in `_contract_for` but
  never populated anywhere; expired day+month still rolls via the month-token fallback
  (§7.6b).

**Hygiene / truthfulness**
- **G14:** two RED tests encode the pre-repair expiry semantics (`test_session_gates.py`):
  `test_valid_mcx_symbol` fails `result is not None` at `:68` ("17 AUG" without year parses
  to 2026-08-17, correctly refused as past); `test_past_date_rolls_to_next_year` dies with
  `AttributeError: 'NoneType' object has no attribute 'year'` at `:82`. Re-run: 2 failed / 12 passed. Disposition: **P0-2** (stale tests, not product bugs).
- **G15:** stale docstrings/comments: `gate_position_cooldown` (family limit), `timesfm_risk` module header ("replaces rigid 0.8R breakeven…", authority now dead), `build_forecast(vah,val)` (§6.6), **risk.py House-Money docstrings `:601-604` ("0.35% + 20% of session profit" — code is 0.25% + 40%/30% tiers), gate_session_phase spread comment `:104` (₹0.40 — code 0.50/2.00)**.
- **G16:** `scripts/scan_half_lot_rejections.py` root/lot blindness (§4.6).
- **G17:** `check_spread_blowout` threshold vs entry band (§7.5/G12); VWAP-drift comment-only
  rule at 6% (§3.6).

---

## 5. Prioritized implementation plan

Each item: **finding** → **files/classes/functions** → **change** → **tests** → **target behavior**.

*Ordering: P0 tier = NEW-P0-1 + NEW-P0-2 (the only entry-blocking defects) + P0-2
(green-tree hygiene). P1-1 stays P1 — its option half is fail-closed, but the non-option
identity fallbacks remain money-relevant. No other item changed tier.*

### P0 — money-path blocked now

**P0-1 · Make OpportunityAuction settle (NEW-P0-1, G1)**
- Files: `quant/execution/opportunity_auction.py` (`propose`, `_pick_winner`),
  `quant/engine/submission_handler.py:_apply_risk_ceilings`.
- Change: stop resetting a symbol's `created_at` on re-propose (`setdefault` semantics keep
  the first-arrival timestamp), and make settlement reachable from a single proposer: either
  settle immediately when no *competing* proposal is pending, or return a structured
  "retry-after hold" that `SubmissionHandler` retries **with the same proposal object** in a
  bounded ≤300 ms loop before blocking. Keep score-ranking for true contention.
- Tests: new `tests/quant/test_opportunity_auction.py`: (a) single proposer settles on
  retry after hold and `register_open` books risk; (b) two symbols, higher score wins the
  grant, loser gets `out-ranked`; (c) expiry TTL; (d) end-to-end
  `SubmissionHandler.submit` with auction wired approves a good signal (regression for the
  starvation repro in §0).
- Target: with the coordinator's default wiring, an approved signal reaches `oms.submit`
  whenever portfolio limits allow; denial reasons name a real limit, never the hold window
  alone.

**P0-2 · Green tree: reconcile expiry tests with the never-roll policy (G14, §7.6)**
- Files: `tests/quant/test_session_gates.py::test_valid_mcx_symbol`,
  `::test_past_date_rolls_to_next_year`; optionally `quant/session_gates.parse_contract_expiry`.
- **Disposition:** stale tests pinning the deleted roll, not product bugs — failure lines and details in G14. Rewrite both assertions for never-roll semantics (never the parser).
- Change: rewrite assertions for the new semantics (past day+month without year → `None`;
  explicit-year past date → `None`; add: expired compact symbol → `None`).
  `parse_contract_expiry` already accepts a `today=` injection (`session_gates.py:60`), so
  pin dates deterministically; if `test_valid_mcx_symbol` is meant to pin a *live* MCX
  contract, build it from a future date.
- Tests: the two become green; a new case asserts `parse_contract_expiry("NIFTY 17SEP24900CE", today=2026-09-22) is None` (never 2027).
- Target: `pytest tests/quant/test_session_gates.py` fully green with never-roll semantics pinned.

**P0-3 · Unblock the faithful translation path: supply delta on translated engines (NEW-P0-2)**
- Files: `quant/engine/decision_loop.py:_build_context` / `_translate_signal_for_option`,
  `quant/decision/context_builder.py` (`option_delta`),
  `quant/amt/session/selector.translate_underlying_signal_to_option` (reject reason).
- Change: key `option_delta` off the *contract* (`self._symbol`), not `eval_symbol` — build
  the context with `option_delta=DEFAULT_OPTION_DELTA if is_option_contract(self._symbol)
  else None`, or resolve delta inside `_translate_signal_for_option` when ctx has none;
  give the translate→`None` path a truthful block reason (today it mislabels a missing delta
  as OPPOSING_TYPE). Longer term, consume scanner `delta_val` (P2-5).
- Tests: drive `DecisionLoop` with `underlying_gateway` + `get_underlying_symbol` wired
  (extend the fixture at `test_decision_loop.py:207/:246`) and assert an approved underlying
  signal reaches `oms.submit` as a *premium-scaled* option signal — or, if translation
  genuinely refuses, that the block reason is not OPPOSING_TYPE; unit: `translate(delta=None)`
  failure reason named correctly. None of the 14 existing translation tests cover this seam
  (they inject `option_delta` directly).
- Target: with a root futures engine running, approved entries on option engines are no
  longer universally blocked; every denial reason names its true cause.

### P1 — residual money-safety and authority defects

**P1-1 · Close the non-option contract-identity fallbacks (§7.6b, G13)**
*Re-scoped: the option half already fails closed — `_contract_for`'s option branch raises "Missing option contract metadata" (`multi_engine.py:1695-1707`). The `year+1` roll (`:1742`) and `today` fallback (`:1747`) now hit only **non-option** symbols, misarming expiry-day gates both ways (never-fire vs always-fire: spread halving, entry cutoffs). P1 retained for that narrower money-relevant residual.*
- Files: `quant/multi_engine.py:_contract_for`.
- Change: for non-option symbols whose month token is already past or absent, do **not**
  silently roll `year+1` or default to `today` — prefer broker `inst.expiry_date` (already
  consulted at `:1723-1727`), then configured `contract_expiries`, then refuse/pin identity
  explicitly; and either populate the `contract_expiries` map or delete the dead reads
  (`:1695/:1711`).
- Tests: `tests/quant/test_multi_engine_startup.py` — expired spaced/compact symbols never
  yield a next-year `ContractRef.expiry`; broker `expiry_date` wins over parse; a symbol with
  no month token never gets `expiry=today`.
- Target: an unresolvable contract identity can never silently arm every expiry-day rule or
  suppress them all year.

**P1-2 · Restore real open-risk for restored positions (G5)**
- Files: `quant/runtime.py:restore_position`.
- Change: `register_open(abs(open_price − persisted stop_loss) × size, symbol=…)` instead of
  `0.0` (row already carries `stop_loss`); keep `release`/`record_close` pairing on close.
- Tests: restart scenario — open 65×NIFTY with 100-pt stop, restore, assert
  `portfolio.open_risk` includes ₹6,500 and a second entry that would breach the cap is
  refused by `can_accept`.
- Target: portfolio headroom is truthful across restarts.

**P1-3 · One equity authority for the snapshot (§5.2 trace, G6)**
- Files: `quant/multi_engine.py:_recompute_portfolio_equity`, `quant/state.py:_engine_portfolio`.
- Change: compute snapshot equity as `balance + realized_pnl(full fold) + open_pnl`, or set
  `balance = INITIAL + realized` when the fold builds the portfolio — stop deriving equity
  from the 50-entry `closed_trades` window.
- Tests: fold 51 closes of +100 → snapshot equity == `INITIAL + 5100 + open` and equals fold
  `realized_pnl` basis; WS payload assertion.
- Target: UI/snapshot/restart-report equity never disagrees with the event fold.

**P1-4 · Entry/exit spread policy on one basis (§7.5, G12, §8.1)**
- Files: `quant/execution/exit_checks.check_spread_blowout`, `quant/execution/exits.py`
  default `spread_max_pct`.
- Change: implement §15b.5 literally on **one** basis shared with Gate 1: decide the
  canonical formula (playbook's `max(2t,0.1%,₹0.40)` vs code's futures `₹0.50` /
  options `max(10t,1.5%,₹2.00)` at `gate_session_phase.py:124-127`) and make the exit
  blowout threshold (3%, expiry 1.5% — `exits.py:69`, `exit_checks.py:19`) ≥ that entry cap
  everywhere; today the options ₹2.00 floor admits spreads the 3% exit force-closes for
  premiums < ₹66.67 (< ₹133.33 on expiry). Keep an emergency absolute ceiling if desired
  but make it ≥ the entry cap so entry→exit can't self-churn.
- Tests: property test — for any book Gate 1 admits, `check_spread_blowout` does not fire on
  the next bar with an unchanged book; expiry-day halving asserted.
- Target: no admitted entry is force-closed next bar for the same spread.

**P1-5 · Wire real quality features into the auction score (G2)**
- Files: `quant/engine/submission_handler._apply_risk_ceilings`, optionally
  `opportunity_auction.score_opportunity` signature.
- Change: pass `absorption_vol_ratio`, `spread_quality` (book spread vs cap), and
  `drive_entry_valid` from the decision context/DTO into `score_opportunity`; document the
  weights in the playbook.
- Tests: unit — equal setup keys rank by absorption/spread; e2e — two simultaneous
  proposals, the one with better absorption+RR wins the grant.
- Target: "highest-quality opportunity" is decided on evidence, not label+RR alone.

**P1-6 · LVN cluster keeps the strongest trough (§1.7 residual, math-debt misclaim)**
- Files: `quant/amt/profile/lvn.py:_cluster_nodes` call at `:221`, docstring `:97-105`.
- Change: flip to `keep_highest=True` (strength is now inverted) or invert back — one flip,
  plus docstring fix; update math-debt row.
- Tests: `tests/quant/amt/profile/test_lvn_detector.py` — add a `find_lvns`-level assertion
  that the clustered survivor is the minimum-volume node. Note: the existing tests drive the *helper* `_cluster_nodes` with **both** flags (5×
  `keep_highest=True`, 1× `False` at `:88`) — they pin neither the production call at
  `lvn.py:221` nor the survivor's volume rank, so no existing test breaks on the flip.
- Target: NPOC/TP2/LVN-sniper levels track the deepest trough, per spec §5.1 intent.

**P1-7 · Scanner half-lot script reads its own journals (§4.6, G16)**
- Files: `scripts/scan_half_lot_rejections.py`.
- Change: strip the `{IST-day}_` prefix in `root_of` (regex), source `KNOWN_LOTS` from
  `quant.contracts.instrument_registry` instead of a duplicated literal, keep GCD only as
  last resort.
- Tests: fixture journal named `2026-09-22_BANKNIFTY 25 AUG.jsonl` with qty 70 → flagged
  (lot 35); registry-backed lot asserted equal to `get_lot_size("NIFTY")`.
- Target: "0 misaligned" output is meaningful evidence.

### P2 — correctness, honesty, and playbook completeness

**P2-1 · Staleness for unstamped forecasts (§6.4 residual)** —
`timesfm_engine`/`scanner`/`multi_engine` stamp `asof_bar` at build; `runtime._fresh_forecast`
rejects `asof < 0` when `source` claims a model. Tests: unstamped forecast → exits get
`None`; stamped ≤1 bar passes.

**P2-2 · `build_forecast` vah/val (§6.6, G15)** — delete the params or implement the
documented band; test asserts either signature without dead kwargs.

**P2-3 · Config hygiene (G7, G8)** — remove/neutralize `base.yaml risk: 0.95/0.50/5/15`;
add loader validation rejecting `risk_per_trade_pct > 0.05` outside tests; wire or delete
`kelly_*`/`portfolio_notional_cap`/`per_symbol_notional_cap`/`max_drawdown_pct`.
Tests: loader rejects absurd risk; config-keys-consumed architecture test.

**P2-4 · VWAP-drift rule (§3.6, G17)** — either re-base the threshold on a real VA width
(DTO has VA extents) with a test that fires within measured VA widths, or delete the
comment-only rule.

**P2-5 · Options policy closure (G9–G11, §15b)** — decide independent-premium mode (block
in live, or document as explicit config); wire scanner `delta_val` → selector `delta` with
`DEFAULT_OPTION_DELTA` only as last resort; add entry-time premium floor mirroring the scan
band. Tests: live mode refuses option engine without root futures feed unless opted in;
delta-scaled stop within ±X% of chain delta; below-floor premium entry rejected.

**P2-6 · Doc/dead-code truthfulness (G4, G15, §8.3/8.4/8.5)** — fix
`gate_position_cooldown` docstring (point at `PortfolioRiskAuthority` root lock), rewrite
`timesfm_risk` header to advisory-only, reconcile `is_pyramiding_unlocked` (wire to §13.2 or
delete), update spec §2 cushion text and §13.3 TP2 text to code reality.

**P2-7 · Remaining math-debt rows** — keep as the existing dedicated ticket (do not mix
into entry/exit PRs, per math-debt header); first re-verify the drive-tracker row.

**P2-8 · Depth-cache stall aging (§1.3 residual)** — expire `_depth_cache[symbol]` entries
by `ts` (e.g. >5 s) and fall back to the in-line book; test with a stalled stream.

**P2-9 · Aggressive-branch Mon/Fri floor (§4.5 residual)** — apply the same min-1-lot floor
in the `base >= 0.05` branch or assert configs can never reach it (ties to P2-3).

### Suggested PR slicing
1. **P0-1 + P0-2 + P0-3** (unblock entries — auction settlement, faithful-path delta, green tree).
2. **P1-1, P1-2** (recovery/expiry money-safety).
3. **P1-4, P1-3** (spread basis + equity authority).
4. **P1-5, P1-6, P1-7** (quality inputs + LVN + tooling).
5. **P2-\*** batched by hygiene vs options policy.

Every item lands with its listed regression test executed in CI before merge; the §0 repro
script becomes `tests/quant/test_opportunity_auction.py` so this class of wiring defect
cannot ship silent again.

---

## 6. Verified-correct (keep)
The canonical keep-list is **§10 above**, each item cited. Every other behavior confirmed
along the way is a cited **REPAIRED** row in §2/§3 — none may regress while implementing
§5.
