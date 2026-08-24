# Greenfield Architecture: AMT Options Scalper (Valentini Triple-A)

> **Author role:** Quant engineer + Fabio Valentini methodology practitioner.
> **Status:** Greenfield proposal — ignores all existing code. Grounded in the
> Valentini Scalper Build Guide + live-trading transcript, adapted for **NSE/BankNifty
> index options on the Dhan broker** (paper → live).
> **Goal:** one clean, event-driven, testable system that implements the Triple-A
> edge end-to-end with no dead code, no fabricated data, and a reproducible test story.

---

## 0. The Methodology We Implement (Ground Truth)

From Fabio Valentini's method, the edge is a single thesis, not a bag of indicators:

> **"Institutions absorb one side, then run price away from value. Trade the transition
> from *absorption* to *aggression*, not the noise in between."**

The Triple-A state machine is the entire strategy:

```
WAITING ──absorption detected──▶ ABSORBING ──2+ bars near POC──▶ ACCUMULATING
ACCUMULATING ──BUY absorption + price > VWAP──▶ SIGNAL(LONG)
ACCUMULATING ──SELL absorption + price < VWAP──▶ SIGNAL(SHORT)
SIGNAL ──next bar──▶ WAITING
```

Three supporting tools give the state machine its inputs, in **priority order**
(what Valentini actually weighs):

1. **Aggression (order flow)** — what price IS doing (delta / CVD / aggressive prints). *Decisive.*
2. **Structure (profile + IB + location)** — WHERE price is doing it (POC, VAH/VAL, LVN/HVN, initial balance). *Contextual.*
3. **Timing (VWAP + velocity)** — execution precision (breakout of VWAP ±1σ). *Confirming.*

**Every trade is one of:**
- **Triple-A** (highest): absorption → accumulation → VWAP-breakout aggression.
- **Value-Area Fade** (secondary): VAL bounce / VAH rejection with delta confirmation.
- **No-Trade** (default): nothing qualifies → FLAT. *(Valentini: "I wait for the trade, I don't chase.")*

Hard rules from the transcript: **no counter-flow trades**, entries only at structural
boundaries (VAH/VAL/LVN), one setup at a time, and if the story isn't clear — stay out.

---

## 1. Architecture at a Glance

```
┌─────────────┐   WS/ticks    ┌──────────────────────────────────────────────┐
│   Dhan API  │ ────────────▶ │                INGESTION LAYER                │
│ (NSE+MCX)   │               │  market-data gw ─► tick bus (single consumer) │
└─────────────┘               └──────────────────────┬───────────────────────┘
                                                     │ one tick at a time
                                                     ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          ANALYSIS LAYER (pure functions)                     │
│  candle aggregator → VP (POC/VAH/VAL/LVN/HVN) → VWAP bands → absorption       │
│  → Triple-A state machine → order-flow metrics (delta/CVD)                    │
│  OUTPUT: `AuctionState` — one immutable snapshot per bar close                │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ on bar close (not every tick)
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          DECISION LAYER (deterministic gates)                 │
│  1 session-phase → 2 no-position/cooldown → 3 direction+P → 4 Triple-A edge   │
│  → 5 risk-reward → signal_builder (entry / SL / TP / R:R)                     │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ approved signal
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          EXECUTION LAYER (paper → live)                       │
│  order manager ─► exit engine (SL/TP/trail/VWAP) ─► risk coordinator          │
│  LLM advisory (entry journaled, overseer adjusts exits) — throttled, optional │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ state broadcasts
                                       ▼
                               FRONTEND (view-only: chart + decision card)
```

**The four laws of this architecture:**
1. **Everything in the analysis layer is a pure function of a closed bar.** No hidden state leaks across modules; each detector owns its own state and exposes `update(bar) → partial state`.
2. **One tick is fully processed before the next.** No parallel mutation, no locks, no torn reads.
3. **Decisions happen on bar close, not every tick.** Ticks update the in-flight bar; analysis + gates + signals run once per closed candle.
4. **The LLM is an overlay, never a gate.** It reads the same `AuctionState` the gates used; it can never change a trade, only annotate entries and adjust exits on open positions.

---

## 2. Component Breakdown

### 2.1 Ingestion Layer
- **Market data gateway** (`Dhan`): subscribes to the **underlying futures** (NSE index
  futures / MCX futures) as the primary auction feed, plus the **screened option contracts**
  (per-symbol delta/IV context). Option premium data is the **fallback auction feed** when the
  underlying stream is absent — never mixed mid-session.
- **Tick bus**: an `async` single-consumer queue. One consumer (the aggregator) drains it;
  nothing else reads broker packets directly. This is the *only* place real-time concurrency exists.
- **Symbol screener** (startup + periodic): picks OTM options near the underlying's current
  strike ladder; the instrument set is **re-selected each session** (fresh strikes/expiries).

### 2.2 Analysis Layer — the pure kernel
Every component is a **stateful pure function**: `update(closed_bar) → partial state`, with
an explicit reset at session open.

| Component | Input | Output | Rule |
|---|---|---|---|
| **Candle aggregator** | ticks | closed 1-min bars (OHLCV + delta + OI) | Lee-Ready delta classification; volume-spike clamp |
| **Volume profile** | closed bars | `VP {levels, poc, vah, val, lvns, hvns}` | uniform distribution across low–high; **CME two-row-pairs (average-weighted)** for VA 68–70% |
| **VWAP bands** | closed bars | `VWAP {value, ±1σ, ±2σ}` | volume-weighted std; proportional clamp (0.1%–3% of price) |
| **Order flow** | closed bars | `delta, cvd, cvd_slope, cvd_divergence, aggressive_prints` | from tick-level cumulative buy/sell when available, else Lee-Ready |
| **Absorption detector** | closed bars | `absorption {side, price, strength, bar_age}` | vol > 1.5×20-bar avg AND range compressed; side by buy/sell ratio |
| **IB + location** | session bars | `ib_high/ib_low, zone {above/below/inside VA}, nearest LVN/HVN` | first N bars define IB; location relative to VAH/VAL/LVN |
| **Triple-A state machine** | bars + absorption + VP + VWAP | `phase ∈ {WAITING, ABSORBING, ACCUMULATING, AGGRESSION}` | the canonical transition table (Section 0) |

**The `AuctionState` snapshot** (immutable, one per bar close) is the single contract the
decision layer, the LLM, and the frontend all read. Nothing downstream re-derives analysis.

### 2.3 Decision Layer — deterministic gates
Five hard gates, all fail-fast, fed only by `AuctionState` + position/risk state:

1. **Session phase** — trading window open, warm-up complete.
2. **No-position / cooldown** — no open position, not in cooldown, not risk-halted.
3. **Direction + probability** — agent direction ∈ {LONG, SHORT} and P ≥ threshold; no CVD-conflict.
4. **Triple-A edge** — fresh absorption (bar_age ≤ N) **and** the corresponding VWAP-breakout
   direction; OR a qualified Value-Area fade with delta confirmation.
5. **Risk-reward** — R:R ≥ 1.5 and entry within N ticks of a structural level.

Signal builder produces `{type, reason, entry, sl, tp, rr, confidence}` exactly per the
guide's `generateSignal()`.

### 2.4 Execution Layer
- **Paper OMS** first (mirrors broker fills, no network dependency in tests); a thin **live
  adapter** replaces it behind the same interface.
- **Exit engine**: SL (structural), TP (R-multiple × entry), VWAP-trail, time-stop, CVD-kill.
  Exits are rules, not discretionary.
- **Risk coordinator**: session P&L, consecutive-loss cushion (risk shrinks after losses),
  per-trade capital fraction, daily stop.
- **LLM advisory (optional, throttled):**
  - **Entry**: journaled only — logs the model's read of `AuctionState`; never executes.
  - **Overseer**: on an open position, may tighten SL / partial / full-exit / add; **cooldown ≥ 15s**, bounded queue, drop-if-busy.
  - **Frequency budget**: entry on bar-close + event triggers (market-state flip, ±2σ cross,
    absorption/break) with a ≥60s floor; overseer ≥15s. Target ≤ 30 calls/hr/symbol.

### 2.5 Frontend — view-only
Renders `AuctionState` + `agentDecision` + positions. **No fabricated data, ever.**
- Chart: candles + VP histogram + VWAP bands + IB + entries/SL/TP.
- Decision card: direction, probability, timing, rationale (the real decision, once).
- Diagnostics behind one toggle.
The frontend is a consumer, never a producer — no strategy logic in the UI.

---

## 3. Data Flow (Event Order)

```
tick ──▶ aggregator (in-flight bar)        [every tick]
bar close ──▶ 1. VP       2. VWAP       3. order flow
              4. absorption  5. IB/location  6. Triple-A
              ──▶ AuctionState snapshot       [once per bar]
AuctionState ──▶ 5 gates ──▶ signal ──▶ paper/live OMS ──▶ exit engine
position/bar events ──▶ overseer (LLM) ──▶ adjusted exits
state ──▶ broadcast ──▶ frontend (throttled to ~4 Hz)
```

**Ordering guarantees:**
- Bar N+1's analysis is a pure function of bar N's close → **same `AuctionState` every
  consumer sees**, no recompute drift.
- Persist (trades, decisions) **before** broadcast — the UI never shows a trade the DB lacks.
- A single event bus with typed events (`BarClosed`, `SignalGenerated`, `PositionOpened`,
  `PositionClosed`, `OverseerAdjusted`) — every handler subscribes, no direct calls.

---

## 4. The "What We Chose" Decisions (with rationale)

| Decision | Choice | Why |
|---|---|---|
| Signal frame | **1-min candles** (not range bars) | Range bars need tick-level history that doesn't exist for freshly-screened options; candles have 500-bar history → backtestable from day one. The Triple-A edge reproduces on candles. |
| Data source | **underlying futures primary, option premium fallback** | VP/VWAP/absorption are cleanest on the underlying; option premium is noisy. Never mix. |
| VP VA method | **average-weighted CME two-row pairs** | Matches guide; average-weighting avoids boundary-pair bias. |
| LLM role | **advisory overlay** | Decision-critical path is 100% deterministic. LLM adds narrative + exit-tuning only. |
| Concurrency | **single-tick consumer, pure analysis** | Kills the entire class of race conditions by construction. |
| State | **immutable `AuctionState` per bar** | Testable, replayable, and the LLM/frontend read the same truth. |

---

## 5. How It Must Be Tested

### 5.1 Unit tests (per component, pure functions — fast, no I/O)

**Volume profile**
- Distribution: sum of bucket volumes == sum of candle volumes.
- POC: max-volume bucket; VWAP tie-break when equal.
- VA: 68–70% of total captured; **boundary-pair case** (POC near an edge — the 1-row vs
  2-row bias regression test: dense single row must win over sparse 2-row pair).
- Empty/single-candle profiles → safe defaults.

**VWAP**
- Volume-weighted mean correct on a synthetic 2-candle set.
- Std is volume-weighted (a 1000-vol candle at price X dominates a 1-vol candle far away).
- Proportional clamp bounds (0.1%–3% of price).

**Absorption**
- Volume > 1.5×20-bar avg AND range compressed → detected, correct side, strength ≤ 1.
- Volume spike with wide range → NOT absorption (noise guard).

**Triple-A state machine** (the most important unit test)
- Full walk: WAITING → ABSORBING → ACCUMULATING → AGGRESSION(SIGNAL) in the exact order.
- Can't skip phases (breakout with no prior absorption stays ABSORBING/ACCUMULATING).
- Reset to WAITING after signal.
- SHORT path symmetric (SELL absorption + price < VWAP).

**Gates**
- Each of the 5 gates fails its specific condition and passes a qualified context.
- Edge requirement: fresh absorption + matching VWAP breakout required for gate 4;
  stale absorption fails.
- Risk-reward: R:R < 1.5 rejected.

**Signal builder**
- Entry/SL/TP derived correctly; R:R ≥ minRR enforced.
- Structural SL (VAH/VAL/LVN), TP = R-multiple.

**Exit engine**
- SL hit → close with loss; TP hit → close with profit; VWAP trail; time-stop.
- Each exit records the correct close reason, exactly once (idempotent).

### 5.2 Determinism & replay tests (the system's superpower)
- **Golden-file replay:** capture a real session's ticks once; replay the exact sequence
  through the analysis layer and assert the `AuctionState` series matches the recorded golden
  file byte-for-byte. This catches any drift in VP/VWAP/absorption/Triple-A.
- **FIFO test:** 1,000 ticks through the tick bus → analysis sees them in exact order, one
  consumer only (asserts the single-consumer invariant).
- **Same-input-same-output:** running the same replay twice yields identical trades.

### 5.3 Integration tests
- **Bar-close pipeline:** synthetic ticks → bar closes → `AuctionState` → gates → signal →
  OMS fill → exit, end-to-end in-process (no broker, no network).
- **LLM throttle:** entry LLM fires ≤ 1 per 60s per symbol; overseer ≤ 1 per 15s; queue
  drops when full (assert call counts over a simulated 10-min window).
- **LLM-decision consistency:** build `AuctionState`, then a *newer* state arrives → the
  LLM prompt must still contain the *original* state (no hot-refresh of decision inputs).

### 5.4 Backtest / historical validation (the acceptance gate)
Per the guide §7.3, on ≥1 month of 1-min data per instrument:

| Metric | Target (paper) |
|---|---|
| Win rate | ≥ 55% |
| Avg R:R (winners) | ≥ 1.5 |
| Max drawdown | ≤ 10% of starting equity |
| Sharpe | ≥ 1.0 |
| Trades/session | 3–8 (selective, not scalping every bar) |

Critical: **the backtest runs the exact production `AuctionState` + gate + signal code**
(no test-only reimplementation). A golden-file replay of a backtested day must equal the
live-computed states for that day.

### 5.5 Live-validation protocol (paper → live)
1. **Paper week 1:** identical to live data feed, no fills risk. Compare paper trades to
   `AuctionState` — any trade that fires with no edge is a bug, not a loss.
2. **Paper week 2:** enable live OMS orders against paper risk; assert fill prices within
   spread of the signal entry.
3. **Live day 1 (1 position max):** watch one Triple-A setup execute cleanly end-to-end;
   SL/TP/exits all rule-driven.
4. **Live day 2+:** scale to the normal instrument set; keep the LLM overseer throttled.
5. **Rolling golden-file:** every live day appends its tick replay; the suite re-validates
   the previous day's states nightly.

### 5.6 What NOT to test (deliberately out of scope)
- The LLM's narrative quality (subjective) — only its *throttle*, *input-consistency*, and
  *output schema* are tested.
- Broker-side network glitches (mock the gateway at the interface).
- Frontend pixel-perfection — only that it renders the real `AuctionState` without phantom fields.

---

## 6. Suggested Module Layout

```
src/
├── ingestion/
│   ├── gateway/            # Dhan adapter (mockable interface)
│   ├── tick_bus.py         # single-consumer async queue
│   └── screener.py         # option contract selection
├── analysis/
│   ├── candles.py          # aggregator + Lee-Ready
│   ├── volume_profile.py   # VP + POC/VAH/VAL (CME avg-weighted)
│   ├── vwap.py             # VWAP + σ bands
│   ├── order_flow.py       # delta / CVD / prints
│   ├── absorption.py
│   ├── location.py         # IB + zone + LVN/HVN
│   └── triple_a.py         # state machine
│   └── auction_state.py    # immutable snapshot contract
├── decision/
│   ├── gates.py            # the 5 gates
│   ├── signal_builder.py
├── execution/
│   ├── oms.py              # paper/live behind one interface
│   ├── exits.py
│   └── risk.py
├── advisory/
│   ├── llm_entry.py        # journaled
│   ├── llm_overseer.py     # throttled, bounded
│   └── prompts.py          # one renderer, one contract
└── api/                    # WS broadcast + REST journal
tests/
├── unit/                   # per-component (5.1)
├── replay/                 # golden-file + FIFO + determinism (5.2)
├── integration/            # bar-close pipeline + LLM throttle (5.3)
├── backtest/               # historical acceptance gate (5.4)
└── fixtures/               # synthetic bars + recorded sessions
```

---

## 7. The Non-Negotiables (design invariants to never violate)

1. Analysis is **pure per closed bar** — no hidden cross-bar mutation.
2. **One tick consumer** — no locks anywhere in the hot path.
3. **Decisions on bar close** — not tick-by-tick.
4. **Same `AuctionState`** for gates, LLM, and UI.
5. **LLM never gates a trade**; it only annotates and tunes exits.
6. **No fabricated data** in any UI; no simulated indicators.
7. **Backtest == production code**; replay of a recorded day reproduces identical states.
8. **Delete over add** — if a component doesn't feed the edge, it doesn't ship.
