# quantv2 AMT Algorithm Port — Implementation Plan (translate docs/amt into quantv2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** quantv2 implements the docs/amt algorithm: translate v1's proven tracker math into typed quantv2 modules, rewrite setups/stops/exits per doc, add §13 pyramiding/partials, §12 cushion risk, §15 exchange SL/TP, L2 depth.

**Architecture:** 6 chains. Chain 1 builds the data foundation (prints/book/vwap/cvd/profile/absorption — pure computation, unit-testable on synthetic streams). Chain 2 builds the machines (triple-a/second-drive/phases/guards). Chain 3 rewrites the decision layer. Chain 4 makes the engine multi-position. Chain 5 rebuilds session risk per §12. Chain 6 completes the broker (SL/TP/live close) and the golden walkthrough gate.

**Tech Stack:** Python stdlib only, pytest. Translation sources live in v1 `quant/amt/` — implementers READ them for math but NEVER import them.

## Global Constraints

- v1 `quant/` frozen; `quantv2/` must never import v1 (`test_no_v1_imports` stays green).
- Stdlib only; no network in tests (transports/fakes injected).
- **Contract tests pin the doc's exact numbers** — every module's test cites its doc anchor and uses the doc constants verbatim (1.5×avg, 0.5×range, ≥60% one-sided, 68.2% VA, 0.8R BE, 15-bar stale, 2% MDL, 3-loss, ≥30 lots, drive<3, RR≥1.5, 200-tick cap).
- APPROVED only post-submit; every rejection carries a reason; fail-closed.
- Full `pytest tests/quantv2/ -v` green at every task end; frequent commits.
- 5-level-depth constraint: OBI/wall math is tested against 5-level books (Dhan reality), documented in module docstrings.

---

### Task 1: `orderflow/prints.py` — bubble detector (AMT §7.1)

**Files:**
- Create: `quantv2/orderflow/__init__.py` (empty), `quantv2/orderflow/prints.py`
- Test: `tests/quantv2/test_prints.py`
- **Translate from:** `quant/amt/orderflow/aggressive_prints.py` (read for math; do not copy wholesale, do not import)

**Interfaces (produces):**
`Bubble(symbol, ts, price, qty, side, institutional: bool)`, `PrintTracker(min_bubble_qty=30.0, institutional_qty=100.0)`, `.on_print(ts, price, qty, side, flag=None) -> Bubble | None` (returns a Bubble when qty ≥ min_bubble_qty; `institutional` when qty ≥ institutional_qty or flag set), `.bubbles_near(price, ticks, tick) -> list[Bubble]` for cluster queries.

- [ ] **Step 1: Write the failing test** (doc-pinned: ≥30 lots = bubble, ≥100 = institutional)

```python
from quantv2.orderflow.prints import PrintTracker

def test_bubble_thresholds_per_doc():
    t = PrintTracker(min_bubble_qty=30.0, institutional_qty=100.0)
    assert t.on_print(1.0, 100.0, 29.0, "BUY") is None          # below 30: not a bubble
    b1 = t.on_print(2.0, 100.0, 30.0, "BUY")
    assert b1 is not None and b1.institutional is False          # 30–99: bubble, not institutional
    b2 = t.on_print(3.0, 100.5, 100.0, "SELL")
    assert b2.institutional is True
    near = t.bubbles_near(100.2, ticks=2, tick=0.05)             # ±2 ticks of 100.2 → [100.0, 100.1..100.3]
    assert len(near) == 2
```

- [ ] **Step 2: Run red** — `pytest tests/quantv2/test_prints.py -q` → FAIL (no module)
- [ ] **Step 3: Implement** — read `quant/amt/orderflow/aggressive_prints.py` first; keep the threshold semantics (lots comparison, institutional flag) identical to v1 where they match §7.1.
- [ ] **Step 4: Run green** — `pytest tests/quantv2/ -q` (full suite; this task lands when other waves idle — if not green due to OTHER agents' files, run own file + report).
- [ ] **Step 5: Commit** — `git commit -m "feat(quantv2): bubble print tracker (AMT 7.1)"`

### Task 2: `orderflow/book.py` — 5-level L2 book (AMT §7, fabio L96)

**Files:**
- Create: `quantv2/orderflow/book.py`
- Test: `tests/quantv2/test_book.py`
- **Translate from:** `quant/amt/orderflow/aggression.py` + `footprint.py` (OBI/one-sided math)

**Interfaces:**
`BookLevel(price, qty)`, `DepthBook(max_levels=5)` with `.apply_bid_ask(bids: list[(price,qty)], asks: list[(price,qty)], ts)`, `.obi() -> float` in [−1,1] ((bidqty−askqty)/(bidqty+askqty)), `.best_bid/.best_ask/.spread(tick)`, `.wall_levels(threshold_ratio=3.0) -> (bid_walls, ask_walls)` (level qty ≥ ratio × median), `.is_stale(now, max_age_s=10.0) -> bool`, `.one_sided_fraction(window_s=60) -> float` from tracked aggressive prints routed in.

- [ ] **Step 1: Write the failing test** (doc-pinned: OBI bounds, wall = 3× median, stale >10s)

```python
from quantv2.orderflow.book import DepthBook

def test_obi_walls_staleness():
    b = DepthBook(max_levels=5)
    b.apply_bid_ask([(100.0, 500), (99.95, 100)], [(100.05, 100), (100.10, 90)], ts=10.0)
    assert abs(b.obi() - (600 - 190) / 790) < 1e-9
    assert b.wall_levels(threshold_ratio=3.0)[0] and not b.wall_levels(threshold_ratio=3.0)[1]
    assert b.is_stale(25.0, max_age_s=10.0) is True and b.is_stale(15.0, max_age_s=10.0) is False
    assert abs(b.spread(0.05) - 0.05) < 1e-9
```

- [ ] Steps 2–5 as Task 1 (red → translate → green → commit `"feat(quantv2): five-level depth book (AMT 7)"`).

### Task 3: `vwap.py` — anchored VWAP ±σ + anti-climax (AMT §6.1)

**Files:**
- Create: `quantv2/vwap.py`
- Test: `tests/quantv2/test_vwap.py`
- **Translate from:** `quant/amt/profile/vwap.py`

**Interfaces:**
`AnchoredVWAP()` with `.on_bar(bar, typical_price=None)`, `.vwap`, `.sigma1_up/.sigma1_dn/.sigma2_up/.sigma2_dn` (std-dev bands per doc), `.anti_climax(close) -> bool` (close beyond ±2σ = climax extension), `.reset()`.

- [ ] **Step 1: Failing test** (doc-pinned: hand-computed session of 3 bars; anti-climax beyond 2σ)

```python
from quantv2.vwap import AnchoredVWAP
from quantv2.types import Bar

def test_vwap_bands_and_climax():
    v = AnchoredVWAP()
    for c, vol in ((100.0, 100.0), (102.0, 100.0), (104.0, 100.0)):
        v.on_bar(Bar(time="t", open=c, high=c + 1, low=c - 1, close=c, volume=vol))
    assert abs(v.vwap - 102.0) < 1e-9                      # equal volumes → mean of typicals
    assert v.sigma1_up > v.vwap and v.sigma2_up > v.sigma1_up
    assert v.anti_climax(120.0) is True and v.anti_climax(102.0) is False
```

- [ ] Steps 2–5 → commit `"feat(quantv2): anchored vwap bands anti-climax (AMT 6.1)"`

### Task 4: `cvd.py` — velocity + divergence (AMT §6.2)

**Files:**
- Create: `quantv2/cvd.py`
- Test: `tests/quantv2/test_cvd.py`
- **Translate from:** `quant/amt/orderflow/cvd.py` + `drive.py` velocity math

**Interfaces:**
`CVDTracker(ema_fast=3, ema_slow=9)` with `.on_delta(delta)`, `.cvd`, `.velocity` (EMAfast−EMAslow of per-bar delta), `.divergence(price_trend: str, lookback=6) -> str` ("BULLISH_RISING"/"BEARISH_FALLING"/"NONE") — price up + cvd falling = CVD-kill signal source.

- [ ] **Step 1: Failing test** (doc-pinned: velocity = EMA3−EMA9; divergence detects price↑/cvd↓)

```python
from quantv2.cvd import CVDTracker

def test_velocity_and_divergence():
    t = CVDTracker()
    for d in (10, 10, 10, 10, 10, 10, -5, -5, -5, -5):   # price pushed up while cvd stalls/falls
        t.on_delta(float(d))
    assert t.cvd == 30.0
    assert t.divergence("UP", lookback=6) == "BEARISH_FALLING"
    up = CVDTracker()
    for d in (5, 5, 5, 5, 5):
        up.on_delta(float(d))
    assert up.divergence("UP", lookback=6) == "BULLISH_RISING"
```

- [ ] Steps 2–5 → commit `"feat(quantv2): cvd velocity divergence (AMT 6.2)"`

### Task 5: `profile.py` — real volume profile + LVN (AMT §5)

**Files:**
- Create: `quantv2/profile.py`
- Test: `tests/quantv2/test_profile.py`
- **Translate from:** `quant/amt/profile/volume_profile.py` (POC/VA expansion, 68.2%) + `lvn.py` (LVN extraction)

**Interfaces:**
`VolumeProfile(tick, value_area_pct=0.682)` with `.on_price_volume(price, qty)`, `.poc`, `.vah`, `.val` (contiguous two-sided expansion around POC until 68.2% — NOT greedy-by-volume), `.lvns(min_ratio=0.3, min_width=1) -> list[(lo, hi)]` (low-volume nodes = consecutive bins < ratio × neighbor mass), `.layer()` tag passthrough for session/box/impulse layers (layer assignment itself arrives with phases/Task 9; profile stays per-session).

- [ ] **Step 1: Failing test** (doc-pinned: 68.2% contiguous VA; POC = max bin; LVN between two high-volume shelves)

```python
from quantv2.profile import VolumeProfile

def test_va_contiguous_and_lvn():
    p = VolumeProfile(tick=1.0)
    for _ in range(5):
        p.on_price_volume(100.0, 10.0)
        p.on_price_volume(104.0, 10.0)
    for _ in range(2):
        p.on_price_volume(102.0, 4.0)      # the LVN shelf between two masses
    assert p.poc == 100.0
    assert p.val == 100.0 and p.vah == 104.0     # 68.2% of 108 mass → both shelves included
    lvns = p.lvns(min_ratio=0.3)
    assert any(lo <= 102.0 <= hi for lo, hi in lvns)
```

- [ ] Steps 2–5 → commit `"feat(quantv2): volume profile 68.2 va lvn (AMT 5)"`

### Task 6: `absorption.py` — spec absorption + clusters (AMT §7.2)

**Files:**
- Create: `quantv2/absorption.py`
- Test: `tests/quantv2/test_absorption.py`
- **Translate from:** `quant/amt/orderflow/detectors.py` + absorption section of `quant/amt/analyzer.py`

**Interfaces:**
`Absorption(bar, side, vol_ratio, range_ratio, one_sided)`, `AbsorptionTracker(avg_window=20, vol_mult=1.5, range_mult=0.5, one_sided_min=0.60)` with `.on_bar(bar, book_one_sided: float | None = None) -> Absorption | None` (vol ≥ 1.5×avg AND range ≤ 0.5×avg-range AND one-sided ≥60%), `.cluster() -> dict | None` (multi-bar cluster accumulation → `{"high":..., "low":..., "count":...}`; cluster grows when absorptions within 3 ticks of existing cluster).

- [ ] **Step 1: Failing test** (doc-pinned: 1.5×/0.5×/60% triple gate; cluster bounds)

```python
from quantv2.absorption import AbsorptionTracker
from quantv2.types import Bar

def test_absorption_gate_and_cluster():
    t = AbsorptionTracker()
    bars = [Bar(time=f"a{i}", open=100.0, high=100.6, low=99.4, close=100.0, volume=10.0, delta=2.0) for i in range(20)]
    for b in bars:
        assert t.on_bar(b) is None
    # 1.5× volume (15+), range 1.2 ≤ 0.5×avg-range? avg range = 1.2 → need ≤0.6 → compressed high/low
    big = Bar(time="x", open=99.8, high=100.1, low=99.7, close=100.0, volume=20.0, delta=-14.0)  # 70% sellers at one side
    a = t.on_bar(big, book_one_sided=0.7)
    assert a is not None and a.vol_ratio >= 1.5 and a.range_ratio <= 0.5 and a.one_sided >= 0.60
    c = t.cluster()
    assert c is not None and c["count"] >= 1 and c["low"] <= c["high"]
```

- [ ] Steps 2–5 → commit `"feat(quantv2): spec absorption clusters (AMT 7.2)"`

### Task 7: `triple_a.py` — spec state machine (AMT §8)

**Files:**
- Create: `quantv2/triple_a.py` (replaces the `_TripleA` inside amt.py)
- Test: `tests/quantv2/test_triple_a.py`
- **Translate from:** `quant/amt/triple_a.py`

**Interfaces:**
`TripleA(triple_a=..., needs: vwap, cvd, profile, absorptions)` — `.on_bar(bar, ctx_inputs: dict) -> dict | None` emitting `{"phase", "signal", "acceptance", "cluster_high", "cluster_low"}` where AGGRESSION requires: close strictly beyond **cluster** extreme, price on VWAP-consistent side, CVD expanding (velocity sign matches), consolidation occurred within 2 range-steps of POC/LVN during ACCUMULATING, and a 15-bar anti-stale reset.

- [ ] **Step 1: Failing test** (doc-pinned: cluster-extreme aggression + VWAP side + CVD expansion + stale reset)

```python
from quantv2.triple_a import TripleA
from quantv2.absorption import AbsorptionTracker
from quantv2.vwap import AnchoredVWAP
from quantv2.cvd import CVDTracker
from quantv2.types import Bar

def _feed(ta, vwap, cvd, abs_tr, bars):
    out = []
    for b in bars:
        vwap.on_bar(b); cvd.on_delta(b.delta); abs_tr.on_bar(b)
        r = ta.on_bar(b, {"vwap": vwap, "cvd": cvd, "absorptions": abs_tr})
        if r: out.append(r)
    return out

def test_aggression_needs_cluster_vwap_cvd():
    ta, vwap, cvd, abs_tr = TripleA(), AnchoredVWAP(), CVDTracker(), AbsorptionTracker()
    bars = [Bar(time=f"t{i}", open=100.0, high=100.6, low=99.4, close=100.0, volume=10.0, delta=2.0) for i in range(20)]
    bars.append(Bar(time="a", open=99.8, high=100.1, low=99.7, close=100.0, volume=20.0, delta=-14.0))       # absorption
    bars += [Bar(time=f"c{i}", open=100.0, high=100.4, low=99.8, close=100.3, volume=10.0, delta=6.0) for i in range(3)]  # accumulation
    bars.append(Bar(time="g", open=100.4, high=100.9, low=100.3, close=100.8, volume=40.0, delta=30.0))      # aggression beyond cluster high
    events = _feed(ta, vwap, cvd, abs_tr, bars)
    assert events and events[-1]["phase"] == "AGGRESSION" and events[-1]["signal"] == "LONG"
    # anti-stale: 15 more neutral bars reset the machine
    for i in range(15):
        bars.append(Bar(time=f"s{i}", open=100.4, high=100.5, low=100.3, close=100.4, volume=10.0, delta=1.0))
        _feed(ta, vwap, cvd, abs_tr, [bars[-1]])
    assert ta.phase == "WAITING"
```

- [ ] Steps 2–5 → commit `"feat(quantv2): spec triple-a machine (AMT 8)"`

### Task 8: `second_drive.py` — reclaim continuation (fabio L104/L114)

**Files:**
- Create: `quantv2/second_drive.py`
- Test: `tests/quantv2/test_second_drive.py`
- **Translate from:** `quant/amt/orderflow/drive.py` + structure reclaim logic

**Interfaces:**
`SecondDrive(max_drives=3)` — `.on_bar(bar, level: float) -> dict | None` emitting `{"drive_number", "reclaimed", "direction"}`: D1 probes level & rejects; entry signal when price **reclaims** (1m close back beyond the rejected probe level) — LONG above, SHORT below; drive counter; ignore after drive ≥ max.

- [ ] **Step 1: Failing test** (doc-pinned: reject→reclaim continuation, counter)

```python
from quantv2.second_drive import SecondDrive
from quantv2.types import Bar

def test_reclaim_continuation():
    sd = SecondDrive(max_drives=3)
    lvl = 100.0
    assert sd.on_bar(Bar(time="1", open=100.0, high=100.9, low=99.9, close=100.1, volume=10.0), lvl) is None       # probe+reject
    r = sd.on_bar(Bar(time="2", open=100.1, high=100.5, low=100.0, close=100.6, volume=12.0), lvl)                  # reclaim above
    assert r and r["reclaimed"] is True and r["direction"] == "LONG" and r["drive_number"] == 1
    # repeated drives stop after max
    for i in range(4):
        sd.on_bar(Bar(time=f"3{i}", open=100.0, high=100.9, low=99.9, close=100.1, volume=10.0), lvl)
        sd.on_bar(Bar(time=f"4{i}", open=100.1, high=100.5, low=100.0, close=100.6, volume=12.0), lvl)
    assert sd.drives >= 3 and sd.active is False
```

- [ ] Steps 2–5 → commit `"feat(quantv2): second drive reclaim (fabio)"`

### Task 9: `phases.py` — session phases (AMT §10)

**Files:**
- Create: `quantv2/phases.py`
- Test: `tests/quantv2/test_phases.py`
- **Translate from:** `quant/amt/market/opening.py`, `regime.py` + v1 session gates

**Interfaces:**
`PhaseRules(trap_minutes=15, discovery_minutes=30, exhaustion_hm=(11, 30))` — `.phase(ts) -> str` ("TRAP" pre-open-15m, "DISCOVERY" first 30m, "MIDDAY", "EXHAUSTION" after 11:30, "CLOSE" ≥ force-exit), `.allow(setup: str, phase: str) -> bool` (DISCOVERY: SQUEEZE only; EXHAUSTION: no new entries; MIDDAY: allow_trend setups only if trend regime), `.trend_regime(closes: list) -> str` ("UP"/"DOWN"/"RANGE" via half-trend-lite), `.warmup_ok(bar_count) -> bool` (≥15).

- [ ] **Step 1: Failing test** (doc-pinned: discovery squeezes only, exhaustion no entries, warmup 15)

```python
from quantv2.phases import PhaseRules
from datetime import datetime, timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30))

def test_phases_and_permissions():
    p = PhaseRules()
    def ts(h, m): return datetime(2026, 9, 4, h, m, tzinfo=IST).timestamp()
    assert p.phase(ts(9, 5)) == "TRAP"
    assert p.phase(ts(9, 25)) == "DISCOVERY"
    assert p.phase(ts(12, 0)) == "MIDDAY"
    assert p.phase(ts(13, 0)) == "EXHAUSTION"
    assert p.allow("SQUEEZE", "DISCOVERY") is True
    assert p.allow("TRIPLE_A", "DISCOVERY") is False
    assert p.allow("TRIPLE_A", "EXHAUSTION") is False
    assert p.allow("TRIPLE_A", "MIDDAY") is True
    assert p.warmup_ok(15) is True and p.warmup_ok(5) is False
```

- [ ] Steps 2–5 → commit `"feat(quantv2): session phases (AMT 10)"`

### Task 10: `guards.py` — veto layer (fabio L93–107)

**Files:**
- Create: `quantv2/guards.py`
- Test: `tests/quantv2/test_guards.py`
- **Translate from:** `quant/amt/market/state_engine.py` + `vars_detector.py` vetoes

**Interfaces:**
`GuardInputs(cvd_slope, obi, vwap_extreme: bool, drive_count: int, market_state: str, book_stale: bool)`; `run_guards(direction: str, inputs: GuardInputs) -> str | None` returning veto reason or None: CVD-conflict (LONG blocked if cvd_slope < −0.3 NSE), anti-climax (vwap_extreme), drive-exhaustion (drive_count ≥ 3), DEAD market, stale book. Market-state classification helper `classify_market(closes, book) -> str` ("TRENDING"/"BALANCED"/"DEAD" via range+volume compression).

- [ ] **Step 1: Failing test** (doc-pinned: −0.3 NSE CVD veto, DEAD, exhaustion ≥3)

```python
from quantv2.guards import run_guards, GuardInputs

def test_vetoes():
    ok = GuardInputs(cvd_slope=0.5, obi=0.1, vwap_extreme=False, drive_count=1, market_state="TRENDING", book_stale=False)
    assert run_guards("LONG", ok) is None
    assert run_guards("LONG", GuardInputs(cvd_slope=-0.31, obi=0.1, vwap_extreme=False, drive_count=1, market_state="TRENDING", book_stale=False)) == "CVD_CONFLICT"
    assert run_guards("LONG", GuardInputs(cvd_slope=0.5, obi=0.1, vwap_extreme=True, drive_count=1, market_state="TRENDING", book_stale=False)) == "ANTI_CLIMAX"
    assert run_guards("LONG", GuardInputs(cvd_slope=0.5, obi=0.1, vwap_extreme=False, drive_count=3, market_state="TRENDING", book_stale=False)) == "DRIVE_EXHAUSTION"
    assert run_guards("LONG", GuardInputs(cvd_slope=0.5, obi=0.1, vwap_extreme=False, drive_count=1, market_state="DEAD", book_stale=False)) == "DEAD_MARKET"
    assert run_guards("LONG", GuardInputs(cvd_slope=0.5, obi=0.1, vwap_extreme=False, drive_count=1, market_state="TRENDING", book_stale=True)) == "STALE_BOOK"
```

- [ ] Steps 2–5 → commit `"feat(quantv2): guard veto layer (fabio)"`

### Task 11: setups + stops rewrite (doc-verified decision layer)

**Files:**
- Modify: `quantv2/setups.py`, `quantv2/stops.py`
- Test: `tests/quantv2/test_setups.py`, `tests/quantv2/test_stops.py` (append; old cases updated where the doc changes behavior)
- **Inputs now produced by Tasks 1–10:** machines emit evidence dicts; Context.extra carries them.

**Behavior changes (doc-pinned):**
- VA_FADE: fires on close **back inside** VA after sweep (close in [VAL, VAH], prev close outside, cvd_slope opposing the sweep); target POC (TP = poc distance, RR still ≥1.5).
- SECOND_DRIVE: consumes reclaim machine (both directions).
- LVN_SNIPER: `leg_lvn` now from real profile `.lvns()` band + trend-close condition.
- SQUEEZE: retest of **trapped level** (from book walls + profile shelf) within 3 ticks.
- Stops: anchor = absorption **cluster** extreme ±2 ticks (behind), fallback unchanged; TP1 = min(2R, structural), fade TP = POC.
- Guards: pipeline integrates `run_guards` before approval (new rejection reasons CVD_CONFLICT/ANTI_CLIMAX/DRIVE_EXHAUSTION/DEAD_MARKET/STALE_BOOK/PHASE_BLOCK).

- [ ] **Step 1: Failing tests** (one per changed setup; doc-pinned; e.g.)

```python
def test_va_fade_requires_reacceptance():
    # sweep outside, then close back inside with opposing cvd → LONG fade at VAL side
    b1 = Bar(time="f1", open=99.9, high=100.0, low=98.8, close=98.9, volume=10.0, delta=-6.0)   # close below VAL (sweep)
    ctx1 = Context(symbol="X", bar=b1, tick=0.05, vah=100.5, val=99.5, poc=100.0, cvd_slope=0.4, extra={})
    assert detect(ctx1) is None or detect(ctx1)[0] != "VA_FADE"    # still outside → no fade
    b2 = Bar(time="f2", open=98.9, high=99.8, low=98.8, close=99.6, volume=10.0, delta=5.0)      # back inside VA
    ctx2 = Context(symbol="X", bar=b2, tick=0.05, vah=100.5, val=99.5, poc=100.0, cvd_slope=0.4, extra={})
    assert detect(ctx2) == ("VA_FADE", "LONG")
```

- [ ] Steps 2–5 → commit `"feat(quantv2): doc-verified setups stops guards integration"`

### Task 12: exits — 0.8R BE, CVD-kill, shield, partial ladder (AMT §13.1/13.3)

**Files:**
- Modify: `quantv2/exits.py`
- Test: `tests/quantv2/test_exits.py` (append)
- **Translate from:** doc §13 (v1 partial logic in `quant/execution/exit_checks.py` for shape)

**Behavior changes:** BE arms at **0.8R** (close-based or CVD-thrust); CVD-kill exits when `cvd.divergence(...) == "BEARISH_FALLING"/"BULLISH_FALLING"` against position; all exit prices shielded 1–2 ticks inside the structural level; `evaluate_exit` gains partial-ladder returns: `ExitDecision` extended with `partial_frac: float` (0.5 at TP1=+2R or LVN, 0.25 at TP2=VA-extreme/CVD-exhaustion, runner trails).

- [ ] **Step 1: Failing test** (doc-pinned: 0.8R BE, partial fracs)

```python
def test_be_08r_and_partials():
    cfg = ExitConfig(time_stop_min=60, trail_ticks=4, tick=1.0)
    pos = Position(pid="p", symbol="X", side="LONG", qty=4.0, entry=100.0, sl=95.0, tp=110.0, setup="T", opened_at="t")
    b1 = Bar(time="t1", open=100.0, high=104.2, low=100.0, close=104.0)   # +0.8R = 104 → arms BE
    d1, trail = evaluate_exit(pos, b1, {}, cfg)
    assert d1.should_exit is False and trail["be"] is True
    b2 = Bar(time="t2", open=104.0, high=110.5, low=103.0, close=110.0)   # TP1 hit (2R) → 50% partial
    d2, _ = evaluate_exit(pos, b2, trail, cfg)
    assert d2.should_exit is True and d2.reason == "PARTIAL_TP1" and d2.partial_frac == 0.5
```

- [ ] Steps 2–5 → commit `"feat(quantv2): 0.8R be cvd-kill shield partials (AMT 13)"`

### Task 13: engine §13 — pyramids + risk-zero + bundle ratchet

**Files:**
- Modify: `quantv2/engine.py`, `quantv2/oms.py` (adds/close_partial/positions list)
- Test: `tests/quantv2/test_engine.py` (append), `tests/quantv2/test_oms.py` (append)

**Behavior:** engine holds `positions: list[Position]` (base + pyramids). Pyramid add conditions (doc §13.2): existing position at +1R, LVN-retest touch + fresh absorption event, risk-zero (stop ratcheted to BE), sizes +50% (first add) / +25% (second), max 2 adds; bundle stop ratchet moves ALL stops to bundle BE. Position sizing for adds from `risk.py` at base risk × frac.

- [ ] **Step 1: Failing test** (doc-pinned: +50%/+25%, max 2 adds, risk-zero gate)

```python
def test_pyramid_adds_riskzero():
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0)
    eng.amt = SessionAMT(tick=0.05)
    # ... feed bars to open base LONG at 100, SL 99 (risk 1), then push +1R to 101 with LVN retest + absorption
    # assert 1 add at 50% size, stop moved to entry (risk-zero), then +25% add; 3rd add refused
```

(implementer writes the real bar tape per the existing loop-test pattern; assertions: `len(eng.positions)==3`, add qtys `0.5×base`, `0.25×base`, bundle SL == entry for all after first add, 4th add attempt → no new position.)

- [ ] Steps 2–5 → commit `"feat(quantv2): pyramids risk-zero bundle ratchet (AMT 13.2)"`

### Task 14: risk §12 — cushion, 3-loss cutoff, 2% MDL, defensive

**Files:**
- Modify: `quantv2/session_risk.py`
- Test: `tests/quantv2/test_session_risk.py` (append)

**Behavior (doc-pinned):** `RiskLimits(mdl_pct=0.02, max_consec_losses=3, cushion_frac=0.40, ...)`; MDL = 2% of **starting equity** (marked to PnL); after cushion profit: offensive size = base + 0.40×cushion; below MDL−cushion: defensive `min(base, remaining)`; 3 consecutive losses → `halt="THREE_LOSSES"`; cooldown after every trade (not just losers).

- [ ] **Step 1: Failing test** (doc-pinned)

```python
def test_cushion_and_three_losses():
    r = SessionRisk(RiskLimits(mdl_pct=0.02, max_consec_losses=3, cooldown_sec=60), starting_equity=100000.0)
    r.record_fill(+1000.0, now=0.0)              # cushion 1000 → offensive adds 0.4×1000
    assert r.size_multiplier() > 1.0
    r.record_fill(-100.0, now=1.0); r.record_fill(-100.0, now=2.0); r.record_fill(-100.0, now=3.0)
    assert r.halt == "THREE_LOSSES"
    r2 = SessionRisk(RiskLimits(mdl_pct=0.02, max_consec_losses=99, cooldown_sec=0), starting_equity=100000.0)
    r2.record_fill(-2100.0, now=0.0)             # > 2% MDL
    assert r2.halt == "DAILY_LOSS"
```

- [ ] Steps 2–5 → commit `"feat(quantv2): cushion three-loss 2pct mdl (AMT 12)"`

### Task 15: broker §15 — SL/TP orders, live close, wiring (I2/I3/I4 from prior review)

**Files:**
- Modify: `quantv2/dhan_broker.py`, `quantv2/dhan_feed.py` (depth packets → book), `quantv2/engine.py` (emit exit orders), `quantv2/runner.py` (mode routing + restore-on-startup + reconcile wiring)
- Test: `tests/quantv2/test_dhan_broker.py`, `tests/quantv2/test_runner.py` (append)

**Behavior:** `DhanBroker.place_stop(sid, side, trigger, qty)` + `.place_limit_tp(...)` + `.close_position(...)`; `BrokerAdapter.live` routes engine exit decisions to broker orders; entry REJECTED if SL placement fails (never unprotected); runner: `load_state` on build, `BrokerAdapter(mode=...)` actually used for submit in live, `reconcile()` diff logged on startup. Depth frames `{"type":"depth","bids":[...],"asks":[...]}` routed to `DepthBook`.

- [ ] **Step 1: Failing tests** (fake rest: SL placed on entry in live; SL-place failure → SUBMIT_FAILED; runner restores open position; depth frame updates book)

- [ ] Steps 2–5 → commit `"feat(quantv2): exchange stops live close restore (AMT 15)"`

### Task 16: golden walkthrough gate (doc §15 end-to-end)

**Files:**
- Create: `tests/quantv2/test_golden_amtdoc.py`
- Test: replay a synthetic 1-minute session tape producing, in order: TRAP (no entries) → DISCOVERY (squeeze allowed only) → absorption cluster → triple-A AGGRESSION → entry with SL/TP → 0.8R BE → TP1 partial 50% → CVD divergence → CVD-KILL → EOD flatten; assert the journal decision sequence matches exactly.

- [ ] **Step 1: Write the test** with the tape + expected `[(kind, symbol, reason), ...]` sequence
- [ ] **Step 2:** Run; iterate tape (not production) until the sequence holds — any production divergence found gets fixed minimally with its own regression test
- [ ] **Step 3:** Commit `"test(quantv2): golden amt-doc walkthrough"`; update paper-live gate doc note.

## Phase B (separate later plan): options selection + underlying-AMT translation; L2 full-book if a deeper feed ever appears.
