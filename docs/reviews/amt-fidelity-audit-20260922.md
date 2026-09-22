# AMT Fidelity Audit — Whole-Pipeline, Multi-Agent (Round 3)

Date: 2026-09-22 · Branch: `architecture/design-level-refactoring` · Combined with Rounds 1–2.

Method: docs-first (spec text read before code), read-only source tracing, independent isolated
execution (heredoc Python against real production classes with synthetic inputs, in-memory ports
only). Tests were never run and never treated as evidence. No file edits, no app/server launch,
no broker contact, no SQLite opens. Seven domain auditors (exits, risk/sizing, entry gates,
bars/feed, persistence/state, advisor/forecast, options-domain) each ran as an independent agent;
every load-bearing claim below was re-confirmed by the orchestrator directly at the cited
file:line, and quoted REPRO blocks are actual executed outputs from those runs.

Review pass (same day): every citation in this file was subsequently re-opened line-by-line by the
orchestrator, including the secondary ones first accepted from auditor evidence. All survived
except: §3.1's catch-site path was incomplete (`quant/engine/exit_manager.py`, not a file in
`quant/execution/`) and §8 item 11's counterpart was mis-cited as code `pipeline.py` when it is the
doc table `docs/amt/fabio_decision_pipeline.md:106-107`; cross-reference numbering was also
corrected (§2.4/§2.5 → §8, §3.4 → §5.1, §6.2 → §6.3). P0-1 was re-checked after the review and is
still live in the working tree. No finding was added, removed, or downgraded by the review.

> WARNING — working tree: the tree at audit time had ~20 uncommitted parallel edits across
> `quant/amt/*` and `quant/decision/*`. Finding P0-1 is a live defect of that in-flight state,
> not of HEAD. All other findings were checked against the files as they exist in this tree;
> where a claim depends on HEAD vs working-tree differences it is marked.

---

## 0. Why this loses money — the one-paragraph diagnosis

The system's inputs are wrong before any strategy logic runs (feed clamps and drops real volume;
provenance grades itself TICK_EXACT from a symbol string), the entry gates are bypassable exactly
where they matter (spread open when no book, fade path skipping the stop-width cap, warm-up
credited by unscoped history), the exit engine turns a documented "tighten" into a zero-price
full-exit and can strand itself in a raising exception loop, sizing doubles pyramid risk and
refuses to trade on profitable days, restart recovery forfeits every ratcheted stop and can
quarantine live positions behind a phantom ledger id, and the "deterministic" layer is silently
driven by a fabricated TimesFM fallback band that is live by default in `start.sh`. Each defect
individually bleeds edge; composed, the AMT playbook is not being executed at all.

---

## P0-1 · CURRENT-TREE BLOCKER — every `AMTAnalyzer.analyze()` raises NameError

- `quant/amt/analyzer.py:718,720` reference `recent_window`; the symbol is assigned nowhere in
  the working-tree file. At HEAD it is defined at `analyzer.py:549` together with the VA clamp
  block that the in-flight edit deleted. `git diff` on this file: 31 insertions / 45 deletions.
- Consumption: `quant/amt_engine.py:490-519` catches the exception ("keeping last good DTO") and
  returns `{}` once the log is emitted; `decision_loop.py:456` then feeds the pipeline an empty
  DTO — POC/VA/VWAP/σ/CVD/direction are all 0/None, every decision is `NO_EDGE`.
- Observed (auditor run, 40-bar synthetic premium): `ANALYZE RAISED: NameError: name
  'recent_window' is not defined`; downstream:
  `{'approved': False, 'reason': 'NO_EDGE', 'block_reasons': ('TRIPLE_A_EDGE: No direction', …)}`.
- Impact: **right now, on this tree, the system can make no AMT decision at all.** It also means
  whoever restores the deleted block must consciously re-decide the VA-clamp question (Round 2),
  since the clamp removal and the bug arrived in the same edit.

---

## 1. Inputs — bar aggregation & market-feed integrity

### 1.1 (critical) The "vol_cap" silently deletes real traded volume, and the loss is unrecoverable
`quant/brokers/multiplexed_feed.py:120-146, 443-446`.
Doc: AMT spec `:77` (tape feed "computes real-time Bar Delta and CVD"), `:124` (profile = Σ V_buy+V_sell),
absorption `:183` (V_b ≥ 1.5×V̄₂₀). No doc authorizes clipping; the rule exists only in a code
comment ("mirrors the legacy candle_aggregator vol_cap").
Actual: `cap = max(10000.0, pvol*0.05)`; `if dvol > cap: dvol = cap` — and the returned baseline
is the FULL cumulative (`return (vol, …)` at `:143`), so the excess never re-enters any bar.
REPRO (real `_route` + `BarAggregator`, opening-minute burst packets):
```
 i=3 cum=30,000 baseline 12,000 -> tick.vol=10,000  <- clamped from 18,000
 i=4 cum=58,000 baseline 30,000 -> tick.vol=10,000  <- clamped from 28,000
 i=5 cum=89,000 baseline 58,000 -> tick.vol=10,000  <- clamped from 31,000
 exchange traded 136,500 ; bars see 59,500 ; MISSING ~77,000 (56%)
```
The 10k floor binds until day-cumulative passes 200k — i.e. the 09:15–09:45 discovery window.
Consumers: Tick.volume → BarAggregator → AMTEngine → profile/CVD/absorption → gates. Every
volume-derived AMT number is understated ~50%+ on early bars, with no counter or log.

### 1.2 (critical) Baseline is committed before validation — every dropped packet erases its volume
`multiplexed_feed.py:485-516`: `_normalize_dhan_packet` (which writes `self._prev_cum[symbol]`)
runs BEFORE the `ltp<=0` reject (`:488`), the late-tick discard (`:512-514`), and the
`except Exception: return None` path. REPRO: two consecutive live WS packets (11,000 units, 73%
of traded volume) produced no tick yet advanced the baseline; `ltp=0` path: traded 3,600 →
accounted 100. Compounding: `_convert` mixes exchange LTT epoch with `time.time()` arrival
stamps (`:500-504`) and `dhan_adapter.py:469-471` silently swaps `stream_full→stream_poll`
on any WS exception (ISO timestamp strings → arrival clock), after which real exchange-LTT
packets compare *behind* the stored arrival stamp and are discarded as "late".

### 1.3 (high) The 20-level depth cache is never aged — after the depth stream ends, every tick
carries a frozen book
`multiplexed_feed.py:398-418, 526-533, 365-369`. Cached depth always shadows the in-line 5-level
book (`db/da` branch unreachable once warm); when `stream_depth` dies the code only logs
"using stream_full 5-depth" and never clears the cache. REPRO: stale 99.5/100.5 book served
forever while the in-line live book moved to 99.0/100.0. Consumers: `tick_handler.py:135-136`
→ `runtime._depth_update` (`runtime.py:791-792`) → Gate-1 spread check, OBI, Gate-3 aggression —
while `provenance["ofi_depth"]=TICK_EXACT` (`analyzer.py:999-1001`) labels it live.

### 1.4 (high) TICK_EXACT is stamped from the symbol string; the live data-quality gate can never fire
`quant/amt/analyzer.py:991-993, 1060-1067` + `quant/amt_engine.py:200-210`. Spec §16
(`:746-747`) admits trade-level aggression flags are NOT available from the Dhan integration —
and the feed agrees: `multiplexed_feed.py:145-166` `_attr_delta` documents "Dhan WS carries no
aggressor flag… an up-tick is buyer-initiated" (a price-direction proxy; the
`PRICE_DIRECTION_PROXY` grade exists in `data_quality.py:17` but is never assigned). Because
`_cvd_source` returns "underlying"/"option" purely from the symbol name, `cvd_delta` is stamped
TICK_EXACT for every production engine, so `decision_loop.py:407` ("Live AMT entry requires
TICK_EXACT evidence") is structurally dead code. REPRO: `NIFTY 24 SEP 24000 CALL ->
_cvd_source='option' => cvd_delta TICK_EXACT = True`.

### 1.5 (high) Duplicate engine spawn has no idempotency guard — one queue, two readers, one orphan
`quant/multi_engine.py:1830-1845, 2045-2050, 1500-1503`. `_spawn_engine` overwrites
`_engines/_gateways/_threads` unconditionally; the symbols list (futures+options) is built with
no dedup. REPRO with two real LiveGateways on one real feed queue: each engine drains a disjoint
half (A volume 9,000 / B 10,000, true 20,000), both bars' OHLC wrong, orphaned engine keeps
deciding and can submit orders while `_stop_engines`/watchdog/`halt_all` can no longer see it.
(The feed's own header comment `:9-18` describes this exact failure class and the queue
multiplexer was built to fix it — the same hazard is reintroduced one layer down.)

### 1.6 (medium) Unbounded per-symbol queues + freshness stamped at dequeue
`multiplexed_feed.py:181,189,224` (`queue.Queue()` maxsize 0), `runtime.py:991-996`
(`self._last_tick_wall = time.time()` at drain), `multi_engine.py:706-721` (watchdog uses that
same basis). A backlog hours old reports as healthy; `int(tick.time)` (the exchange epoch already
carried per tick) is never compared to `now`. Slow consumer = silent minutes-to-hours staleness
in bars and decisions.

### 1.7 (note, current-tree) AMT-math state issues carried from Round 2 (still open, re-confirmed reachable)
Value-area desert under-coverage (50.25% reproduced); session-VA clamp + leg-VA widening
(in-flux in this very diff); balance-ratio OR-trigger; B-shape forced BALANCED; sticky/both-sides
acceptance flags; drive tracker counting residence not re-approach; forming-footprint overwrite;
epoch-vs-ISO footprint key mismatch; LVN cluster keeping the weakest trough (`lvn.py`
`keep_highest=False` retains min strength); CVD `state()` advancing sign-persistence on read;
clamped σ published as statistical σ; Gaussian footprint rounding non-conservation; flat-price
incremental profile (+0.5 offset, forced 50/50 split); cold CVD/IB/session-VWAP after seed;
duplicate-timestamp double-count; session-rollover retention; 1m-decision-on-stale-5m-DTO.

---

## 2. Entry — gates, evidence, signals

### 2.1 (critical) Gate 1 spread filter: 4% of the UNDERLYING close, and fully open when no book
`quant/decision/gate_session_phase.py:104-125`. Doc: `fabio_decision_pipeline.md:56` —
"Spread ≤ max(2× tick, 0.1% of price, ₹0.40)". Actual: check is inside
`if ctx.ask > 0 and ctx.bid > 0` (no depth → skipped, passed=True); `pct_threshold =
close_px*0.04` — the 4% figure is the scanner's *chain-screening* limit (`scanner.py:459-460`),
not the entry rule; and for LEGACY_TRANSLATED option engines `ctx.bar` is the underlying bar
(`tick_handler.py:148-152`) while bid/ask are the option's book. REPRO:
```
no book:                 GateResult(gate=1, passed=True)
900-pt spread (band 920): passed=True   (doc cap: 23.0)
option book 55/66 (spread=18.3% of premium), underlying close 22400 -> passed=True
```
40× (futures) to 4000× (translated options) looser than documented; fails open. This is the only
slippage admission in the pipeline — exactly the low-premium books that killed paper P&L.

### 2.2 (critical) Gate 4's stop-width verdict is not re-enforced on the VA-fade fallback
`quant/decision/decision_service.py:137-171` + `va_fade.py:86-92` vs `gates_rr.py:24-38`.
After gates 1/2 pass, a Gate-3 OR Gate-4 failure falls through to the fade path, which checks
only direction, `fade.rr >= min_rr`, option-short suppression, and `is_min_stop_met` (a MINIMUM
stop). The documented maximum stop is never re-checked and sizing does not shrink with stop width,
so the over-cap trade is submitted at identical size. REPRO (real `DecisionService.evaluate`):
```
Gate4: passed=False 'Stop too wide (4998 > 3360 ticks)'
approved: True | reason: VA_FADE | SIGNAL sl=21499.95 entry=22400.00 risk=900 pts
= 18001 ticks vs cap 3360 -> excess 5.4x, qty identical to the capped-size qty (225.0)
```

### 2.3 (high) Warm-up is credited with bars the analyzer threw away
`quant/amt_engine.py:361-372` → `context_builder.py:540` → `gate_session_phase.py:58-59`.
`scoped = session_scope(candles)` fills `_amt_candles`, but `self._warm_bars = len(candles)` —
the UNSCOPED count, never updated again. REPRO (real builder + gate): `warm_bars=750,
bar_index=0 → warmup_complete=True, gate1 passed`; with 14 → correctly blocked. After any
multi-session seed, the ≥15-bar rule (§15 row 3) is satisfied on bar 0 of the session while
VA/LVN/VWAP/20-bar volume averages are still garbage.

### 2.4 (high) The structural stop never anchors on the bubble cluster the spec names
`quant/decision/stops.py:27-60, 63-81`. Spec `:362,367` — stop "1–2 ticks BEHIND the Big
Executed Bubble, NOT at arbitrary candle wicks". `_anchor_candidates` offers
`nearest_buy_print_below / leg_lvn / vah / val / bar.low|high`; `ctx.absorption_cluster_low/high`
(the actual cluster, populated at `context_builder.py:617-618`) has NO reader anywhere in
quant/decision (grep). REPRO: cluster low 22390 absent from candidates; chosen anchor == bar.low.
When nothing clears the min-distance floor, `structural_anchor` fabricates one
(`synthetic fallback anchor 22399.75`) and Gate 4 still reports "Stop within cap" — a
non-structural stop published as stop truth. (This also means the "SL inside the cluster" Gap #13
policy is neither inside nor behind the cluster; see §8 doc-conflicts.)

### 2.5 (high) LONG stop sits 2 ticks on the ENTRY side of the anchor
`stops.py:1-7, 84-108`: `if side == "LONG": sl = anchor + offset` — i.e. the §11.2
take-profit shield applied to a stop. Effect: the stop triggers while the support level is still
2 ticks untested — a clean retest that holds (the auction behavior the playbook depends on) is
booked as a loss. Note §11.1 vs §11.2 ambiguity is a real doc conflict (§8), but `oms.py:199`
and `WALKTHROUGH.md:71` both use the "behind" convention that the shared helper does not
implement.

### 2.6 (high) Option-leg translation reports the pre-clamp plan; the emitted stop degenerates to one tick
`quant/amt/session/selector.py:493-514`: `opt_risk = max(tick, underlying_risk*eff_delta)`;
`opt_sl = max(tick, opt_entry - opt_risk)`; `rr = opt_reward / opt_risk` — RR uses the
PRE-clamp risk, not `entry - sl`. REPRO (real OptionSelector, delta 0.5 = DEFAULT_OPTION_DELTA):
```
prem 60.00 -> entry=60.00 SL=0.05 TP=220.00 reported_rr=2.00 ACTUAL risk=59.95 (99.9% of premium)
```
`signal.rr` is what lands in order metadata (`order.py:80`), the cert record
(`decision_loop.py:567`) and fold state (`state.py:177`). No re-validation runs on the translated
leg ("All 4 gates passed" still says so). For cheap/deep-OTM contracts the system submits a
5-paise "stop" = no stop, while every downstream record shows a sane 2R plan.

### 2.7 (verified-correct) Gate pipeline hygiene
All four gates run unconditionally and exceptions become failed gates (fail-closed,
`pipeline.py:31-35`); fade eligibility keys on gate NUMBER not list position (`decision_service.py:137-141`);
gate and builder call the identical anchor/stop pair (no gate↔builder divergence on the
all-pass path); `_shield_tp` applied exactly once and never to a VA-fade POC; data-quality
admission fail-closed on missing capability (`data_quality.py:27-31`); the 5-session-phase clock
check behaves correctly for both epoch and ISO inputs on today's feed.

---

## 3. Exits

### 3.1 (critical) The "tighten SL" rule exits at price 0.0 and preempts the structural-stop check
`quant/execution/exit_checks.py:35-55` + `exits.py:233-237`.
`check_stacked_imbalance_tighten` returns `ExitDecision(True, "STACKED_IMBALANCE_TIGHTEN", 0.0)`
— despite its own docstring ("tighten by moving SL to entry … instead of full exit"), it never
amends any stop (single production site, grep), and it runs ABOVE Rule 2 (protective stop).
Doc: ARCHITECTURE `:410-416` — monotonic tightening; STOP_LOSS is exit type #1; fabio doc `:99`
lists opposing stacked imbalance as an ENTRY veto only. REPRO (real ExitEngine + real paper OMS,
bar low 97.90 < SL 98.00):
```
evaluate -> ExitDecision(True, 'STACKED_IMBALANCE_TIGHTEN', 0.0)
_execute_full_close(oms.close(... price 0.0)) -> ValueError: paper reference_price must be positive
caught at `quant/engine/exit_manager.py:244-253` -> '[EXIT FAILED] … position kept open, will retry next bar'
```
Every bar showing an opposing stack ≥3 while price is through the stop: the documented SL exit
never books (bar path; tick path still enforces), the position can stay stuck open, and the
journal eventually labels the exit `STACKED_IMBALANCE_TIGHTEN` instead of SL — poisoning
exit-reason analytics (which includes the known label-keyed terminal-TP logic).

### 3.2 (critical) Tier ladder rounding over-closes, kills the runner, and strands a 0-size ghost position
`quant/execution/oms.py:255-266` (`lots = int(size/lot); close_lots = max(1, round(lots*fraction))`)
+ `position_manager.py:216-220` + `exit_manager.py:255-256`.
Doc §13.3: 50% / 25% / 25% runner. REPRO (real PaperOMS close_partial, lot 100):
```
2 lots -> TP1 50% + TP2 50% -> runner left 0.0%
3 lots -> TP1 66.7% + TP2 33.3% -> runner left 0.0%
TP2 on remaining 100: booked 100.0 -> surviving Position size = 0.0 kept as pm.current_position
next bar on the ghost: should_exit=True reason='SL' price=98.0 -> OMS raises
   'paper quantity must be a positive lot multiple' -> [EXIT FAILED] repeats every bar
DecisionContext position_open stays True (context_builder.py:370) -> entries blocked all session
```
Only exact multiples of 4 lots execute §13.3; 1-lot trades book a FULL close labelled TP1
(`count_as_trade=False` is not applied — it is a full close, so streaks DO move on what the
journal calls TP1). The ghost-position sequence follows directly from `close_partial` returning
a non-None `remaining` at size 0: `_book_full_close` is skipped and the flat book keeps owning
stop state + gate 6.

### 3.3 (high) Breakeven/risk-zero anchor on `signal.entry`, not the actual fill → "breakeven" books a loss
`exits.py:174-178, 285` + `exit_checks.py:120-133` + `oms.py:141-143`. Production paper default
`fill_mode="bid_ask"` (`oms_factory.py:37`) — longs fill at the ask; `entry = position.order.signal.entry`
everywhere in exit math; `is_risk_free()` gates pyramid adds (`position_manager.py:253`).
Doc §13.1: BE at +0.8R "strictly $0.00 downside"; §13.2: pyramid only at Risk-Zero.
REPRO (ask 100.15 vs signal entry 100.0, SL 98.0):
```
bar1 close 101.70: true 0.775R, engine 0.850R -> is_risk_free=True, pyramids armed
bar2: exit reason='BREAKEVEN' booked pnl = -20.00 ; consecutive_losses -> 1
```
Corroborated in the read-only run log `backend/backend_e2e.log`: `reason=BREAKEVEN pnl=₹-46.50`.
Those phantom losses feed the 3-loss halt and the cushion sizing — cross-domain amplification.

### 3.4 (high) Restart silently reverts every ratcheted stop, the TP tier index, and the time stop
`quant/runtime.py:736-749` + `quant/persistence_bridge.py:42-45` + `execution/oms.py` row writer.
`ExitEngine` keeps `_breakeven/_trail/_tp_tier` in process memory keyed by `position._id`; the
bridge subscribes only to Opened/Reduced/Closed (never StopMoved); `position_to_row` persists the
ORIGINAL `sig.sl` and no tier/BE fields; `restore_position` zeroes `_entry_time_epoch`.
REPRO: same-process engine on re-touch books nothing; restarted engine books TP1 50% AGAIN;
post-restart `stop_state=(None,None)`, `is_risk_free=False`; `check_time_stop` minutes branch is
dead with epoch 0.0. Given §5.1's phantom-fill-id quarantine bug plus daily deploys/restarts, the
documented monotonic-stop invariant exists only within one process lifetime.

### 3.5 (medium) Tier index and BE floor are written inside `evaluate()` before the OMS tries to fill
`exits.py:279-288` — `self._tp_tier[...] = new_tier; self._breakeven[...] = entry` happen before
`position_manager` calls `close_partial` (which is the next statement); no rollback on failure.
Tick path does it correctly after the fill (`position_manager.py:455-476`). REPRO: OMS raises
(unavailable quotes) → position full-size but tier burned → ladder jumps to TP2, and
pyramiding is authorized from a BE floor armed by a fill that never happened.

### 3.6 (medium, comment-only rule) VWAP-drift exit is ~150× too wide to ever fire
`exits.py:67, 74-79` + `exit_checks.py:140-149, 168-172`: threshold is 6% of entry (2×3%) vs
profit<1R where Gate-4 caps risk at ≤0.75% of entry — mutually almost unreachable; measured real
VA widths (551 log lines): median 0.04%, p90 0.96%, vs the comment's claimed "1 VA-width".
The rule exists only in a code comment (no doc §), hence medium. The anti-drift tightening is
inert in live data.

---

## 4. Risk, sizing, portfolio authority

### 4.1 (critical) Pyramid add-ons snap UP to whole lots and reserve the pre-snap size
`quant/position_manager.py:606-638` + `oms.py add_pyramid` + `execution/lots.py:9-18`
(`max(1.0, floor(q/lot + 0.5))` — half-lots round UP, min 1 lot). Doc §13.2: P1 = 0.50×base,
P2 = 0.25×base, bundle net-positive guaranteed. REPRO (NIFTY lot 65):
```
base 1 lot: P1 doc 0.5 lot -> actual 1.0; P2 doc 0.25 -> actual 1.0 ; total 3.000x (doc 1.75x)
hand-check §13.2.4: base +17x65 locked; add-ons risk 13ptx130u -> bundle = -Rs585 at the
ratcheted stop (doc 0.75-lot total would stay +)
position_manager.py:638 reserves add_risk with the PRE-snap size (0.5 lot) -> ceiling under-books
SessionRisk.pyramid_position_size has no production caller (the self-declared sizing authority
is bypassed for pyramids entirely)
```
Live path exists (`live_oms.py:462 add_pyramid`).

### 4.2 (high) The 30%-of-session-profit ceiling applies to TOTAL risk → profit switches trading OFF
`quant/execution/risk.py:601-604`: `if daily_pnl>0: risk = min(risk, daily_pnl*0.30/starting_equity)`
— caps the whole per-trade pct, not the cushion add-on (§12.2: base 0.25% + 40% cushion;
selector.py comment "the old min(..., 30% profit) cap could never bind"). REPRO
(E₀=1M, option entry 150/SL 120 → 1 lot risks ₹1,950):
```
realized 0    -> 1.00 lot; realized 1,000 -> pct 0.0003 -> 0 lots (NO TRADE)
realized 5,000 -> 0 lots (doc 12.2 would allow 2.31 lots); realized 6,500 -> 1 lot
```
After ANY win below ~₹6,500 the engine refuses to trade (submission_handler latches
"risk budget affords 0 lots") — directly matches the observed trade starvation in paper.

### 4.3 (high) SessionRisk never rolls over — daily breakers become lifetime breakers
`risk.py:100-111` (`_date`, `_day_of_week` fixed at construction; `_key()` frozen), `:511-524`.
`reset_session()` has ZERO production callers (grep across quant/+backend/: only tests/docs);
AMT rollover detection (`amt_engine.py:439-459`) resets candles/profile but never touches
`self._risk`; `eod_square_off` ("next-day trading must stay unaffected", `multi_engine.py:1163-1173`)
leaves counters in place; no scheduled restart exists. REPRO: after 3 losses —
```
same object, simulated next session: can_trade() -> (False, 'max consecutive losses reached'); sizing 0.0
```
In any process alive past midnight: halt latched forever; yesterday's profit inflates today's
cushion; the Mon/Fri multiplier is the CONSTRUCTION day's weekday forever. Futures engines are
never rotated (`check_and_rotate_dead_symbols` respawns option engines only), so futures carry
stale risk state indefinitely.

### 4.4 (high) The 2% account kill switch is per-engine against a hard-coded ₹1,000,000
`quant/runtime.py:527-537` constructs `SessionRisk(...)` WITHOUT `starting_equity` → every engine
inherits `INITIAL_CAPITAL=1e6` (§12.1: E0 = account balance at session start); halt = 2% of ₹1M
= ₹20,000 PER SYMBOL. The only account-wide breaker is `PortfolioRiskAuthority` daily-loss kill
at 15% (`portfolio_risk.py:30,37`), and `multi_engine.py:455-458` reads
`config.get("max_portfolio_daily_loss_pct", 0.15)` — no backend config/** file sets that key, so
15% is what actually runs — and it merely refuses new entries. `max_concurrent_positions: 5` is
loaded/validated/logged but has NO consumer in quant/ (composition_root `_coordinator_risk_config`
drops it). Paper ran 42-63 symbols/day → 84-126% of equity of "2% stop" available while every
documented breaker reports satisfied. (Fold `equity` also compounds with §5.2.)

### 4.5 (medium) Mon/Fri "defensive size" = zero size for 1-lot trades
`risk.py:473-475`: `qty *= 0.5` then `int(qty // lot) * lot` floors 1 lot → 0 → whole setup class
rejected on Mon/Fri (`entry=150 sl=120 -> qty 0` vs Tue 1 lot; 3 lots → 1 lot = 33%, not 50%).
§10.4 says half size, §16 says the 0.5× multiplier — "no size" is neither. Note: commit 72a4fff2
added the same floor to the aggressive branch (uncommitted tests exist); the production branch
case is unfixed.

### 4.6 (medium) The half-lot rejection scanner cannot see half-lot closes
`scripts/scan_half_lot_rejections.py`: `root_of(path.name)` on `"2026-08-24_BANKNIFTY 25 AUG …jsonl"`
returns `"2026-08-24_BANKNIFTY"` → KNOWN_LOTS miss → `infer_lots()` = GCD of observed quantities
(single 870 sample → "lot=870"); the alignment loop reads `evt["fill"]["quantity"]` which does
not exist on PositionClosed/Reduced records → every close is skipped; its KNOWN_LOTS (75/35/65/140)
contradict the registry (65/30/60/120) it claims to mirror. A "0 misaligned" report from this
script is not evidence the sizing fix works. (Lot authority is triple-split: registry vs this
script vs exchange_config.py; broker lot effectively ignored, `multi_engine.py:1753-1767`.)

---

## 5. Persistence / state fold / journals

### 5.1 (critical) Tiered partials write the durable fill row under a phantom position_id
`quant/execution/oms.py:290-299` — `close_partial` builds the FILL-side Position without `_id`
(uuid4 default_factory) while the residual keeps the real `_id` (`:324`);
`quant/persistence_bridge.py:136-148` keys the ledger row off `partial.position.id`;
`reconstruct_fill_ledger` groups strictly by position_id; the restart guard
(`multi_engine.py:2002-2029`) compares reconstructed quantity vs the durable row. REPRO:
```
durable open row id d429d4d8 size 50 ; fill row key 9adb238d (matches nothing)
guard: reconstructed 100.0 vs row 50.0 -> unresolved_startup.add('ledger-mismatch') -> restore SKIPPED
reconstruct-ALL -> phantom -50-lot short appears in the book
```
Every TP1/TP2 scale-out silently forfeits cross-restart recovery of the runner: the position
persists in the durable book with no engine, no fold and no stop owner. Also
`multi_engine.py:2029` `break`s after the first row per symbol — only one open position could
ever restore even when ids agree.

### 5.2 (high) The fold never banks partial-exit PnL → two authorities for the same cash in one state
`quant/transitions.py:208-232` vs `:261` — only `PositionClosed` adds
`realized_pnl += event.fill.pnl`; the `PositionReduced` branch shrinks the position/merges stops
but leaves realized untouched. Meanwhile `position_manager.py:232/467/503` call
`risk.record_trade(partial.pnl, count_as_trade=False)` → folded back as `risk`. REPRO:
```
TP1 +500 banked: fold realized_pnl=0.0 ; equity=1,000,500 ; true 1,001,000
after runner close +600: fold realized 600 vs true 1,100 ; risk.daily_pnl = 1,100 ; gap = 500
```
`state.py:_engine_portfolio` equity, the cushion tiers, `snapshot()`/WS and restart reports all
read the fold; the documented "state is derived by folding append-only events" (ARCHITECTURE
`:486,100`) is false for scale-outs. Related (trace): `_recompute_portfolio_equity`
(`multi_engine.py:803-817`) overwrites fold equity with a sum over `closed_trades[-50:]`
(`transitions.py:263`) — with >50 closes a THIRD number surfaces (51×+100 → 1,005,000 vs 1,005,100).

### 5.3 (high) A second, undated prior-levels authority clobbers the dated session store
`quant/runtime.py:699-734` + `quant/amt/session/context.py:394-455` vs `quant/session_levels.py:79-120`.
`AMTEngine.__init__` loads DATED `session_levels.load_levels` (incl. `close`), then
`attach_storage` (runs after) overwrites with `prior_profile:SYMBOL` kv — no date, no close
(`set_prior_profile` defaults `close=0.0`, never seeds `_last_underlying_close`). The kv writer
is invoked not just at stop but by mid-session rotations (`switch_symbol`, dead-symbol rotation,
rescan, gameloop), so "previous-session levels" become today's truncated intraday profile.
REPRO: after attach_storage `_prior = {poc:24930 …, close:0.0}` while the dated store still says
`{date 2026-09-18, poc 24995, close 24980}`; gap classification (`analyzer.py:1118`) falls back
to prior_poc. Direct violation of the persistence-audit promise "each concern has exactly one
writer" (commit 7b14d0b7 doc).

### 5.4 (high) Completed-session levels/NPOCs persist only when the NEXT session's first bar arrives
`quant/amt_engine.py:434-459` — the sole close-of-session writer is the rollover branch inside
`analyze()`, gated on `self._session_date` which a fresh process lacks. No session-close/EOD hook
exists (grep: `save_levels`/`add_session_poc` writers only at cold-seed `:341-353`, rollover
`:443/451`, plus runtime kv path). REPRO: process spanning midnight writes levels only after the
next session's first bar; the production restart-between-sessions lifecycle writes NOTHING —
every subsequent session sees POC_prev=0. Gap classification, TP2 anchors and NPOC magnets
silently degrade to zeros day after day. (This is the durable half of Round 1/2's
"prior-session-data-not-flowing" gap.)

### 5.5 (medium) One NPOC store keyed by root with first-writer-wins: an option-premium POC poisons the underlying
`quant/session_levels.py:131-143` + `amt_engine.py:451` — every engine (futures AND options)
constructs its own NPOCTracker over the same `SessionLevelStore`, all writing under the ROOT key;
the disk keeps the FIRST record per session_date and in-memory dedupe is per-instance, so the
losing engine's memory and disk permanently disagree. REPRO: option engine wins the key with
poc 5.2; after restart the futures decision sees NPOC 5.2, the scale filter
(`signal_builder.py:265`: 0.70×entry ≤ npoc) rejects it → documented NPOC-based TP2/runner
target disappears; in-process ≠ post-restart decisions on identical bars.

### 5.6 (medium) Journals are filed under machine-local dates while records and risk keys are IST
`multi_engine.py:2032` (`_dt.now().strftime`) and `trade_journal.py:570+` (`date.today()`) vs
`_now_ist()` payloads and IST-keyed risk (`risk.py:44-45`). REPRO with TZ=America/New_York:
entry timestamp 2026-09-22T06:44+05:30 lands in `journal_2026-09-21.jsonl`;
`read_entries(2026-09-22)` → 0. On non-IST hosts the compliance/backtest ledger for day D is
filed under D−1 — the audit trail and the decisions it audits describe different days.
(Also trace-only: `restore_position` appends directly to the store bypassing the bus →
restored opens missing from journal/bridge; `_emit` append-then-fold window on transition raise.)

---

## 6. Model usage & provenance honesty (TimesFM) — these paths are LIVE, not default-off

Correction to Round 2's assumption: only `LLM_ADVISOR_ENABLED` is default-off.
`start.sh:46-47` ships `TIMESFM_ADVISOR_ENABLED:-true` and `TIMESFM_CONTRACT_SELECTION:-true`,
the timesfm package is installed via `.venv/.../miniconda.pth` and the 3.0 weights are cached
(`~/.cache/huggingface/.../model.safetensors`) → the following are production paths.

### 6.1 (high) The "quantile trailing stop" is the one-step p10 peg, written into real stop state AHEAD of deterministic rules
`quant/decision/timesfm_risk.py:68-88, 177` + `quant/execution/exits.py:187-219` (verified).
`candidate = p10_path[0] - tick`; result written to `tr.stop`/`_breakeven` — the inputs of the
deterministic resolver used on bar AND tick paths — and `should_exit` returns before Rule 2/TP
tiers. Doc §15:733 "Strict zero-discretion execution" for stops; §13.3 tiering; §13.1 0.8R for BE.
REPRO: bar 2 tags TP1 intrabar but closes below: authority ON → exit 100% at close, reason
`VAR_STOP`, −20.1 pts/lot vs booking the TP1 partial at the TP price; +0.03R bar →
`is_risk_free=True` → pyramid authorization ~28× earlier than §13.2. And when the model-driven
stop finally exits, `position_manager.py:299-301` re-stamps the source as
`DETERMINISTIC:<reason>` — provenance washing in both directions.

### 6.2 (high) The ±0.2% flat fallback band has no provenance flag and is sold as native model output
`quant/decision/timesfm_forecast_factory.py:53-57` (verified): quantiles None →
p50=price, p10/p90=∓0.2%, `q_spread=0.0`; `TimesFMForecast` has NO `source` field so
`result_factory.py:74` default `"TIMESFM_3.0_NATIVE"` always fires. Reachable without any
exception at `timesfm_engine.py:526`. REPRO: `p10[0]=149.6999… q_spread=0.0` while
p90−p10=0.4 (internally contradictory), UI/journal labels `TimesFM-SCANNING-ENTER_LONG`.
Consequences: §6.1's stop is driven by a fabricated ₹0.30/₹150 "VaR envelope" with no model at
all; and §6.3's VELOCITY_DECAY exit, which the fabricated zero pct_change guarantees.

### 6.3 (medium) The VELOCITY_DECAY exit is guaranteed to fire on the fallback
`timesfm_risk.py:177`: `abs(forecast.pct_change) < 0.0002` — the fallback's pct_change is exactly
0.0. REPRO: `[F] fallback -> True VELOCITY_DECAY ; real model -> False`. Absence of a model is
read as "auction stagnant" → force-close with a model-attributed reason instead of degrading to
the deterministic time stop. (Doc: TIMESFM_INTEGRATION `:5` "advisory-only … never changes the
deterministic decision".)

### 6.4 (medium) Staleness rule: one enforcement site, unstamped forecasts exempt forever, and a third unauthorized consumer
`quant/runtime.py:1198-1206` (verified logic: `asof>=0` precondition). The other two producers
(`scanner.py:371`, `multi_engine.py:1635` behind a 900s TTL cache) never stamp `asof_bar` (−1),
so their forecasts pass through at any age (REPRO: age=401 → PASSED to exits). Those feed
`scanner._detect_momentum` (`:708-719`), whose BULLISH/BEARISH verdict is a hard directional
filter on option selection (`:428-434` deletes PE (or CE) on a 0.02% 32-step drift ≈ 2.7 ticks)
— an ENTRY-DIRECTION authority that docs forbid (`selection.py:4-5` says forecasts → exits/UI;
spec §15 has no model-authority row at all). Also a config contradiction: `scanner.py:344`
defaults `TIMESFM_CONTRACT_SELECTION` to TRUE when unset while `multi_engine.py:1547` + its
docstring say false.

### 6.5 (medium) The trading retrieval path drops the observation-identity guard the engine itself mandates
`timesfm_forecast_factory.py:100-106` calls `engine.last_forecast_for(symbol)` without identity;
`timesfm_engine.py:199-202, 501-505` state identity is REQUIRED or "a stale forecast is served"
(micro-trigger path evaluates several micro-bars under one bar_index). REPRO `[I]`: reuse path
refuses with identity, serves the other observation's forecast without. The stop-setting path can
execute against a forecast built from a price the market already left.

### 6.6 (low) `build_forecast(vah=, val=)` advertises a value-area band it never computes
`timesfm_forecast_factory.py:36-44, 63-65` — parameters unused; sole caller does real work to
supply them. Also minor (not filed): `bars_held` uses held-bars correctly; quantile (H,9)
contract validated; sizing does NOT consume forecasts (`submission_handler.py:174-186` discards
the fresh forecast — the call is stale-warning-only); `decision_loop` `replace()` patches are
quality/translation only — no forecast flips entry direction/size.

---

## 7. Options domain — futures-scale rules on premium numbers

### 7.1 (critical, current tree) See P0-1 — the NameError kills premium decision state entirely.

### 7.2 (critical) The 5-tick fallback anchor emits a zero/negative stop on cheap premiums and Gate 4 approves it
`quant/decision/stops.py:81` + `:91-104` via `signal_builder.py:122-127`:
`return entry - 5.0*tick` (no structural level cleared the min-distance floor), then
`sl = anchor + 2*tick` → net `entry − 3×tick`, with NO floor at zero and no `sl>0` check
anywhere on the signal path (grep: only `transitions.py:335` guards the trail).
REPRO (real classes; NSE tick 0.05, MCX root tick 1.0):
```
premium 0.10 -> anchor -0.15 sl -0.05 | G4 pass 'stop risk=3 ticks (cap 200)' | SIGNAL rr=2.00 stop_below_zero=True
premium 3.00 (tick 1.0) -> sl 0.00 | G4 pass | risk=3 pts (>=150% of debit) feeds sizing + portfolio open-risk
```
Routine late on expiry day. The ≥₹20 premium band exists only at scan time
(`scanner.py:443-448`), never at entry. A stop at/below zero can never trigger; the position is
structurally naked while every consumer believes it has a stop.

### 7.3 (high) Gate 4's option branch inverts the cap: passes 50-100%-of-premium stops, rejects high-LTP options
`gates_rr.py:27-38` (verified): `dynamic_factor = entry*0.05/tick` under `max(200, …)` — the
5% factor can only WIDEN. Doc `:135`: cap = `max(200, (entry×0.75%)/tick)` ticks; "scaled UP for
high-priced instruments". REPRO:
```
NIFTY…CE px 5.00  G4 pass: stop risk=49 ticks = 49% of premium ; SIGNAL rr 2.00 (TP needs +98%)
px 20.00 pass 50% of premium | px 200-800 FAILS the 5% cap it was written to loosen
CRUDE CE px 3.00 tick 1.0: doc-cap 200 ticks = 6,666% of price (cap meaningless at premium scale)
NIFTY FUT px 24500: cap 0.75% — behaves as designed
```
For every premium under ₹200 (tick 0.05) the "stop-width authority" is a rubber stamp at
50-100% of the debit, validated RR is the synthetic 2R fallback the code's own comment calls
"a fake 'RR pass' by construction" (`:44-46`), and the branch that exists to loosen for
high-priced instruments is what blocks them.

### 7.4 (high) Premium σ-bands feed the anti-climax veto, and the veto message prints rupees as sigmas
`gates_edge.py:181-184`: `f"LONG rejected at +{abs(ctx.vwap_std):.1f}σ extension"` — `vwap_std`
is σ in PRICE units, not a σ-multiple; bands computed on the option's own 3-price premium series
(via the same analyzer primitives as `analyzer.py:717-720`). REPRO (₹2 premium, 3 candles):
true deviation 2.09σ (=3 ticks, ₹0.15) → `'Anti-Climax: LONG rejected at +0.1σ extension'`; the
value area itself is ~3.1 ticks wide. The most important edge guard on an option engine fires on
noise and mislabels its own reason (operator/journal read +0.1σ as benign while rejecting).

### 7.5 (high) Gate 1 admits 4% spreads while the exit engine force-closes at 3% (1.5% expiry)
`gate_session_phase.py:113-123` vs `exits.py:65,181` + `exit_checks.py:19`. REPRO (real gate +
real `check_spread_blowout`): premium 20.00 spread 0.60 (3.0%): GATE1 pass → next bar EXIT
(non-expiry); spread 0.80 (4.0%): pass → exit; expiry-day: a 1-tick (₹0.05) spread on a ₹2 book
exits. Entry/exit liquidity policies contradict → open→forced-close churn whose round-trip cost
(₹0.80) is ~5× the minimum structural stop the same path emits (₹0.10-0.15). (Same rule-site as
§2.1 — fixing one fixes both.)

### 7.6 (high) Expiry authority: parsed year discarded, past dates roll +1 year, broker expiry never wired
`quant/session_gates.py:82-98` (verified): compact regex captures `(\d{2,4})?` but never reads
group 3; `if parsed < today: parsed = date(today.year+1, …)`. Configured override
`contract_expiries` is read (`multi_engine.py:1673-1676`) but NEVER populated anywhere; the
scanner's broker `expiry_date` is dropped at rotation (`:746-755` keeps only `r.symbol`).
REPRO (pinned today=2026-09-22):
```
'NIFTY 22SEP24900CE' -> 2026-09-22, is_expiry=True   (correct)
'NIFTY 17SEP24900CE' -> 2027-09-17, is_expiry=False  (expired days ago -> presented as FY27 live)
'NIFTY24000CE'       -> None, is_expiry=False        (exact shape the broker converter synthesizes)
```
Five expiry-day protections silently off: NSE-14:00 entry block, MCX 21:00/21:30 force-exit,
expiry time stop, 50% sizing cut, spread-blowout halving. `docs/reviews/2026-09-06-valentini-guide-platform-review.md:69`
still certifies expiry handling "Correct". No producer re-checks expiry before subscribing, so a
mis-rolled contract can be traded.

### 7.7 (open, carried) Structural: options trade their own premium tape as if it were the underlying auction
Carried from Round 2: independent option engines (`underlying_gateway=None`), PUT thesis-flip
closes, DEFAULT_OPTION_DELTA=0.5, root-prefix level contamination. New corroboration this round:
§1.4 (premium candles earn TICK_EXACT), §6.4 (direction selection from a drift filter), §7.4
(premium bands in guards), and the options auditor confirmed the ONLY function deriving option
signals from underlying action (`selector.py:429-514`) is unreachable for options because
`decision_loop.py:424` requires `_underlying_gateway`, which options never have.

---

## 8. Doc conflicts & policy items (owner decisions, not code bugs)

1. Gate 1 spread: doc `max(2×tick, 0.1%, ₹0.40)` vs code 4%-of-price with the ₹0.40 term
   deliberately removed (recorded in the `:104-108` comment). Decide one; the code currently
   also fails open with no book — that part is a bug either way.
2. Stop side convention: §11.1 "behind the bubble" vs §11.2 shield "1-2 ticks inside" for
   targets; `structural_stop` implements inside-for-stops; `oms.py:199` docstring and
   WALKTHROUGH:71 say behind.
3. Cushion arithmetic: §2 (0.35-0.50×Cushion) vs §12.2 (0.40×Cushion) vs code (0.35%/0.40% of
   EQUITY + 20%/30%-of-profit variants); selector.py comment says "cushion is exactly 20% of
   session profit". Three implementations, four texts.
4. §12.2 E0 ("balance at 00:00 session start") vs §14 `current_equity` vs code
   `sizing_equity = 1M + portfolio pnl` (undocumented third basis).
5. Tier percentages: §13.3 50/25/25 vs flow box `:67` vs ARCHITECTURE `:414` "runner trailing to
   TP2"; TP2 as Macro-VA-extreme (§9.1) vs code's 2R multiple.
6. TimesFM: "advisory-only, never changes the deterministic decision" (INTEGRATION:5, §15:756)
   vs "forecasts to exits/UI" (selection.py:4-5) vs the code's reality (stop authority + exit
   trigger + contract direction selection = THREE consumers; the third is unauthorized by any doc).
7. `balance_ratio_threshold`: 0.55 global vs 0.70 in several market blocks (base.yaml) — carried
   from Round 2.
8. §4 mandates ATR range bars; §16 declares time candles "an architectural choice" — §4 is
   unimplemented-by-declaration. (Dead `DynamicRangeBarAggregator`'s `_add_range` double-counts
   the crossing tick — no production consumer.)
9. AMT spec contains ZERO occurrences of "option"/"premium"/"expiry": there is no documented
   options policy, so every premium-scale rule in §7 is an undocumented futures extension — the
   deepest fidelity problem for an "options scalper" product.
10. `gate_position_cooldown.py:5` docstring claims "max 2 concurrent open contracts per root
    family" — no implementation anywhere; docs don't require it. Over-promising docstring.
11. CVD veto thresholds: code `cvd_block_neg = -0.3 if MCX else -0.5`
    (`quant/decision/gates_edge.py:192-193`) vs `docs/amt/fabio_decision_pipeline.md:106-107`
    "< -0.3 (NSE) or < -0.5 (MCX)" — inverted family mapping: the code applies the tighter 0.3
    veto to MCX and the looser 0.5 to NSE, the opposite of the documented table.

## 9. Carried from Rounds 1–2 (previously reported; not re-litigated here)
Execution economics (cost model figures, slippage/STT/brokerage math; live OMS native-stop
lifecycle; trailing same-bar extreme; PUT thesis close; DEFAULT_OPTION_DELTA; session-levels root
prefix; deployment sizing ignoring stop width; 0.25% fractional-risk hard-code) and the Round 2
AMT-math/state table (§1.7). Two are re-confirmed as still-present this round (cold-seed warmup
interaction §2.3; label-corrupted exits ecosystem around `is_terminal_tp_only`).

## 10. Verified correct (worth keeping)
- Gate pipeline fail-closed order; fade hard-reject keyed on gate numbers; identical gate/builder
  stop functions; single shield application, never on fade POC; data-quality admission fail-closed
  on UNAVAILABLE; option SHORT cannot be emitted by any live path; tick-size authority fail-closed
  (`UnknownInstrumentError`, prefix-matching forbidden); whole-lot discipline on the ENTRY path;
  halt latches correctly within a process and partial/pyramid closes don't inflate streaks;
  boundary-tick attribution exact (no double/lost); IST-aligned window math for 60/300/900s;
  frozen Bar/Tick — no torn forming-bar reads; `buy+sell==delta` by construction; session-reset
  re-baseline (vol<pvol → delta 0) correct; PositionReduced stop-merge monotonic; EventStore
  refuses future-dated events; bar/tick paths share one protective-stop resolver with correct
  precedence (except §3.1's preemption); 0.8R BE trigger + next-bar arming match §13.1; TIME_STOP
  table keys match session phases; sizing does not consume forecasts; entry direction cannot be
  flipped by a forecast patch.

## 11. Repair order (highest edge-recovery per unit risk first)
1. **Restore the tree to a working analyzer** (P0-1) — decide the VA-clamp question consciously
   while re-landing it; nothing else is testable until then.
2. **Feed integrity** (§1.1-1.3): remove or make observable the vol_cap (log + counter + DTO flag
   if kept), commit baselines only for packets that survive validation, age the depth cache with a
   timestamp and fall back to the in-line book; stamp freshness from `tick.time`, bound the queues.
3. **Exit engine sanity** (§3.1-3.4): make Rule 2b actually tighten via `ProtectiveStopState`
   (never exit at 0.0); rework `close_partial` lot math (floor at 1 lot with remainder handling,
   full-close when remaining==0, no zero-size survivors); BE/risk basis = actual fill
   (`position.open_price`); persist BE/trail/tier/entry-time with the position row and replay
   StopMoved into ExitEngine on restore.
4. **Entry-gate honesty** (§2.1-2.3, §7.5): restore documented spread rule (per-instrument price
   basis; fail CLOSED with no book); re-run Gate 4 + min-RR on the fade fallback and after
   option-leg translation (validate emitted `entry-sl`, floor sl>0, reject tick-floor stops);
   fix `warm_bars` to the scoped count.
5. **Risk/sizing** (§4.1-4.5): size pyramids through SessionRisk with post-snap quantities and a
   1-lot-minimum that SKIPS (not upsizes) sub-lot add-ons; apply the 30%-of-profit cap to the
   cushion term only; per-IST-date rollover (re-key by `date.today(IST)` per access, wire a
   production reset on session start); thread real account equity + make the 2% MDL account-level
   and the 15% portfolio default a config-visible decision; weekday multiplier after lot-floor
   with min-1-lot (or accept half-lot explicitly).
6. **Persistence authority** (§5.1-5.4): stamp the fill row with the RESIDUAL's `_id`; fold
   `PositionReduced.fill.pnl` into realized; one writer for prior levels (delete the undated kv
   or make it a pure projection of the dated store); persist session levels/NPOCs on a real
   session-close trigger (and root-vs-contract keys for NPOC, per-engine).
7. **Model layer truth** (§6.1-6.5): make fallback carry provenance (`FALLBACK_BAND`, q_spread
   honest) and make every consumer refuse non-TICK truth for stop/exit authority; move the TimesFM
   stop BEHIND the deterministic resolver (never preempt §13.3 tiers, never arm risk-free below
   §13.1 0.8R); gate contract-selection drift filter on real inference + stamped freshness; pass
   observation identity in the trading path; reconcile scanner vs multi_engine default flags.
8. **Options policy** (§7.x + §8.9): write an options section into the AMT doc (premium-scale
   stop/TP floors as % of premium, expiry authority from broker metadata, underlying-auction
   requirement or explicit prohibition of premium-tape "CVD"), then fix expiry parsing (read the
   year group; never roll silently; prefer broker `expiry_date`).

Every fix above should land with an independent reproduction turned into a regression test —
not because existing tests pass, but because each finding here was demonstrated with one.
