# Valentini Scalper Build Guide — Platform Review

> **Read-only evidence review** of the Python platform in `quant/` against
> `docs/amt/Valentini_Scalper_Build_Guide_Layout.txt`, with the live execution
> path traced via `graphify` (existing graph reused per skill rules;
> vocab-expanded queries from the corpus vocabulary).
>
> **Scope:** strategy mathematics, Indian futures/options correctness, execution
> order, code quality, and guide-vs-platform divergence. The guide describes a
> Node.js/Binance crypto scalper; the platform is a Python/Dhan NSE/MCX F&O
> engine. The review is against the **methodology and execution-order
> semantics** the guide prescribes, not its tech stack.
>
> **Validation:** `pytest tests/quant` → **1764 passed, 11 skipped, 1 expected
> warning** (the `test_lifecycle_races` crash-path test deliberately raises).
> Plus targeted synthetic reproduction of profile and order-flow behavior.
>
> **Working tree:** dirty `quant/bars.py` and `quant/state_machine.py`, and
> untracked `docs/superpowers/plans/2026-09-05-simplification-refactor.md` and
> `tests/quant/test_type_unification.py` are all preserved — this review
> touched none of them.

---

## 1. What Is CORRECT (and better than the guide)

Strengths to keep unchanged.

### 1.1 Auction Market Theory — mathematically sound

| Component | File | Verdict |
|---|---|---|
| CME two-row value area | `quant/amt/profile/volume_profile.py:69-176` | Correct. Average-weighted pair expansion, gap guard, half-step edges. |
| POC with VWAP tiebreak | `quant/amt/profile/volume_profile.py:41-66` | Correct. |
| Session VWAP + σ bands | `quant/amt/profile/vwap.py:24-109` | Correct. Shifted-variance numerical stability, session reset. |
| Absorption with displacement | `quant/amt/orderflow/detectors.py:273-358` | Correct + stricter than guide. Pending candle requires close beyond cluster high/low within 3 bars (guide's `volume > avg × 1.5` alone is insufficient — displacement prevents false positives). |
| Bubble detection | `quant/amt/orderflow/detectors.py:118-187` | Correct. PRIOR-bars-only reference (no self-inflation), σ floor. |
| Triple-A machine | `quant/amt/triple_a.py:37-132` | Correct. Sequential phases, conviction decay, stale reset at 15 bars. |
| CVD tracker with divergence | `quant/amt/orderflow/cvd.py:41-166` | Correct. Sign persistence filter prevents flicker. |

### 1.2 Execution order — correct and defensive

The tick loop in `quant/runtime.py:517-660` is ordered correctly:

```
0. tick-level SL/TP (Fabio: exit immediately, never wait for bar close)
1. option micro-bar decide (if no position)
2. option 5m bar → option AMT analyze → manage_exit or decide
3. underlying ticks → underlying AMT → decide (execution basis)
4. per-tick LTP/OI/depth broadcast
```

- `quant/position_manager.py:318-402` — `_manage_tick_exit` runs under
  `_close_lock` and adopts survivor positions correctly.
- `quant/runtime.py:1100-1145` — thesis-flip runs **only** after
  `manage_exit` declines (preserves SL/spread/CVD/TP/trail priority).
- `quant/runtime.py:984-998` — portfolio risk reserved **before** OMS submit;
  unwound on broker failure (`runtime.py:1001-1017`).
- `quant/position_manager.py:250-268` — double-close guard prevents phantom
  closes.

### 1.3 Indian F&O adaptation — correct

| Feature | File | Verdict |
|---|---|---|
| NSE 5-phase session | `quant/amt/session/context.py:8-26` | Exact Fabio mapping. |
| MCX overnight (23:30 close) | `quant/contracts/timezones.py` | Correct. |
| NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/SENSEX/BANKEX + MCX | `quant/contracts/instrument_registry.py:76-117` | Correct lot/strike/tick. |
| Contract-expiry force-exit | `quant/runtime.py:158-161` | Correct. Option never devolves to futures. |
| Expiry-day sizing halves risk | `quant/execution/risk.py:266-267, 287-288` | Correct. |

### 1.4 Engineering — strong

- Event sourcing: `quant/event_store.py` is source of truth, cached state is
  projection; `periodic_reconcile` detects drift
  (`quant/runtime.py:1487-1574`).
- Determinism: same ticks → same trace (golden-file suite passes).
- Crash containment: `run()` converts thread death into a loud failure;
  broker/OMS exceptions never kill the engine thread (`C3` pattern).

---

## 2. What Is WRONG — bugs and divergences

### 2.1 CRITICAL: Volume double-count in `IncrementalVolumeProfile`

**File:** `quant/amt/profile/volume_profile.py:429-432`

```python
for i in range(start_bucket, end_bucket + 1):
    self._volumes[i][0] += vol_per_bucket
    self._volumes[i][0] += vol_per_bucket   # <- duplicated
    self._volumes[i][1] += vol_per_bucket * float(buy_ratio)
    self._volumes[i][2] += vol_per_bucket * (1 - float(buy_ratio))
```

The total-volume line runs **twice**. Reproduced empirically:

```
Full rebuild (create_profile):  buy=400  sell=100  (correct 3:1 delta)
Incremental (_add_candle_to_buckets): buy=0  sell=500  (total doubled, buy zeroed)
```

This corrupts POC, VAH, VAL, LVN/HVN and balance-ratio whenever the
incremental path is active (i.e. live trading after a boundary expansion
triggers `_full_rebuild`, or whenever price stays in-range and the
incremental add runs). The non-`concentrated` branch is affected; the
`concentrated` branch is correct.

**Repair:** delete the duplicate `self._volumes[i][0] += vol_per_bucket` on
the first line of the loop body. The `_full_rebuild` path calls the same
helper, so fixing it fixes both.

---

### 2.2 CRITICAL: AggressionScorer has no trade direction

**File:** `quant/amt/orderflow/aggression.py:51-136`

`AggressionScorer.score()` counts confirming signals but **does not know
LONG vs SHORT**. Reproduced:

```python
# Strong bullish footprint, bullish CVD, big buy prints
# -> used against a SHORT setup
result = scorer.score(footprint_confirmed=True, cvd_confirmed=True,
                      big_trade_confirmed=True, ...)
# -> score 3.5/4.5, confirmed=True, pyramid eligible
```

So a SHORT entry with bullish order flow scores **higher** than one with
bearish flow. The gate pipeline (`quant/decision/gates_edge.py`) later
checks direction separately, but the "aggression score" emitted to the
UI/journal is directionless and the additive FR-06 model is meant to
confirm a directional thesis, not just count activity.
`PersistentAggressionScorer` inherits the flaw.

**Repair:** add a `direction` parameter and gate each component
(footprint, CVD, big_trade, absorption, OFI, bubble) on whether it agrees
with that direction. Bullish components score 0 when
`direction == "SHORT"`.

---

### 2.3 HIGH: CVD confirmation is directionally blind in IMBALANCED

**File:** `quant/amt/orderflow/compute.py:86-93`

```python
if cvd_state is not None:
    if market_state == MarketState.IMBALANCED and cvd_state.slope > 0:
        result["cvd_confirmed"] = True
    elif market_state == MarketState.IMBALANCED and cvd_state.slope < 0:
        result["cvd_confirmed"] = True
```

Both positive and negative slopes confirm in IMBALANCED — so a LONG setup
with steep negative CVD slope gets `cvd_confirmed=True`. The gate's
directional check (`gates_edge.py:48-51`) partially masks this, but it
leaks into the FR-06 aggression score (feeding 2.2) and the UI's CVD
indicator. Same structural issue as 2.2.

---

### 2.4 HIGH: Absorption detector uses only one side

**File:** `quant/amt/orderflow/detectors.py:333-343`

Absorption requires `range_ratio < ABSORPTION_RANGE_ATR` (0.30) AND
`vol_ratio >= ABSORPTION_VOL_MULT` (2.0). But for an intraday 5m candle on
NSE, 2× avg volume is very rare; the guide's 1.5× would fire more often.
More importantly, the detector returns at most the **first** qualifying
candle's side per pending window — if a BUY-absorbed candle is followed by
another BUY-absorbed before displacement, the second is dropped. Minor but
worth noting for scalping sensitivity.

---

### 2.5 MEDIUM: Guide vs platform divergence — intentional but document the gap

| Guide says | Platform does | Assessment |
|---|---|---|
| Volume profile = uniform OHLC distribution | `create_profile` supports uniform **and** concentrated; default uniform | Platform is more configurable. |
| `riskPerTrade: 100` USD fixed | `risk_per_trade_pct` equity-scaled, cushion tiers, expiry halving | Platform is more conservative and correct for F&O. |
| 3-loss daily halt | `max_consecutive_losses=3` AND 2% daily-loss AND `max_trades_per_session=6` | Stricter, correct. |
| Range bars from 1m klines | Interval bars default; range bars available but unused in live `BarAggregator` | The `range_size` path exists (`quant/aggregator.py:76-87`) but `quant/multi_engine.py` constructs `BarAggregator(interval_seconds=...)` without `range_size`. Range bars are only tested, not live. |
| Live trading = Binance futures | Dhan adapter + `LiveOMS` routes to exchange | Platform is correctly wired for Indian brokers. |

---

### 2.6 MEDIUM: Option scanner spread thresholds disagree

**Files:** `scanner.py:182` rejects at **4.0%** spread;
`selector.py:69` `validate_option` rejects at **2.0%**. Scanner scores on a
sliding penalty (`112-116`) but the hard cap at 4% means a contract with
3.5% spread passes to the engine if it scores high. Inconsistent with
Fabio's liquidity requirement. The entry-side gate
`gates_session_position.py:45` is tighter (max 3 ticks / 0.1% / 0.40), so
the engine self-corrects, but the scanner's top-N ranking will prefer
cheaper-liquidity contracts only weakly.

---

### 2.7 MEDIUM: `translate_underlying_signal_to_option` dropped cross-scale guard

**File:** `quant/amt/session/selector.py:399-415`

A guard rejecting `signal.entry > 5× option_ltp` was deleted (correctly per
the inline audit: the original polarity was backwards, since underlying ≈
24000 vs premium ≈ 150 is a 160× ratio — the guard rejected all real
trades). The deletion is empirically justified, but it means a
**mis-wired feed** (option LTP accidentally equals underlying scale, ratio
≈ 1×) passes through. Accept the risk per the code comments; add a
defensive log-only alert if `option_ltp > signal.entry * 0.5`.

---

### 2.8 LOW: Pyramids disabled in LiveOMS

**File:** `quant/execution/live_oms.py:320-324`

`add_pyramid` raises `ValueError("E9: pyramids disabled...")`.
Paper/pyramid math is certified
(`tests/quant/test_pyramid_certification.py`,
`tests/quant/certification/test_e10_base_sl_ratcheted_at_pyramid_fill.py`),
but live pyramid submit→fill→linked-close is not implemented end-to-end,
so it's correctly refused to avoid ghost positions. Paper path
(`quant/execution/oms.py:61-111`) works. This is spec §13.2 deferred, not a
bug.

---

## 3. Execution-sequence correctness

| Step | File | Correct? |
|---|---|---|
| Tick SL/TP protection before aggregation | `quant/runtime.py:580-582` | Yes. |
| Micro-bar entry only when flat | `quant/runtime.py:590, 643` | Yes. |
| Underlying dto drives decisions; option bar settles execution | `quant/runtime.py:591-596, 870-894` | Yes. |
| Option signal translation before risk sizing | `quant/runtime.py:870-894` → `959-963` | Yes. |
| Portfolio risk reserved before OMS | `quant/runtime.py:984-998` | Yes. |
| OMS failure unwinds reservation | `quant/runtime.py:1001-1017` | Yes. |
| Decision emits only after successful submit | `quant/runtime.py:1033` | Yes. |
| Full-close books PositionClosed + RiskUpdated | `quant/position_manager.py:305-315` | Yes. |
| EOD watchdog force-flattens | `quant/multi_engine.py:823-870` | Yes. |

No execution-order defects found.

---

## 4. Code-quality observations

- **God classes persist:** `analyzer.py` (1066 lines) and `runtime.py`
  (1590 lines) remain large despite decomposition. Not a correctness issue
  but a maintainability one. Your active refactor on `bars.py` /
  `state_machine.py` is in the right direction.
- **`compute_order_flow_metrics`**
  (`quant/amt/orderflow/compute.py`) is a 12+ parameter pure mapper —
  correct but has a wide call surface.
- **`BigTradeDetector.detect`** uses a candle-level proxy
  (`vol_ratio < multiplier * 0.5`) and estimates
  `print_count = volume / avg_volume`. Not true tick-level clustering,
  but acceptable for 5m bars.
- **Thread safety is documented where it matters:** `AMTAnalyzer` is
  explicitly not thread-safe and `AMTEngine._amt_lock` serializes access;
  `EventStore` is documented not thread-safe.
- **Tests are comprehensive:** 1764 tests cover golden-file determinism,
  crash recovery, lifecycle races, pyramid accounting, and adversarial
  regressions.

---

## 5. Prioritized repair order

1. **P0 — `IncrementalVolumeProfile._add_candle_to_buckets` duplicate line**
   (`quant/amt/profile/volume_profile.py:430`). Corrupts profile in live
   incremental mode. One-line fix.
2. **P0 — Direction-aware `AggressionScorer`**
   (`quant/amt/orderflow/aggression.py`). Add `direction` param, zero
   opposing components. Affects entries, pyramid eligibility, journal
   truth.
3. **P1 — CVD confirmation direction gate**
   (`quant/amt/orderflow/compute.py:86-93`). Confirm only when slope
   agrees with trade direction.
4. **P2 — Reconcile scanner/selector spread thresholds** (4% vs 2%). Pick
   one (suggest 2%).
5. **P2 — Range bars: document or wire.** Either construct
   `BarAggregator(range_size=...)` in the live path or remove range-bar
   code to avoid dead code confusion.
6. **P3 — Pyramid LiveOMS end-to-end** when broker supports reliable
   submit→fill→linked-close.

---

## 6. Guide accuracy summary

The guide is a **solid replication of the Fabio methodology** for a
Node.js/Binance context. It is **not ground truth** for the platform's
Indian F&O deployment, and several of its numeric thresholds (absorption
1.5×, spread handling, static risk) are intentionally tightened by the
platform. The platform correctly supersedes the guide on:

- Indian market sessions (NSE 5-phase, MCX overnight)
- Lot/strike/tick metadata (InstrumentRegistry authority)
- Broker-agnostic execution (OMS port + Dhan adapter)
- Live risk architecture (cushion tiers, portfolio ceiling, expiry halving)

The guide should be read as the methodological blueprint; the platform is
the production-faithful implementation with tighter risk controls.

---

## 7. Graphify evidence trail

Existing graph reused (`graphify-out/graph.json`, 2411-token vocab). DFS
traversal from 23 seed vocabulary tokens
(`runtime, aggregator, amt, analyzer, decision, execution, option,
underlying, risk, position, bar, absorption, vwap, profile, signal,
order, expiry, futures, tick, trade, portfolio, reconcile, session`)
returned 754 nodes. Key shortest paths confirmed active wiring:

- `Tick` → 5 hops → `PositionOpened` (via `DhanBroker`, `runtime`)
- `AMTAnalyzer` → 3 hops → `PaperOMS` (via `multi_engine.py`)
- `OptionSelector` → 1 hop → `Signal` (translation seam)

Graph vocabulary expansion prevented the wording mismatch noted in the
query reference: the guide says "absorption → accumulation → aggression"
while the platform labels them `ABSORBED / ACCUMULATING / AGGRESSION`; the
expanded traversal resolves both to the same `triple_a.py` node.
