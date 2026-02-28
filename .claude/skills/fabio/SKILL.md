---
name: fabio
description: Fabio System Analysis & Infrastructure Audit — analyze codebase against Fabio Valentini's AMT methodology
user-invocable: true
---

# /fabio — Fabio System Analysis & Infrastructure Audit

Analyze the GlassyTrade AI codebase against Fabio Valentini's Auction Market Theory methodology. Find divergences between current implementation and the review findings. Suggest prioritized improvements.

## Instructions

You are an expert auditor for the GlassyTrade AI trading system. Use the comprehensive knowledge base below (extracted from Fabio Valentini's in-depth code review) to:

1. **Analyze** the current state of any file or module the user asks about
2. **Find divergences** between the current code and Fabio's recommendations
3. **Suggest improvements** with specific code locations and implementation guidance
4. **Track progress** on which gaps have been fixed vs remain open

When invoked without arguments, scan the key files and produce a divergence report.
When invoked with a specific topic (e.g., `/fabio exits`, `/fabio bubbles`), focus on that area.

---

## Architecture (CORRECT — maintain this)

- **LLM reads narrative → entries** (`llm_entry_handler.py` + `prompt_builder.py`)
- **TradeManager executes mechanically → exits** (`trade_manager.py` + `trade_lifecycle_handler.py`)
- LLM never touches exits. Exit is rule-based and deterministic. This is correct.
- Event-driven: InMemoryEventBus with TickReceived → AMT → LLM → Signal → Portfolio

### Philosophical Problem: Rules-First, Conviction-Second (INVERTED)

The system has **12 boolean rules** before/after the LLM's single moment of discretion at entry. On exits, 9 rules run every tick while the conviction-based overseer runs only every 10s. **This should be flipped:**

- Entry: LLM LEADS, rules GUARD (move pre-entry gates INTO the prompt as context, not hard blocks)
- Exit: Guardrails every tick (hard SL, max time, daily loss), overseer LEADS management (tighten/partial/add/exit)

---

## Scorecard — What's Correct (DO NOT BREAK)

| Component | File | Score | Notes |
|-----------|------|-------|-------|
| Gaussian-weighted VP + VWAP tiebreak | `amt_analyzer.py` | 9/10 | Better than most pro tools |
| CME two-row VA calculation | `amt_analyzer.py` | 10/10 | Textbook correct |
| 2.5σ aggression filter + 15% delta | `amt_analyzer.py` | 9/10 | Strong, correct |
| CVD tracker with divergence | `cvd_tracker.py` | 8/10 | Missing early BE usage |
| Profile shape P/b/D/B | `profile_classifier.py` | 9/10 | Bimodal detection is rare/good |
| 5-phase NSE session structure | `session_context.py` | 10/10 | Perfect mapping |
| Acceptance/Rejection engine | `amt_analyzer.py` | 9/10 | Time+volume+wick |
| Bimodal override (B shape → BALANCED) | `amt_analyzer.py` | Correct | Prevents rotation misread |
| Break detection (initiative/responsive/absorption) | `amt_analyzer.py` | 9/10 | Comprehensive |
| OI analyzer (India edge) | `oi_analyzer.py` | 9/10 | Keep — NSE-specific advantage |
| Confirmation bundle 2/3 | `entry_gate.py` | 8/10 | Good NSE proxy |
| Failed auction re-entry block (Rule 11) | `regime_detector.py` | 10/10 | Exact Fabio rule |
| Runner 75/25 (trend) / 100% exit (mean-rev) | `trade_manager.py` | 9/10 | Correct differentiation |
| Daily loss limit (3 stops) | `trade_manager.py` | 10/10 | Correct |
| R:R filter ≥ 1:2 | `trade_manager.py` | 10/10 | Correct |
| 7-section entry prompt | `prompt_builder.py` | 9/10 | Comprehensive narrative |
| Episodic memory (last 5 trades) | `llm_entry_handler.py` | 9/10 | Smart context |
| Option gates (IV/delta/theta) | `entry_gate.py` | 8/10 | Correct for scalping |
| Incremental VP (O(buckets) per tick) | `amt_analyzer.py` | Smart | Performance optimization |
| LVN detection (local min + smoothing + spacing) | `amt_analyzer.py` | 8/10 | Clean implementation |

---

## Critical Gaps — Prioritized Fix List

### Gap #1: System Philosophy — Rule-Based, Not Conviction-Based (Score: 4/10)
**Impact: CRITICAL — limits the LLM's value**

Current: 12 rules → LLM → more rules. LLM is step 6 of 14.
Fix: Move pre-entry gates INTO prompt as context. Let LLM decide. Only check guardrails AFTER.
- `llm_entry_handler.py`: Instead of `if not session_info.allow_entry: return`, tell the LLM "Session: Midday, only mean-reversion valid"
- Replace `grade_score` checklist with trusting LLM conviction
- `config.py`: Change `LLM_INSTRUCTION` from "Analyze" → "You are READING the auction, not predicting. Read narrative. If story is clear and all three align, state conviction. If no setup, STAY FLAT."
- Consider temperature 0.4-0.5 for entries (pick up narrative subtleties), 0.3 for overseer

### Gap #2: Volume Bubble Systems Disconnected (Score: 2/10 integration)
**Impact: HIGH — ignoring best signal. Three detection systems, zero integration.**

Three systems exist:
1. `AggressivePrint` (2.5σ candle-level) → goes to LLM as text ✅
2. `FootprintAnalyzer` (diagonal imbalance + stacked detection) → frontend ONLY ❌
3. `TickFootprintAccumulator` (tick-level classification) → ORPHANED, nothing calls it ❌

Stacked imbalances (3+ consecutive 3:1 ratio levels) = highest conviction signal. Currently rendered on chart and ignored by trading logic.

Fix:
- Wire `TickFootprintAccumulator` into `TradingSessionService`
- Create `BubbleLevel` structural levels from stacked imbalances
- Feed to `entry_gate.py` `near_level` check
- Feed to `TradeManager` (opposing bubble = TIGHTEN immediately)
- Feed to LLM: `"STACKED BUY IMBALANCE at 24750-24780 (3 levels, 3:1+ ratio). Structural support."`

Missing bubble features from Fabio's live trading:
- **Absorption detection**: big SELL aggression but price doesn't drop = hidden buyer absorption = LONG signal
- **Follow-through analysis**: after big bubble, does price continue? Yes = commitment, No = trap
- **Proportional conviction**: 100-contract bubble ≠ 30-contract bubble, weight differently
- **Contested zone**: both BUY and SELL bubbles in same window = FLAT, don't trade
- **Squeeze detection**: trapped sellers forced to cover = your entry fuel (see Gap #6)

### Gap #3: Overseer Has Less Context Than Entry Handler (Score: 5/10)
**Impact: HIGH — conviction-based exits with incomplete data**

Missing from `build_overseer_prompt()`:
- Session phase context
- Profile shape (P/b/D/B)
- OI data (PCR, sentiment)
- LVN play signal
- Stacked imbalances from footprint

Fix: Add all missing fields to overseer prompt. Overseer should have AT LEAST same data as entry.
Also: reduce overseer polling from 10s → 3-5s.

### Gap #4: No Intraday Compounding / Cushion System (Score: 0/10)
**Impact: HIGH — doubles returns on good days**

Current: static `stop_loss_pct = 0.005` always. No session P&L tracking.

Fabio's system:
| Phase | Condition | Risk |
|-------|-----------|------|
| Conservative | First 1-2 trades | 0.25% |
| Cushion Built | session_pnl > 0 | 0.35% + 20% of session profit |
| Momentum Day | 2+ consecutive wins | 0.40% + can add 1-2 lots |
| Cap | Always | Never > 0.50%, never > 30% of session profit |
| 1st loss | | Stay current |
| 2nd consecutive loss | | Back to 0.25% |
| 3rd consecutive loss | | STOP (already implemented: MAX_DAILY_LOSSES=3) |
| Max daily loss | | 2% of account |

### Gap #5: Breakeven Too Slow (Score: 4/10)
**Impact: HIGH — reduces avg loss by ~30%**

Current: BE at 50% of TP distance (`partial_tp_pct = 0.50`).
Fabio: BE at 1R (= SL distance) OR when CVD confirms within 1 candle — whichever FIRST.

Fix in `trade_manager.py`:
- Add CVD-based BE: if CVD slope strongly confirms direction after entry → immediate BE
- Add 1R-based BE: if unrealized ≥ SL distance → BE
- Keep 50% partial TP as separate action

### Gap #6: No Second Drive Enforcement (Score: 0/10)
**Impact: HIGH — reduces fakeout losses 30%+**

"Don't take the first drive because you can get tapped in a fake out."

Current: no differentiation between first-touch and return-visit entries. A first-touch scores identically to second-drive with same confirmations.

Fix:
1. Track all levels where price touched (reached or exceeded)
2. When price returns after moving away → mark "second drive"
3. Add to grading: second-drive = +2 to grade_score
4. Add to LLM prompt: "This is the SECOND approach to this level"

### Gap #7: Squeeze Detection Not Implemented (Score: 0/10)
**Impact: HIGH R:R — Fabio's primary live setup**

Algorithm from live trading:
1. Detect big sell/buy bubbles at a level (trapped participants)
2. Absorption: aggression with zero price impact
3. Price recovers above/below the bubble cluster
4. Breakout = squeeze (forced liquidation = fuel)
5. Enter on first pullback to LVN after squeeze breakout
6. SL below absorbed level, target next distribution

Your `regime_detector.py` BLOCKS re-entry at failed levels. Fabio USES the failure as fuel. Flip the logic: failed sellers' forced exit IS the entry catalyst.

### Gap #8: Prior Session Data Not Flowing (Score: 0/10)
**Impact: MEDIUM — pre-session narrative empty**

`amt_analyzer.py` line 1227-1231: `prior_poc=0.0, prior_vah=0.0, prior_val=0.0, gap_type="", opening_bias=""`

Functions exist (`classify_gap()`, `opening_inventory_bias()`) but aren't called. Fix: persist POC/VAH/VAL at session close, load at session open.

### Gap #9: VWAP Bands Not Used for Bias/Trailing (Score: partial)
**Impact: MEDIUM — filters 20% of bad entries**

VWAP + σ bands computed in `amt_analyzer.py` but only used for POC tiebreak and SL reference.

Missing:
- **Bias filter**: price below VWAP = don't go long (or warn)
- **Overextension**: price at VWAP±2σ = tighten stops / take partials
- **Trailing**: after +1.5R, trail to nearest VWAP band (adaptive to market conditions)

### Gap #10: Aggressive Prints Don't Create Structural Levels (Score: 0/10)
When a massive print occurs at a price, that price IS support/resistance for future reference. Currently prints are only used for confirmation + SL placement.

### Gap #11: Market Structure Classifier Too Conservative (Score: 7/10)
TRANSITION state: 3 dwell + 5 cooldown = 8 candles = 40 min delay on 5-min chart.
Bypass at 85 confidence rarely fires.
Fix: reduce `_DWELL_TICKS` to 1, `_COOLDOWN_TICKS` to 2, or lower `_BYPASS_CONFIDENCE` to 70.

### Gap #12: Static Time Stops
Current: 30min balanced, 2hr trending. Should be session-aware:
- Morning: 20min balanced, 45min trend
- Afternoon: 15min balanced, 30min trend
- Expiry day: 10min flat

### Gap #13: SL Placement — Inside vs Outside Cluster
Current: SL at `best_print - buffer` (outside). Fabio: 1-2 ticks INSIDE the cluster to exit before cascade acceleration.

### Gap #14: Trailing Stop Issues
- Activates too late (50% of TP → should be 1R)
- 30% giveback too loose for options with theta
- No VWAP-based trailing

### Gap #15: No Spread Blowout Detection During Trade
Entry checks spread. But mid-trade spread blowout (>3% of premium) = liquidity crisis → exit immediately.

---

## Audit Checklist

When running an audit, check these files and verify current state against expected:

```
backend/app/config.py                          → LLM_INSTRUCTION, temperature
backend/app/application/handlers/llm_entry_handler.py → grade_score logic, pre-entry gates, episodic memory
backend/app/application/handlers/llm_overseer_handler.py → polling interval, prompt completeness
backend/app/domain/fabio_ai/services/amt_analyzer.py → VP, displacement, A/R, aggressive prints, prior session fields
backend/app/domain/fabio_ai/services/market_structure_classifier.py → hysteresis params
backend/app/domain/fabio_ai/services/cvd_tracker.py → slope, divergence
backend/app/domain/fabio_ai/services/footprint_analyzer.py → stacked imbalances, TickFootprintAccumulator integration
backend/app/domain/fabio_ai/services/profile_classifier.py → P/b/D/B shapes
backend/app/domain/fabio_ai/services/oi_analyzer.py → OI walls, PCR
backend/app/domain/fabio_ai/entry_gate.py → three_align, confirmation_bundle, SL placement, VWAP bias
backend/app/domain/fabio_ai/prompt_builder.py → 7-section prompt, overseer prompt
backend/app/domain/fabio_ai/trade_manager.py → BE logic, trailing, time stops, cushion system
backend/app/domain/fabio_ai/trade_lifecycle_handler.py → exit flow priority
backend/app/domain/fabio_ai/regime_detector.py → squeeze vs re-entry block
backend/app/domain/fabio_ai/session_context.py → 5-phase NSE, MCX sessions, gap classification
```

## How to Run an Audit

1. Read each file in the checklist above
2. For each Gap (#1-#15), check if it's been addressed
3. Produce a report:
   - ✅ Fixed gaps
   - ⚠️ Partially fixed (with what remains)
   - ❌ Still open
   - 🔄 New divergences found
4. Suggest the next highest-impact fix to implement

## Overall Scores (Baseline from Review)

```
Reading the Market:    90%  — VP, CVD, OI, footprint detection
Volume Bubble Usage:   25%  — detected but not integrated
Entry Precision:       75%  — good gates, missing second drive + VWAP
Exit Execution:        55%  — BE too slow, overseer underinformed
Position Management:   40%  — rules dominate, conviction secondary
Risk Management:       35%  — static risk, no compounding
System Philosophy:     35%  — rule-based, not conviction-based
LLM Prompts:           70%  — entry strong, overseer weak
Architecture:          95%  — the bones are right
OVERALL:               60%  → Target after fixes: 90%+
```
