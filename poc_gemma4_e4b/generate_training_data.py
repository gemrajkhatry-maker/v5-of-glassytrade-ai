"""
Enhanced Training Data Generator — Gemma-4-E4B-it Fine-Tuning
for GlassyTrade AMT Options Scalper System

Output format per example:
  - Input:  Rich AMT market narrative (session + state + location + aggression)
  - Output: <think>Fabio-style reasoning chain</think> + JSON
             {"direction": "LONG|SHORT|FLAT", "confidence": "High|Medium|Low",
              "rationale": "concise justification"}

Fabio Rules extracted from NoteGPT transcript + existing playbook:
  1. Read auction state first (balanced/imbalanced) — determines the model
  2. Location = VAH/VAL/LVN/POC — where to enter
  3. Aggression (bubbles/delta/CVD) = trigger confirmation
  4. SECOND DRIVE > First drive in every scenario
  5. CVD divergence = ABORT or don't enter
  6. VWAP bias filter — long below VWAP = FLAT; short above VWAP = FLAT
  7. Session rules: opening noise (skip), midday (downgrade), close protection (exit)
  8. Risk rules: 3 losses = stop, 2 losses = reduce, cushion = scale up
  9. Squeeze = trapped traders closing → fuel for continuation
  10. No follow-through = scratch immediately
  11. Don't marry bias — if invalidation levels break, flip
  12. Stop loss INSIDE the aggressive print cluster (below/above the big bubble)
  13. Target = previous balance area POC (70% probability mean reversion)
  14. Round numbers (22000, 48000, 6000) = expect pause/reversal
"""

import json
import random
import os

random.seed(42)

OUTPUT_FILE = "poc_gemma4_e4b/data/train.jsonl"
VAL_FILE    = "poc_gemma4_e4b/data/valid.jsonl"

SYSTEM = (
    "You are an expert AMT scalping analyst using Fabio Valentini's Auction Market Theory. "
    "You READ the auction — you do NOT predict. "
    "MANDATORY REASONING STRUCTURE (Inside <think> tags): "
    "1. SESSION CHECK: [Window] -> Bias [Bullish/Bearish/Neutral] "
    "2. RISK CHECK: [P&L/Rule Status] -> Permit [Yes/No] "
    "3. STRUCTURE CHECK: [State/Location] -> Signal [Confirmed/No] "
    "4. AGGRESSION CHECK: [CVD/Delta/Bubbles] -> Trigger [Confirmed/No] "
    "5. FINAL LOGIC: [Narrative summary] "
    "Then respond with a JSON object only. "
    "JSON format: {\"direction\": \"LONG|SHORT|FLAT\", \"confidence\": \"High|Medium|Low\", \"rationale\": \"brief reason\"}"
)

# ═══════════════════════════════════════════════════════════════════
# SCENARIO TEMPLATES  (user prompt → assistant response)
# Each entry: (scenario_text, direction, confidence, think_chain, rationale_text)
# ═══════════════════════════════════════════════════════════════════

def _make_example(user: str, direction: str, confidence: str,
                   think: str, rationale: str) -> dict:
    """Format a single ChatML training example."""
    # Prepend the structured checklist to any logic provided
    assistant = (
        f"<think>\n{think}\n</think>\n"
        f'{{"direction": "{direction}", "confidence": "{confidence}", '
        f'"rationale": "{rationale}"}}'
    )
    return {
        "messages": [
            {"role": "system",  "content": SYSTEM},
            {"role": "user",    "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


# ═══════════════════════════════════════════════════════════════════
# SECTION 1: TRIPLE-A SETUP (All 3 must align)
# ═══════════════════════════════════════════════════════════════════

TRIPLE_A_EXAMPLES = [

    _make_example(
        user=(
            "SESSION: NSE Primary Window (09:30-11:30). Session favors: MEAN REVERSION. "
            "MARKET STATE: BALANCED. Active model: MEAN REVERSION. "
            "Price at VAL 22100. Aggressive selling -900 Delta but price NOT moving down — iceberg buyers absorbing. "
            "D-shaped profile. Volume bubbles: 2.5σ buy at 22100 (3000 contracts). "
            "CVD Slope: +650. Price above VWAP (22050). ✅ SECOND DRIVE: High probability re-test setup."
        ),
        direction="LONG", confidence="High",
        think=(
            "1. SESSION CHECK: Primary Window (09:30-11:30). Price (22100) > VWAP (22050) -> Bias Bullish.\n"
            "2. RISK CHECK: No losses reported -> Permit Yes.\n"
            "3. STRUCTURE CHECK: Balanced State at VAL extreme -> Signal Confirmed (Mean Reversion).\n"
            "4. AGGRESSION CHECK: -900 Delta absorbed + 2.5σ buy bubble + CVD +650 -> Trigger Confirmed.\n"
            "5. FINAL LOGIC: AAA setup at VAL with institutional absorption. Second drive confirmed. Fabio: 'Location + Aggression = 100 probability.' -> LONG."
        ),
        rationale="AAA setup: balanced at VAL, iceberg absorption, CVD +650, second drive. All three align → LONG."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. Active model: MEAN REVERSION. "
            "Price at VAL 22100. No volume bubbles. Delta neutral (+12). No aggressive prints detected. "
            "D-shaped profile. CVD slope: +18 (flat). Price at VWAP 22100. ⚠️ FIRST DRIVE."
        ),
        direction="FLAT", confidence="High",
        think=(
            "1. SESSION CHECK: Primary Window. Price at VWAP -> Bias Neutral.\n"
            "2. RISK CHECK: No constraints -> Permit Yes.\n"
            "3. STRUCTURE CHECK: Balanced State at VAL extreme -> Signal Confirmed.\n"
            "4. AGGRESSION CHECK: No bubbles, Delta neutral, CVD flat -> Trigger NOT Confirmed.\n"
            "5. FINAL LOGIC: Fabio absolute rule: All three (State, Location, Aggression) must align. Missing aggression = NO trade. -> FLAT."
        ),
        rationale="Missing aggression trigger (no bubbles, neutral CVD). Location correct but incomplete setup → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: UNCLEAR — mixed overlap, partial acceptance. "
            "Price near POC 22300. Delta choppy ±200. Some volume but no clear direction. "
            "CVD slope: -35. D-shaped profile. ⚠️ FIRST DRIVE."
        ),
        direction="FLAT", confidence="High",
        think=(
            "Step 1 - AGGRESSION: CVD slope -35 = weak bearish but not significant. Delta choppy. "
            "No clear directional pressure. "
            "Step 2 - STRUCTURE: State is UNCLEAR. Market state is Step 1 of the model. "
            "Fabio: 'You need to understand if you are in balanced or imbalanced.' Without clear state, model cannot activate. "
            "Price at POC = FAIR VALUE. Fabio says: 'Price near POC — WAIT for bias.' "
            "No clear setup. Wait for market to declare direction. "
            "Decision: FLAT."
        ),
        rationale="Market state unclear, price at POC (fair value), no decisive aggression → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. "
            "Price at VAH 22500. Aggressive buying +1500 Delta but price NOT moving up. "
            "P-Shape profile forming. CVD divergence: BEARISH — price rising, buying pressure declining. "
            "Passive sellers absorbing all buy pressure. Price above VWAP+1σ. ✅ SECOND DRIVE at resistance."
        ),
        direction="SHORT", confidence="High",
        think=(
            "Step 1 - AGGRESSION: Delta +1500 aggressive buying BUT price not moving up = sellers ABSORBING. "
            "CVD BEARISH DIVERGENCE = price up but true buyer pressure declining. Hidden supply. "
            "This is the AAA pattern REVERSED: sellers are the dominant party despite visible buy aggression. "
            "Step 2 - STRUCTURE: P-shape profile = sellers distributing. Fabio: P-shape = DO NOT GO LONG. "
            "At VAH = structural resistance. Perfect SHORT location. "
            "Price above VWAP+1σ = OVEREXTENDED. Reversal probability high. "
            "Step 3 - SECOND DRIVE: Higher conviction for shorts. "
            "Decision: SHORT with High confidence. This is the AAA short at VAH."
        ),
        rationale="P-shape at VAH, buyers absorbed by passive sellers, bearish CVD divergence, price overextended → SHORT."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 2: SECOND DRIVE vs FIRST TOUCH
# ═══════════════════════════════════════════════════════════════════

DRIVE_EXAMPLES = [

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. "
            "Price returned to VAL 22100 for SECOND time after initial rejection. "
            "Buyers stepping in: Delta +850, Volume 3200 contracts. "
            "Volume bubble: 2.5σ buy at 22100. CVD slope: +420. Price above VWAP. "
            "✅ SECOND DRIVE. D-shape profile."
        ),
        direction="LONG", confidence="High",
        think=(
            "Step 1 - AGGRESSION: Delta +850, bubble 3200 contracts, CVD +420 = real buyers present. "
            "Significant institutional pressure. "
            "Step 2 - STRUCTURE: Balanced at VAL = mean reversion model active. "
            "VAL is the exact entry zone for longs. D-shape = balanced rotation, VAL is the extreme. "
            "Step 3 - SECOND DRIVE: Fabio: 'Second drive > first drive. Wait for re-test.' "
            "Market returned after first rejection = market VALIDATED this level. Higher probability. "
            "All conditions met: aggression + location + state + second drive. "
            "Decision: LONG with High confidence."
        ),
        rationale="Second drive at VAL with bubble confirmation, CVD +420, D-shape → LONG High."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. "
            "Price arriving at VAL 22100 for the FIRST time today. Some buying interest. "
            "Delta +420, Volume 1500 contracts. No bubble (below 2.5σ threshold). "
            "CVD slope: +85. Price at VWAP. ⚠️ FIRST DRIVE."
        ),
        direction="FLAT", confidence="High",
        think=(
            "Step 1 - AGGRESSION: Delta +420, CVD +85 = light buying. Volume 1500 = below institutional threshold. "
            "No volume bubble = no big participant confirmation. "
            "Step 2 - STRUCTURE: Correct location (VAL) but first touch. "
            "Step 3 - FIRST TOUCH: Fabio: 'I wait for the second drive. First breakout can be fake out.' "
            "Risk of first touch = only 40-50% win rate vs 70%+ on second drive. "
            "No bubble means no confirmation signal. Wait. "
            "Decision: FLAT. Monitor for second drive setup."
        ),
        rationale="First touch at VAL, no bubble confirmation, CVD weak → FLAT. Wait for second drive."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: IMBALANCED. Active model: TREND CONTINUATION. "
            "Displacement leg broke above VAH 22500. Acceptance outside value confirmed. "
            "Price pulled back to LVN at 22350. "
            "Aggressive buyers at LVN: Delta +1200, Volume 4000 contracts. Bubble: 2.8σ buy. "
            "CVD slope: +780. Price above VWAP. ✅ SECOND DRIVE."
        ),
        direction="LONG", confidence="High",
        think=(
            "Step 1 - AGGRESSION: Delta +1200 + bubble 4000 contracts + CVD +780 = STRONG institutional buy pressure. "
            "Very significant. Big participants confirmed. "
            "Step 2 - STRUCTURE: Imbalanced market = TREND CONTINUATION model active. "
            "LVN pullback = textbook Fabio entry: displacement → acceptance → LVN retest → continuation. "
            "This is the trend model: out of balance, find LVN, wait for aggression. "
            "Step 3 - SECOND DRIVE: Pullback to LVN after displacement = second drive pattern. "
            "High probability continuation. Target = next balance area / prior POC higher. "
            "Decision: LONG with High confidence."
        ),
        rationale="Imbalanced market, LVN pullback, bubble +4000 at LVN, CVD +780, second drive → LONG High."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 3: MEAN REVERSION (Failed Breakout)
# ═══════════════════════════════════════════════════════════════════

MEAN_REV_EXAMPLES = [

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. Active model: MEAN REVERSION. "
            "Price broke above VAH 22500 but FAILED to hold — price snapped back inside value. "
            "Now at reclaim-leg LVN 22400. Sellers aggressive: Delta -820, Bubble: 2.6σ sell. "
            "CVD slope: -560. P-shape profile forming. ✅ SECOND DRIVE."
        ),
        direction="SHORT", confidence="High",
        think=(
            "Step 1 - AGGRESSION: Delta -820 + sell bubble 2.6σ + CVD -560 = strong sellers. "
            "Significant institutional selling pressure. "
            "Step 2 - STRUCTURE: Failed breakout above VAH = market REJECTED imbalanced state. "
            "Price inside value = mean reversion model. P-shape forming = sellers in control. "
            "Fabio: failed auction is the highest probability setup in balanced mode. "
            "LVN 22400 = entry zone for shorts. Target = POC inside value. "
            "Step 3 - SECOND DRIVE: Price tested outside VA, failed, came back. "
            "This is the second drive for shorts. "
            "Decision: SHORT with High confidence."
        ),
        rationale="Failed breakout above VAH, P-shape, sell bubble at LVN, CVD -560, second drive → SHORT High."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. "
            "Price broke below VAL 47200 but FAILED — price recovered above VAL within 2 candles. "
            "Now at post-rejection LVN 47350. Buyers: Delta +950, Bubble: 2.7σ buy. "
            "CVD slope: +680. b-shape profile. ✅ SECOND DRIVE at LVN."
        ),
        direction="LONG", confidence="High",
        think=(
            "Step 1 - AGGRESSION: Delta +950 + buy bubble 2.7σ + CVD +680 = strong institutional buying. "
            "Step 2 - STRUCTURE: Failed breakout BELOW VAL = market rejected breakdown. "
            "b-shape = buyers absorbing. Fabio: b-shape = DO NOT GO SHORT. "
            "Price recovered inside value. Mean reversion model: failed breakdown → long from LVN toward POC. "
            "Step 3 - SECOND DRIVE: Failed breakdown and now re-testing from inside. "
            "Decision: LONG High confidence."
        ),
        rationale="Failed breakdown below VAL, b-shape, buy bubble at LVN, CVD +680, second drive → LONG High."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 4: SQUEEZE SETUPS (Trapped traders = fuel)
# ═══════════════════════════════════════════════════════════════════

SQUEEZE_EXAMPLES = [

    _make_example(
        user=(
            "MARKET STATE: IMBALANCED. Price breaking through 22500 where previous shorts were stopped out. "
            "Short covering accelerating — forced liquidation. "
            "Delta: +2500. Volume: 7000 contracts. CVD slope: +1200 (strongly positive). "
            "Their closing IS the fuel. ✅ SECOND DRIVE. Price above VWAP."
        ),
        direction="LONG", confidence="High",
        think=(
            "Step 1 - AGGRESSION: Delta +2500 + volume 7000 + CVD +1200 = EXTREME buy pressure. "
            "Fabio: when shorts are forced to close, THEIR buying creates more momentum = squeeze fuel. "
            "Step 2 - STRUCTURE: Imbalanced. Breaking through prior stop level = displacement confirmed. "
            "Above VWAP = bullish bias. "
            "Step 3 - SQUEEZE PATTERN: Fabio: 'Short covering accelerating → the covering IS the fuel.' "
            "This is the most powerful continuation setup. Stop loss protected by the cluster of buy orders. "
            "Decision: LONG High. Trail stop below big buy bubbles."
        ),
        rationale="Short squeeze at 22500, forced covering fuel, CVD +1200, delta +2500 → LONG High."
    ),

    _make_example(
        user=(
            "MARKET STATE: IMBALANCED. Price crashing through VAL 47000 where previous longs were stopped out. "
            "Long liquidation accelerating. Delta: -2000. Volume: 6000 contracts. "
            "CVD slope: -950 (strongly negative) — forced liquidation. ✅ SECOND DRIVE. "
            "Price well below VWAP."
        ),
        direction="SHORT", confidence="High",
        think=(
            "Step 1 - AGGRESSION: Delta -2000 + volume 6000 + CVD -950 = POWERFUL sell pressure. "
            "Long liquidation = trapped longs closing = more selling = squeeze fuel downward. "
            "Step 2 - STRUCTURE: Imbalanced, breaking below VAL. Below VWAP = bearish bias confirmed. "
            "Target = prior balance area POC below. "
            "Step 3 - SQUEEZE: Exact mirror of the long squeeze. Longs are fuel for sellers. "
            "Decision: SHORT High confidence."
        ),
        rationale="Long squeeze fuel at VAL, longs forced to close, CVD -950, delta -2000 → SHORT High."
    ),

    _make_example(
        user=(
            "MARKET STATE: BALANCED. Price at VAL 22100. Aggressive sellers: Delta -1500, Volume 5000. "
            "BUT price is NOT moving down — buyers absorbing every sell print. "
            "CVD slope: +320. D-shape. These sellers will eventually need to close. ✅ SECOND DRIVE."
        ),
        direction="LONG", confidence="High",
        think=(
            "Step 1 - AGGRESSION: On the surface looks bearish (delta -1500, big volume). "
            "BUT CVD +320 = despite all selling, NET pressure is bullish. Price not falling = absorption. "
            "Fabio: 'Sellers no follow-through = sellers are punching a wall.' "
            "These trapped sellers WILL need to close → their buying = fuel for longs. "
            "Step 2 - STRUCTURE: Balanced at VAL = perfect mean reversion location. D-shape. "
            "Step 3 - SECOND DRIVE: Tested twice, sellers can't push it down. Setup building. "
            "Decision: LONG High. Sellers will be squeezed upward."
        ),
        rationale="Sellers absorbed at VAL, price unmoved despite -1500 delta, CVD positive, incoming squeeze → LONG High."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 5: CVD / VWAP FILTERS
# ═══════════════════════════════════════════════════════════════════

FILTER_EXAMPLES = [

    _make_example(
        user=(
            "SESSION: NSE Primary Window. Entered LONG at 22100. "
            "CVD slope now strongly positive: +1200. Market confirming direction. "
            "Aggressive buyers still pushing. Price +45 in favor."
        ),
        direction="FLAT", confidence="High",
        think=(
            "Context: already IN a long position. This is a trade management signal. "
            "CVD +1200 = market has confidently shown its hand. "
            "Fabio: 'When CVD confirms entry direction, move to breakeven IMMEDIATELY.' "
            "The winning trade = protect it. Breakeven = zero risk. "
            "This is not an entry signal = FLAT (no new entry). "
            "Action: move SL to entry price. This frees mental capital and protects P&L."
        ),
        rationale="CVD confirms long direction strongly. Fabio rule: move to breakeven immediately → FLAT (already in, protect it)."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. "
            "Long signal present at VAL 22050. BUT price is BELOW VWAP. VWAP at 22100. "
            "Price at 21980 = 120 points below VWAP. Bearish VWAP bias. D-shape."
        ),
        direction="FLAT", confidence="High",
        think=(
            "1. SESSION CHECK: Primary Window. Price (21980) < VWAP (22100) -> Bias Bearish (Long Forbidden).\n"
            "2. RISK CHECK: No constraints -> Permit Yes.\n"
            "3. STRUCTURE CHECK: Balanced State at VAL extreme -> Signal Confirmed (Location OK).\n"
            "4. AGGRESSION CHECK: Aggression present but disregarded due to session bias -> Trigger N/A.\n"
            "5. FINAL LOGIC: Fabio absolute rule: 'Don't long below VWAP.' Bearish session bias overrides the long structural signal at VAL. Expectation of value is negative. -> FLAT."
        ),
        rationale="Long signal but price -120 below VWAP = bearish bias. Fabio VWAP filter: don't long below VWAP → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. "
            "Short signal present at VAH 22500. BUT price is ABOVE VWAP. VWAP at 22300. "
            "Price at 22550 = 250 points above VWAP. Bullish VWAP bias. D-shape."
        ),
        direction="FLAT", confidence="High",
        think=(
            "1. SESSION CHECK: Primary Window. Price (22550) > VWAP (22300) -> Bias Bullish (Short Forbidden).\n"
            "2. RISK CHECK: No constraints -> Permit Yes.\n"
            "3. STRUCTURE CHECK: Balanced State at VAH extreme -> Signal Confirmed (Location OK).\n"
            "4. AGGRESSION CHECK: Aggression present but disregarded due to counter-flow bias -> Trigger N/A.\n"
            "5. FINAL LOGIC: Fabio rule #1: 'No counter-flow trades.' Shorting against a strong bullish VWAP bias is forbidden. buyers have session control. -> FLAT."
        ),
        rationale="Short signal but price +250 above VWAP = bullish bias. Fabio: don't short above VWAP, no counter-flow → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. "
            "Long signal at VAL 22100. Price ABOVE VWAP (22050). VWAP at 22000. "
            "CVD slope: +380. Delta +600. D-shape. Volume bubble: 2.5σ buy at VAL. ✅ SECOND DRIVE."
        ),
        direction="LONG", confidence="High",
        think=(
            "Step 1 - AGGRESSION: CVD +380, delta +600, bubble at VAL = confirmed buy aggression. "
            "Step 2 - STRUCTURE: Balanced at VAL. D-shape. VWAP check: price ABOVE VWAP = BULLISH. "
            "Price above VWAP = buyers have session control. Long direction aligns with session bias. "
            "Step 3 - SECOND DRIVE: Higher conviction. "
            "All elements: state (balanced at VAL) + location (VAL) + aggression (bubble) + VWAP (bullish) + second drive. "
            "Decision: LONG High."
        ),
        rationale="Long at VAL, price above VWAP (bullish bias confirmed), bubble, CVD +380, second drive → LONG High."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 6: RISK MANAGEMENT RULES
# ═══════════════════════════════════════════════════════════════════

RISK_EXAMPLES = [

    _make_example(
        user=(
            "SESSION: NSE Primary Window. Session P&L: -₹4,200 (3 consecutive losses today). "
            "A-grade signal firing: long at VAL 22100 with bubble confirmation. "
            "D-shape profile. CVD slope: +450. ✅ SECOND DRIVE."
        ),
        direction="FLAT", confidence="High",
        think=(
            "1. SESSION CHECK: Primary Window. Bias Bullish (Price above VWAP).\n"
            "2. RISK CHECK: 3 consecutive losses -> STOP TRADING (Permit NO).\n"
            "3. STRUCTURE CHECK: Balanced at VAL extreme -> Signal Confirmed (A-grade Location).\n"
            "4. AGGRESSION CHECK: Bubble + CVD +450 + Second Drive -> Trigger Confirmed.\n"
            "5. FINAL LOGIC: Risk rule veto: 'Three losses and walk away. No exceptions.' Even with an A+ signal, the session is over. Resilience is depleted, revenge trading risk is high. -> FLAT."
        ),
        rationale="3 consecutive losses = walk away rule triggered. Fabio: 3 losses → session done regardless of signal quality → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. Session P&L: +₹5,800 (strong cushion built). "
            "Price trending strongly upward with momentum. "
            "A-grade momentum signal at LVN pullback. CVD slope: +720. ✅ SECOND DRIVE. "
            "Price above VWAP. Delta: +1100."
        ),
        direction="LONG", confidence="High",
        think=(
            "RISK MANAGEMENT: +₹5800 cushion = 'house money' mode. "
            "Fabio: 'When cushion is built, you can take this kind of trade with risk from session profit.' "
            "This aligns with Fabio's world cup approach: 'building profit for the day, building profit, then risk more.' "
            "Step 1 - AGGRESSION: CVD +720, delta +1100 = strong institutional momentum. "
            "Step 2 - STRUCTURE: Imbalanced trend continuation, LVN pullback = textbook entry. "
            "Step 3 - CUSHION: Risk from session profit = acceptable. Can scale up. "
            "Decision: LONG High. This is a prime A-grade setup WITH house money available."
        ),
        rationale="Strong cushion +₹5800, A-grade LVN pullback, CVD +720, second drive. House money mode → LONG High."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. Session P&L: -₹2,800 (2 consecutive losses). "
            "B-grade setup at VAL 22100. D-shape profile. CVD slope: +82 (weak). "
            "Delta: +180. ⚠️ FIRST DRIVE. Price at VWAP."
        ),
        direction="FLAT", confidence="High",
        think=(
            "RISK RULE: 2 consecutive losses. Fabio: 'After 2 losses, reduce to minimum size.' "
            "More importantly: this is a B-grade setup. CVD +82 = WEAK. Only first drive. "
            "When you have 2 losses, you need A+ setups. B-grade after 2 losses = recipe for 3rd loss. "
            "Fabio: 'If model is not working for the day, the market is telling you something. Listen.' "
            "No bubble, weak CVD, first drive, at VWAP (not at a structural extreme). "
            "Multiple weaknesses. The edge is not there. "
            "Decision: FLAT. Wait for clear A-grade setup or end of session."
        ),
        rationale="2 losses + B-grade setup + weak CVD + first drive. After 2 losses need A+ setups only → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. Session P&L: -₹1,200 (1 loss). "
            "A-grade signal: SECOND DRIVE at VAL, Volume bubble 2.8σ buy (4500 contracts). "
            "CVD slope: +850. Price above VWAP. D-shape. Delta: +1300."
        ),
        direction="LONG", confidence="High",
        think=(
            "RISK RULE: Only 1 loss. Within normal operating range. "
            "Signal quality check: SECOND DRIVE ✓, Bubble 4500 contracts ✓, CVD +850 ✓, above VWAP ✓. "
            "This is A-grade: all three elements (state + location + aggression) align. "
            "1 loss doesn't trigger any reduction rule. Standard risk (0.25-0.5% of account). "
            "The rule is: 3 losses = walk. 2 losses = reduce. 1 loss = normal operation. "
            "Decision: LONG High."
        ),
        rationale="1 loss (within tolerance), A-grade second drive, bubble +4500, CVD +850 → LONG High at normal size."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 7: SESSION TIMING RULES
# ═══════════════════════════════════════════════════════════════════

SESSION_EXAMPLES = [

    _make_example(
        user=(
            "SESSION: NSE Opening Noise (09:15-09:20). B-grade setup present. "
            "Wild price swings. Spreads wide (15 bps). Delta whipsawing ±800. "
            "High volume but chaotic. No stable profile yet."
        ),
        direction="FLAT", confidence="High",
        think=(
            "SESSION RULE: Opening 5 minutes (09:15-09:20). "
            "Fabio: 'I strongly advise not to trade 10-20 minutes before/after session open.' "
            "'You will be liquidated even if your direction is right.' "
            "Wide spreads = slippage risk. Whipsawing delta = no readable aggression. "
            "Volume is high but CHAOTIC = not directional, not useful. "
            "Rule is absolute: Skip the opening noise. The profile hasn't formed. "
            "Decision: FLAT. Wait until 09:30+ when profile forms and volume is readable."
        ),
        rationale="Opening noise 09:15-09:20, wide spreads, whipsawing delta, no stable profile → FLAT. Wait for session open."
    ),

    _make_example(
        user=(
            "SESSION: NSE Midday (11:30-14:00). B-grade momentum signal. "
            "Volume declining vs morning. CVD slope: +180 (mild). "
            "Pattern forming but conviction low. False breakouts common in midday."
        ),
        direction="FLAT", confidence="High",
        think=(
            "SESSION RULE: Midday (11:30-14:00). "
            "Fabio mentions 'edge decay' in certain conditions — midday is the textbook case. "
            "Volume declining = less institutional participation = less reliable volume signals. "
            "CVD +180 = mild, not significant. B-grade in low-liquidity = C-grade effectively. "
            "Fabio trades NSE equities primarily in Primary Window (09:30-11:30). "
            "Midday = downgrade all setups by one grade. B→C = FLAT. "
            "False breakouts common = risk/reward deteriorates. "
            "Decision: FLAT. Only A-grade setups acceptable in midday, and only if volume confirms."
        ),
        rationale="Midday session, declining volume, B-grade signal downgrades to C-grade. False breakout risk → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: NSE Close Protection (15:15-15:30). Long position open. "
            "Session ending in 15 minutes. Position profitable by ₹800 per contract. "
            "No new setups visible."
        ),
        direction="FLAT", confidence="High",
        think=(
            "SESSION CLOSE RULE: 15:15-15:30 = MANDATORY EXIT window. "
            "Fabio: 'I don't advise to keep trades overnight.' "
            "'This is a model that gets close as soon as the market closes.' "
            "'Cut the position and tomorrow it's another day.' "
            "Even if the trade is profitable and looks like it could continue — CLOSE IT. "
            "Overnight margin costs + gap risk not worth it. "
            "Lock in the ₹800 profit. Tomorrow is a fresh day. "
            "Decision: FLAT (meaning: close current position, no new entries)."
        ),
        rationale="Close protection window 15:15-15:30. Fabio rule: no overnight holds. Exit existing position → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window (09:30-11:00). 20 minutes into strong session. "
            "A-grade signal: second drive at LVN 22350 after imbalanced breakout. "
            "Volume bubble: 3.1σ buy (5200 contracts). CVD slope: +920. "
            "Price above VWAP. Delta: +1400. ✅ SECOND DRIVE."
        ),
        direction="LONG", confidence="High",
        think=(
            "SESSION CHECK: NSE Primary Window (09:30-11:30). This is the BEST session. "
            "Fabio: 'Best session = 100% New York session (or NSE equivalent primary window). "
            "'This model gives the biggest amount of volatility in this window.' "
            "Signal quality: second drive ✓, bubble 5200 ✓, CVD +920 (very strong) ✓, above VWAP ✓, delta +1400 ✓. "
            "This is a textbook A-grade setup in the optimal session window. "
            "Decision: LONG High confidence. Full position size."
        ),
        rationale="Prime session window, A-grade second drive, massive bubble +5200, CVD +920 → LONG High, full size."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 8: ABORT / EXIT SIGNALS
# ═══════════════════════════════════════════════════════════════════

ABORT_EXAMPLES = [

    _make_example(
        user=(
            "Currently LONG. Price making new highs above 22500. "
            "BUT delta is diverging NEGATIVE: -1200. Price up, buyers not following. "
            "CVD slope turning down: -280. No real aggression from buyers. "
            "Hidden supply: passive sellers absorbing every buy."
        ),
        direction="SHORT", confidence="Medium",
        think=(
            "ABORT SIGNAL: CVD DIVERGENCE. Price making new highs BUT delta -1200 and CVD turning down. "
            "Fabio: 'CVD divergence = kill the trade.' "
            "Price rising without buyer support = HIDDEN SUPPLY absorbing. "
            "This is the AAA setup in reverse — sellers are the real party here. "
            "The long position should be exited: 'if you see big sell aggression not having follow-up... "
            "sellers building narrative.' Wait for confirmation of short. "
            "If already flat: Short signal but only MEDIUM confidence (no bubble yet, just divergence). "
            "Action: Exit long immediately. Consider short on confirmation."
        ),
        rationale="Bearish CVD divergence: price up but delta -1200, CVD turning down. Hidden supply absorbing. Exit long, consider SHORT Medium."
    ),

    _make_example(
        user=(
            "Entered LONG at VAL 22100. Volume dried up immediately after entry. "
            "No follow-through. Delta turned neutral: +15. CVD slope flat: +12. "
            "Confirmation disappeared within first 2 candles."
        ),
        direction="FLAT", confidence="High",
        think=(
            "ABORT SIGNAL: NO FOLLOW-THROUGH. "
            "Fabio: 'If you don't have follow-through, scratch the position immediately.' "
            "'Confirmation disappeared = the story changed.' "
            "Delta +15 = essentially zero. CVD flat. Volume dried up. "
            "The entire premise for the trade (aggression = confirmation) is GONE. "
            "Fabio: 'If wrong, be wrong immediately. Never widen stop loss.' "
            "The market is telling you: this is not the time. Get out. "
            "Decision: FLAT. Exit position at near breakeven."
        ),
        rationale="No follow-through: volume dried, delta neutral, CVD flat. Fabio: scratch immediately when confirmation disappears → FLAT."
    ),

    _make_example(
        user=(
            "Entered SHORT at VAH 48200. Price IMMEDIATELY broke higher with +2000 Delta surge. "
            "Strong buying momentum. Stop loss about to be hit. "
            "Was expecting rejection but market accelerating upward."
        ),
        direction="FLAT", confidence="High",
        think=(
            "ABORT SIGNAL: WRONG IMMEDIATELY. "
            "Fabio: 'If wrong, wrong immediately. Never widen your stop loss.' "
            "Price immediately breaking opposite to entry = trade invalidated. "
            "The key principle: 'Be wrong immediately.' A small loss now vs a large loss if stop widens. "
            "Never add to a losing position. Never widen the stop. "
            "Accept the loss. The stop will trigger. Let it. "
            "Decision: FLAT. Let stop hit. Tomorrow is another day."
        ),
        rationale="Immediately wrong: price broke opposite with +2000 delta. Fabio: be wrong immediately, never widen SL → FLAT (take the hit)."
    ),

    _make_example(
        user=(
            "SESSION: NSE Primary Window. RBI policy announcement in 15 minutes. "
            "Good technical setup at POC 22300 — price at fair value, some aggression. "
            "CVD slope: +220. But major event imminent."
        ),
        direction="FLAT", confidence="High",
        think=(
            "EVENT RISK RULE: Major announcement in 15 minutes. "
            "Fabio mentions this context: before events, market behavior is unpredictable. "
            "'Yesterday there was America bombing Iran — cannot expect market to behave as Friday.' "
            "Before a central bank decision: liquidation risk is extreme. "
            "Even a good technical setup (POC, some aggression) = NOT worth the binary risk. "
            "The R:R collapses because the stop needs to be wider to handle volatility. "
            "Rule: Never trade ahead of major events (RBI, Fed, CPI, etc). "
            "Decision: FLAT. Wait for announcement to pass, volatility to normalize."
        ),
        rationale="RBI announcement in 15 min. Major event risk collapses R:R. Fabio: never trade ahead of major events → FLAT."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 9: SPREAD/LIQUIDITY FILTERS
# ═══════════════════════════════════════════════════════════════════

LIQUIDITY_EXAMPLES = [

    _make_example(
        user=(
            "SESSION: NSE Primary Window. Good setup at VAL 22100. "
            "Delta: +680, Volume bubble present. CVD slope: +390. D-shape. ✅ SECOND DRIVE. "
            "BUT bid-ask spread: 18 bps (normally 2-4 bps for this instrument). Liquidity thin."
        ),
        direction="FLAT", confidence="High",
        think=(
            "LIQUIDITY FILTER: Spread 18 bps vs normal 2-4 bps. "
            "At 18 bps, we're giving away 18 bps just to enter + 18 bps to exit = 36 bps round trip. "
            "For a scalp targeting 1.5-3% move, 36 bps is significant drag. "
            "Also: thin liquidity = slippage risk on stop loss execution. "
            "The stop could execute 5-10 bps worse than intended. "
            "Fabio: 'Skip trades with poor liquidity.' "
            "Even a good setup fails the minimum edge threshold when spreads are this wide. "
            "Decision: FLAT. Wait for liquidity to normalize or skip this session."
        ),
        rationale="18 bps spread (9x normal) = slippage risk kills edge. Fabio: skip thin liquidity setups → FLAT."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 10: TRANSCRIPT-SPECIFIC INSIGHTS
# New scenarios from what Fabio actually says in the live session
# ═══════════════════════════════════════════════════════════════════

TRANSCRIPT_EXAMPLES = [

    # "Wait for the second drive — you wait for the first breakout, I wait for the retracement"
    _make_example(
        user=(
            "SESSION: NSE Primary Window. MARKET STATE: BALANCED. "
            "Price broke out of VAH 22500 (first breakout). "
            "Now price is retracing back toward VAH area. Low volume node visible at 22350. "
            "No bubble yet at LVN. CVD slope: +145 (mild). ⚠️ FIRST DRIVE."
        ),
        direction="FLAT", confidence="High",
        think=(
            "Fabio transcript: 'I don't take the first movement. I WAIT for the first breakout, "
            "then I wait for the retracement. When it retraces to the low volume node, THAT is the entry.' "
            "Currently: first breakout happened. Price retracing. BUT no bubble at LVN yet. "
            "CVD +145 = mild. No bubble = no confirmation = no entry. "
            "The SETUP is forming (correct location) but the TRIGGER (aggression) hasn't fired. "
            "Wait for price to reach LVN AND see a buy bubble (2.5σ+). "
            "Decision: FLAT. Monitor for bubble at LVN 22350."
        ),
        rationale="First breakout done, retracing to LVN. No bubble yet at LVN. CVD mild. Fabio: wait for aggression at LVN → FLAT."
    ),

    # "Punch on the wall" — aggressive effort with zero result = signal flip
    _make_example(
        user=(
            "SESSION: NSE Primary Window. Sellers have been pushing aggressively: "
            "3 separate sell bubbles (2.8σ, 3.1σ, 2.6σ) at 22300 level over 20 minutes. "
            "But price has NOT moved down. Buyers absorbing everything. "
            "CVD slope: +280 (positive despite sell pressure). D-shape. ✅ SECOND DRIVE."
        ),
        direction="LONG", confidence="High",
        think=(
            "Fabio transcript: 'Punch on the wall — aggression without result changes the narrative.' "
            "3 massive sell bubbles = sellers trying HARD. But price not moving = buyers are ABSORBING. "
            "CVD positive DESPITE sell bubbles = institutional buyers winning the battle. "
            "Fabio: 'If sellers are not going through with their aggression, they will eventually be squeezed.' "
            "These trapped sellers = upcoming fuel for the buy squeeze. "
            "The narrative has FLIPPED: what looked bearish is actually ultra-bullish. "
            "Sellers are building the squeeze fuel for longs. "
            "Decision: LONG High confidence. Small stop below last sell bubble."
        ),
        rationale="Punch on wall: 3 sell bubbles rejected, CVD positive, sellers trapped and becoming squeeze fuel → LONG High."
    ),

    # Round number reaction
    _make_example(
        user=(
            "SESSION: NSE Primary Window. Price approaching round number 22000. "
            "Trend was bullish, good momentum. CVD slope: +480. Strong move upward. "
            "But price is now at exact round number 22000."
        ),
        direction="FLAT", confidence="Medium",
        think=(
            "Fabio transcript: '22 round number — price will accumulate or distribute here. "
            "It's a really important number.' "
            "Round numbers (22000, 48000, 6000 crude, etc.) = always expect pause or reversal. "
            "Two scenarios: 1) Accumulate here and break higher = need to wait for confirmation. "
            "2) Distribute here = don't be in long, sellers will step in. "
            "Current action: CVD strong but at round number = risk of rejection. "
            "Better play: wait for reaction at round number. "
            "If price consolidates and shows buy bubble → enter LONG continuation. "
            "If sellers step in and absorb → SHORT. "
            "Decision: FLAT for now. Monitor the battle at 22000."
        ),
        rationale="Price at round number 22000. Fabio: always expect pause/reversal at round numbers. Wait for battle resolution → FLAT Medium."
    ),

    # "Don't marry your position" — bias flip
    _make_example(
        user=(
            "SESSION: NSE Primary Window. Started day with bullish bias. "
            "Price has now broken below the VAL compression range support at 22050. "
            "Sellers stepped in at break: Delta -1400, Bubble 2.9σ sell. "
            "CVD slope: -630. Price below VWAP. P-shape forming."
        ),
        direction="SHORT", confidence="High",
        think=(
            "Fabio transcript: 'My narrative was long from the beginning. The market did aggressive selloff. "
            "I was ready to CHANGE my narrative.' "
            "'I'm not marrying my position. My long day gets activated if we break the high. "
            "My SHORT day gets activated if we break the compression range down.' "
            "LEVEL INVALIDATION: VAL support broken with aggressive sellers = long bias CANCELLED. "
            "New narrative: SHORT day activated. "
            "Step 1 - AGGRESSION: Sell bubble 2.9σ, delta -1400, CVD -630 = strong sellers. "
            "Step 2 - STRUCTURE: P-shape forming, below VWAP, support broken = bearish structure. "
            "Decision: SHORT High. Bias flipped. Fabio principle followed."
        ),
        rationale="Long bias invalidated: VAL support broken with sell bubble -1400, P-shape, CVD -630, below VWAP → SHORT High."
    ),

    # "Building profit, then taking risk with profits" — world cup method
    _make_example(
        user=(
            "SESSION: NSE Primary Window. Built ₹8,500 profit already today (3 successful trades). "
            "An aggressive momentum setup is forming: second drive continuation after breakout. "
            "CVD slope: +1100 (exceptional). Delta: +2200. Volume bubble: 3.5σ (very large). "
            "Risk-to-reward could be 1:8 to 1:12 if day continues trending. ✅ SECOND DRIVE."
        ),
        direction="LONG", confidence="High",
        think=(
            "Fabio world cup strategy: 'Building profit for the day, building, and in directional days "
            "I risk the profit I made for the day and you get a huge percentage.' "
            "Current cushion: ₹8,500 = significant house money. "
            "Signal quality: CVD +1100 (EXCEPTIONAL), delta +2200, bubble 3.5σ = ELITE setup. "
            "This is the directional day Fabio describes. 1:8-1:12 R:R is achievable on such days. "
            "Apply world cup method: use session profit as risk capital, scale up. "
            "This is the exact scenario where Fabio breaks his normal 0.25-0.5% risk rule "
            "and goes up to 1% using profit. "
            "Decision: LONG High confidence, scale up with session profits."
        ),
        rationale="₹8500 cushion + elite setup (CVD +1100, bubble 3.5σ) + directional day. World cup method: scale with profits → LONG High."
    ),

    # Stop loss INSIDE the cluster (inside extreme)
    _make_example(
        user=(
            "Setting entry on LONG at VAL 22100. Volume bubble cluster: big buy orders at 22095-22098. "
            "Conventional SL would be below the VAL low at 22070. "
            "Should SL go below 22070 OR inside the cluster at 22093?"
        ),
        direction="LONG", confidence="High",
        think=(
            "Fabio stop loss rule from transcript: "
            "'A small trick: put your stop loss NOT above the high. "
            "Above the high there are a lot of orders and the market will accelerate. "
            "You lose additional ticks from acceleration. "
            "Put SL one or two ticks BELOW the high (or in this case below the cluster). "
            "You are taken out before the acceleration. It's worth it.' "
            "Applied to this long: cluster is at 22095-22098. "
            "SL should be at 22093 (1-2 ticks inside the cluster). "
            "If wrong: taken out at 22093 before the acceleration downward that traps others. "
            "If right: protected inside the cluster without widening stop. "
            "Decision: LONG High, with SL at 22093 (inside cluster), not at 22070."
        ),
        rationale="Entry LONG at VAL. Fabio: SL inside cluster at 22093, not outside at 22070. Reduces slippage from acceleration → LONG High."
    ),

    # Profile + LVN finding the reaction level
    _make_example(
        user=(
            "SESSION: NSE Primary Window. Price in free fall, no visible support. "
            "Daily profile shows LVN gap at 22200-22250 (zero volume area). "
            "Price now approaching LVN at 22215. "
            "First touch of LVN. No bubble yet. CVD slope: -320 (still bearish)."
        ),
        direction="FLAT", confidence="High",
        think=(
            "LVN = Low Volume Node = low transaction area = market passes through quickly. "
            "Fabio: 'Low volume node is a really good reaction level.' "
            "But: 'I wait — I don't take the first touch because it's risky.' "
            "CVD -320 = still bearish, sellers in control. "
            "One scenario: price bounces at LVN briefly but continues down (first fake). "
            "Better plan: wait for price to reach LVN, see if sellers run out of momentum (CVD turning), "
            "THEN look for buy bubble at LVN for the mean reversion trade. "
            "Decision: FLAT. Alert set at 22215. Watch for seller exhaustion + buy bubble."
        ),
        rationale="LVN at 22215 approaching but no bubble, CVD still bearish. Fabio: LVN is reaction zone but first touch + no aggression → FLAT."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 11: MCX CRUDEOIL SPECIFIC EXAMPLES
# (System trades MCX CRUDEOIL mode)
# ═══════════════════════════════════════════════════════════════════

MCX_EXAMPLES = [

    _make_example(
        user=(
            "SESSION: MCX Primary (10:00-14:00 IST). MARKET STATE: IMBALANCED. "
            "CRUDEOIL at 6450. Prior session VAH: 6500, VAL: 6350, POC: 6420. "
            "Price broke above 6500 with displacement. Pulled back to LVN at 6480. "
            "Delta: +850. Bubble: 2.7σ buy at 6480 (320 lots). CVD slope: +580. "
            "Price above VWAP (6440). ✅ SECOND DRIVE."
        ),
        direction="LONG", confidence="High",
        think=(
            "MCX CRUDEOIL context: same model applies. "
            "Step 1 - AGGRESSION: Delta +850, bubble 320 lots at LVN, CVD +580 = strong buyers. "
            "320 lots on CRUDEOIL = significant institutional size for MCX. "
            "Step 2 - STRUCTURE: Imbalanced market (broke above prior VAH 6500). "
            "Price pulled back to LVN at 6480 = textbook trend continuation entry zone. "
            "Above VWAP 6440 = bullish bias confirmed. "
            "Step 3 - SECOND DRIVE: LVN retest after displacement = classic Fabio setup. "
            "Target = previous balance POC (6420 below used as floor, next POC target above). "
            "Decision: LONG High confidence. MCX CRUDEOIL options: buy CALL at ATM/slight ITM."
        ),
        rationale="CRUDEOIL LVN pullback after VAH breakout, bubble 320 lots, CVD +580, second drive → LONG High, buy CALL."
    ),

    _make_example(
        user=(
            "SESSION: MCX Pre-market (09:00-10:00 IST). CRUDEOIL options chain open. "
            "CRUDEOIL futures not yet active. Spread on options: 15 points (normally 2-5). "
            "Looking to take position ahead of MCX open."
        ),
        direction="FLAT", confidence="High",
        think=(
            "MCX PRE-MARKET RULE: MCX primary session starts 10:00 IST. "
            "Pre-market behavior = same issues as NSE opening noise. "
            "Wide options spread (15 points vs normal 2-5) = slippage will destroy edge. "
            "Futures not generating meaningful volume profile yet. "
            "Fabio: 'Never trade 10-20 minutes before session. You will be liquidated.' "
            "Pre-market option positions carry gap risk at MCX open. "
            "Decision: FLAT. Wait for 10:00 IST MCX open."
        ),
        rationale="MCX pre-market, wide 15-point spread, no futures volume profile. Pre-market noise rule → FLAT."
    ),

    _make_example(
        user=(
            "SESSION: MCX Primary. CRUDEOIL 6400 PUT option. "
            "Underlying CRUDEOIL at 6350 (below VAL 6380). MARKET STATE: IMBALANCED (breakdown). "
            "Delta on underlying: -680. CVD slope: -490. P-shape profile. "
            "Bubble: 2.6σ sell at 6355 (280 lots). ✅ SECOND DRIVE. LVN at 6380 above."
        ),
        direction="SHORT", confidence="High",
        think=(
            "CRUDEOIL SHORT setup: underlying-first analysis. "
            "Step 1 - AGGRESSION: Delta -680, sell bubble 280 lots, CVD -490 = institutional sellers. "
            "Step 2 - STRUCTURE: Imbalanced, below VAL 6380 (breakdown confirmed). "
            "P-shape = sellers distributing. LVN 6380 now acts as RESISTANCE above. "
            "Second drive below VAL = trend continuation model active. "
            "Options application: buy PUT at ATM (6400) or slight OTM. "
            "Target on underlying: prior balance POC (6300 area). "
            "Decision: SHORT High. Buy CRUDEOIL 6400 PUT."
        ),
        rationale="CRUDEOIL imbalanced breakdown, P-shape, sell bubble 280 lots, CVD -490, second drive → SHORT High, buy 6400 PUT."
    ),
]

# ═══════════════════════════════════════════════════════════════════
# SECTION 12: OVERSEER / TRADE MANAGEMENT SCENARIOS
# (For the active position manager)
# ═══════════════════════════════════════════════════════════════════

OVERSEER_EXAMPLES = [

    _make_example(
        user=(
            "[OVERSEER MODE] LONG position open. Side=LONG Entry=22100 Current=22145 "
            "Unrealized=+0.21% SL=22070 TP=22250 Hold=180s. "
            "Market: State=BALANCED POC=22120 VAH=22280 VAL=22080 "
            "Aggression=1.4 CVD_slope=+420 Delta=+0.45. "
            "Risk: Tier=A DailyPnL=+1200 LossStreak=0 DailyLoss=0.00%. "
            "ACTION needed: HOLD | TIGHTEN_SL | PARTIAL_EXIT | FULL_EXIT | ADD"
        ),
        direction="FLAT", confidence="High",
        think=(
            "Position review: LONG at 22100, currently 22145 = +45 pips = +0.21% unrealized. "
            "CVD +420 = buyers still in control, momentum intact. "
            "Aggression 1.4/2.0 = strong but not excessive. "
            "SL at 22070 = protected. TP at 22250 = still 105 pips away. "
            "Daily PnL positive, no loss streak. "
            "Fabio action: CVD still bullish = HOLD. "
            "No reason to tighten SL yet — not enough profit buffer (only +45 pips, SL is 75 pips away). "
            'Output JSON: {"action": "HOLD", "reason": "CVD+420 bullish, momentum intact, price moving toward TP, no SL tighten needed"}'
        ),
        rationale='{"action": "HOLD", "reason": "CVD +420, aggression 1.4, price +0.21% trending toward TP. Momentum intact."}'
    ),

    _make_example(
        user=(
            "[OVERSEER MODE] LONG position. Side=LONG Entry=22100 Current=22190 "
            "Unrealized=+0.43% SL=22070 TP=22250 Hold=420s. "
            "Market: State=IMBALANCED POC=22120 VAH=22280 CVD_slope=+820 Delta=+0.68 "
            "Aggression=1.8. Risk: Tier=A DailyPnL=+2100 LossStreak=0."
        ),
        direction="FLAT", confidence="High",
        think=(
            "Position: +90 pips, 420 seconds in. CVD +820 = very strong, market confirming direction. "
            "Fabio rule: 'When CVD confirms direction strongly, move to breakeven IMMEDIATELY.' "
            "Current SL at 22070. Entry at 22100. Breakeven SL = 22100. "
            "Action: TIGHTEN_SL to 22100 (breakeven). "
            "This is risk-free position. CVD +820 = buyer conviction strong = let it run. "
            'Output: {"action": "TIGHTEN_SL", "new_sl_price": 22100, "reason": "CVD +820 confirms direction, moving to breakeven"}'
        ),
        rationale='{"action": "TIGHTEN_SL", "new_sl_price": 22100, "reason": "CVD +820 strong confirmation. Move to breakeven per Fabio rule."}'
    ),

    _make_example(
        user=(
            "[OVERSEER MODE] LONG position. Side=LONG Entry=22100 Current=22240 "
            "Unrealized=+0.63% SL=22100 TP=22250 Hold=720s. "
            "Market: CVD_slope=-180 Delta=-0.35 Aggression=0.6 State=BALANCED. "
            "Price at TP level. Risk: DailyPnL=+3500."
        ),
        direction="FLAT", confidence="High",
        think=(
            "Position at TP: only 10 pips from target (22240 vs TP 22250). "
            "CVD -180 = turning bearish. Delta -0.35 = sellers stepping in. Aggression 0.6 = declining. "
            "Fabio: 'When I told you I will scale out, it's because when you see THIS, the next step is aggressive sellers.' "
            "TP level approaching + CVD diverging negative = PARTIAL_EXIT or FULL_EXIT. "
            "Fabio: 'I take out the full position because the probability that market reverses from here is 70%.' "
            "At TP with CVD turning = full exit most appropriate. "
            'Output: {"action": "FULL_EXIT", "reason": "Price at TP, CVD diverging -180, sellers stepping in. Fabio: take full profit at TP."}'
        ),
        rationale='{"action": "FULL_EXIT", "reason": "At TP 22250, CVD diverging -180, sellers active. Fabio: take full profit, 70% reversal prob."}'
    ),
]

# ═══════════════════════════════════════════════════════════════════
# ASSEMBLE ALL EXAMPLES + AUGMENTATION
# ═══════════════════════════════════════════════════════════════════

def augment_numbers(example: dict, shift: float) -> dict:
    """Slightly shift prices to create varied numeric examples."""
    import copy, re
    ex = copy.deepcopy(example)
    def shift_num(m):
        val = float(m.group())
        return f"{val + shift:.0f}"
    for msg in ex["messages"]:
        if msg["role"] != "system":
            msg["content"] = re.sub(r"\b([1-9][0-9]{3,5})\b", shift_num, msg["content"])
    return ex

ALL_EXAMPLES = (
    TRIPLE_A_EXAMPLES * 4 +
    DRIVE_EXAMPLES * 5 +       # Increased weight on Second Drive logic
    MEAN_REV_EXAMPLES * 4 +
    SQUEEZE_EXAMPLES * 4 +
    FILTER_EXAMPLES * 10 +      # HEAVY weight on VWAP/CVD filters (was 3)
    RISK_EXAMPLES * 8 +        # HEAVY weight on Risk overrides (was 3)
    SESSION_EXAMPLES * 8 +     # HEAVY weight on Session timing (was 3)
    ABORT_EXAMPLES * 8 +       # HEAVY weight on Exits (was 4)
    LIQUIDITY_EXAMPLES * 6 +   # Increased (was 3)
    TRANSCRIPT_EXAMPLES * 6 +  # Increased (was 4)
    MCX_EXAMPLES * 4 +
    OVERSEER_EXAMPLES * 4
)

# Add augmented variants with shifted prices
AUGMENTED = []
for ex in ALL_EXAMPLES[:150]:  # Augment more base cases (was 60)
    for shift in [-50, +50, -150, +150]:
        AUGMENTED.append(augment_numbers(ex, shift))

FINAL = ALL_EXAMPLES + AUGMENTED
random.shuffle(FINAL)

# 90% train, 10% validation
split = int(len(FINAL) * 0.9)
train_set = FINAL[:split]
val_set   = FINAL[split:]


def main():
    os.makedirs("poc_gemma4_e4b/data", exist_ok=True)

    with open(OUTPUT_FILE, "w") as f:
        for ex in train_set:
            f.write(json.dumps(ex) + "\n")

    with open(VAL_FILE, "w") as f:
        for ex in val_set:
            f.write(json.dumps(ex) + "\n")

    print(f"✅ Generated {len(train_set)} training examples → {OUTPUT_FILE}")
    print(f"✅ Generated {len(val_set)} validation examples → {VAL_FILE}")
    print(f"\nBreakdown:")
    print(f"  Base examples:     {len(ALL_EXAMPLES)}")
    print(f"  Augmented:         {len(AUGMENTED)}")
    print(f"  Total:             {len(FINAL)}")
    print(f"  Train / Val split: {len(train_set)} / {len(val_set)}")

    # Sample preview
    print(f"\nSample output (first example):")
    sample = train_set[0]["messages"]
    print(f"  [system]:    {sample[0]['content'][:100]}...")
    print(f"  [user]:      {sample[1]['content'][:100]}...")
    print(f"  [assistant]: {sample[2]['content'][:200]}...")


if __name__ == "__main__":
    main()
