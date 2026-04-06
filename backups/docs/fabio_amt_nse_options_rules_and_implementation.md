# Fabio AMT Strategy — NSE Options Translation

## Complete Rules & Implementation Guide for NIFTY/BANKNIFTY Options

Extracted from Fabio Valentini's live trading session transcript and adapted for NSE derivative contracts. Every rule below maps directly to a specific behavior observed in the transcript, translated into quantifiable logic for automated or semi-automated execution on Indian indices.

---

## Part A: Extracted Rules from the Transcript

### What Fabio Actually Does (Observed Behavior → Quantified Rule)

---

### Rule 1: Session Structure — "The First Directional Move"

**Transcript Evidence:**
> "Usually I wait for European time the first 30 minutes of New York opening to have a little bit of stability"
> "90% of my execution of model B testing of the value area after their expansion is from 7:30 European time till 9"
> "If you expand immediately... you rebalance till the power hour"

**Extracted Rule:**
```
SESSION PHASES for NSE:

    Phase 1 — Opening Noise (09:15 – 09:30 IST):
        DO NOT TRADE. Let the auction settle.
        Use this time to:
            - Build the day's initial volume profile
            - Identify opening range (OR = first 15 min high/low)
            - Watch for gap direction and overnight positioning

    Phase 2 — Primary Setup Window (09:30 – 11:30 IST):
        THIS IS YOUR AAA WINDOW. Equivalent to Fabio's NY opening.
        Take the FIRST directional move only.
        This is where the Trend Model and Mean Reversion Model trigger.

    Phase 3 — Midday Consolidation (11:30 – 14:00 IST):
        Equivalent to Fabio's "consolidation after expansion."
        DO NOT initiate new Trend Model trades.
        Only valid setup: Mean Reversion if price returns to POC.
        "After a wave like this zero retracement the market will
         just go sideways and when go sideways it's expensive."

    Phase 4 — Power Hour (14:00 – 15:15 IST):
        Equivalent to Fabio's "power hour."
        Second-best window for AAA setups.
        Watch for reaccumulation at value area low → expansion.
        "The game plan is done... then the power hour you go up."

    Phase 5 — Close Protection (15:15 – 15:30 IST):
        NO NEW ENTRIES. Close all positions.
        NSE options lose all time value rapidly in last 15 min.
```

---

### Rule 2: Risk Sizing — "Only Risk the Profit"

**Transcript Evidence:**
> "Risk Size: Keep risk small, 0.25% to 0.5% of the account per trade"
> "We are risking 2,000 to make a potential $10,000"
> "Consider it's only $800 risk"
> "I don't want to risk because we are already in profit 11,000"
> "I only risk the profit of the session"
> "On a $25,000 day, what I'm risking 2,000, not even 10%"

**Extracted Rule:**
```
POSITION SIZING:

    Base risk per trade:
        risk_pct = 0.25% to 0.50% of account equity
        HARD CLAMP: never exceed 0.50%

    For a ₹10,00,000 account:
        max_risk_per_trade = ₹2,500 to ₹5,000

    Dynamic risk adjustment (Fabio's "cushion" concept):
        IF session_profit > 0:
            available_risk = min(base_risk, session_profit × 0.20)
            "I only risk the profit of the session"

        IF session_profit > 2 × base_risk:
            can_increase_lot_count by 1-2 lots
            "I can start to build my position"

        IF session_profit < 0:
            REDUCE to minimum risk (0.25%)
            After 3 consecutive losses → STOP for the session

    Risk-to-Reward minimum:
        NEVER take a trade below 1:2.5 R:R
        Target trades: 1:4 to 1:5 R:R
        "We are risking 2,000 to make a potential $10,000" = 1:5

    For NSE Options:
        risk_per_trade = number_of_lots × lot_size × stop_loss_points
        NIFTY lot = 25 units, BANKNIFTY lot = 15 units

        Example:
            Account: ₹10,00,000
            Risk per trade: ₹5,000 (0.5%)
            NIFTY option premium: ₹200
            Stop loss: ₹25 (12.5% of premium)
            Lots: ₹5,000 / (25 × ₹25) = 8 lots

            Target: ₹100 move in premium (50% of premium)
            R:R = ₹100/₹25 = 1:4 ✅
```

---

### Rule 3: The AAA Setup — "Value Area Low on Absorption"

**Transcript Evidence:**
> "This is the AAA setup... Value area low. So we are really low on the curve."
> "The market participants are setting up because it's 30 minutes in the session"
> "What I was trying to explain before is that we have a P shape... all the volume is built on the top part... you go back to test to reaccumulate and you rebalance the profile and then you continue."
> "Huge aggression on the value area low. Full of sellers. Huge aggression of buyers with result."

**Extracted Rule — The AAA Setup:**
```
PRECONDITIONS (ALL must be true):
    1. Market state: IMBALANCED (displacement leg detected)
    2. Time: within Phase 2 (09:30-11:30) or Phase 4 (14:00-15:15)
    3. Volume profile shows P-shape or b-shape distribution:
        P-shape: volume concentrated at top → expect retest of bottom → expand up
        b-shape: volume concentrated at bottom → expect retest of top → expand down
    4. Price has pulled back to value area low (for longs) or value area high (for shorts)
    5. Absorption visible: aggressive sellers being absorbed by passive buyers (for longs)

ENTRY TRIGGER:
    Price at VAL (within buffer) + absorption confirmed
    "Big buy bubbles or imbalance for longs"

    For NSE implementation (no tick-by-tick order flow):
        - Volume spike at VAL level (volume >= 1.5× 20-period avg)
        - Bullish candle forming at VAL (close > open, close in upper 40% of range)
        - Delta positive (estimated buy volume > sell volume)
        - OI increasing (new positions being built = conviction)

STOP LOSS:
    Below the absorption zone + 1-2 buffer ticks
    "Place just beyond the aggressive print. Add 1-2 tick buffer"

TARGET:
    Value Area High (for longs from VAL)
    OR Previous session POC
    "Going from the value area low in a momentum day to the value area high"
```

---

### Rule 4: Scaling In — "Build as You Go"

**Transcript Evidence:**
> "I didn't load it full size because I want to scale as we go up. I want to be right with the market."
> "I'm not to load everything while the market is collapsing"
> "So I'm not to load everything... but by putting risk in the markets this way you can still do it"
> "The reason I fraction is because I'm fast and I can understand really fast how much am I risking"
> "If you put immediately 10 contract, you cannot build exactly in the level to make the risk always 2,000"

**Extracted Rule:**
```
SCALING STRATEGY:

    NEVER go full size on initial entry.
    Build position as the market confirms your thesis.

    Allocation:
        Entry 1: 40% of planned position at initial signal
        Entry 2: 30% on first confirmation (price moves in favor, absorption continues)
        Entry 3: 30% on breakout of key level or expansion

    Total risk stays FIXED at planned amount:
        Even as you add lots, the stop loss tightens.
        "Still risking 2,000 but now the potential is to make 7 8 10,000"

    For NSE Options:
        Planned: 8 lots total
        Entry 1: 3 lots at VAL touch + absorption
        Entry 2: 3 lots on first higher low + volume confirmation
        Entry 3: 2 lots on breakout above consolidation high

        After Entry 2: move stop to below Entry 2 level
        After Entry 3: move stop to breakeven on Entry 1
        Total risk at any point: never exceeds ₹5,000
```

---

### Rule 5: Breakeven Management — "Zero Risk in the First Minute"

**Transcript Evidence:**
> "In 1 minute the position is risk-free. So we are risking zero to make 10,000"
> "If I'm fast this 2,400 can go to zero risk really fast"
> "As soon as we go high trail stop-loss"
> "If CVD shows strong pressure, move the stop to break-even early"
> "Removing the stress in the first minute is something that is crazy for this field"

**Extracted Rule:**
```
BREAKEVEN PROTOCOL:

    Priority #1 after entry: GET TO BREAKEVEN as fast as possible.

    Trigger conditions (any one):
        a) Price moves 1R in your favor
           "In 1 minute the position is risk-free"

        b) Strong volume/delta confirmation after entry
           "If CVD shows strong pressure, move stop to break-even early"

        c) You've scaled in and have a cushion
           If floating profit > initial risk, move stop to breakeven

    Implementation:
        For LONG: new_stop = entry_price + (1 tick × tick_size)
        For SHORT: new_stop = entry_price - (1 tick × tick_size)

    CRITICAL: This is the #1 skill for this model.
        "Getting your stop loss to zero in the first minute
         is something that is crazy for this field"

    For NSE Options:
        If bought at ₹200, stop at ₹175 (₹25 risk)
        As soon as price reaches ₹225 (1R in favor):
            Move stop to ₹202 (breakeven + slippage buffer)
        Now: risking ₹2 to make potentially ₹100+
```

---

### Rule 6: Take Profit — "Close at POC, Don't Stretch"

**Transcript Evidence:**
> "Target the previous balance POC. Close the full position there."
> "The main rule is to exit at the POC because 70% of the time, the price reverses from balance"
> "Don't stretch for the other side of the range unless conditions are exceptional"
> "I prefer to have consistent 10,000 7,000 10,000 days instead of having -5 -6 -7 +60"
> "Getting from A to B and A to C, it's of course a huge number of different in ticks. This probability in ticks is contained and distributed through days."

**Extracted Rule:**
```
EXIT RULES:

    PRIMARY EXIT: Close FULL position at POC.
        "70% of the time the price reverses from balance"
        This is non-negotiable for the base model.

    RUNNER EXCEPTION (rare, strict criteria):
        Only if ALL true:
            - Market is in strong imbalance (not just momentum)
            - Displacement is continuing (new candles meeting displacement criteria)
            - You are already in significant profit for the session
            - "If the markets today wants to give me 30,000, I take 30,000"

        If runner allowed:
            Close 70-80% at POC
            Trail remaining 20-30%
            Trail stop = most recent support/LVN

    DO NOT:
        - Hold for "the big move" as default behavior
        - Try to get from VAL to the other side of the range
        - Set and forget: "I cannot do this. Why? Because I have had
          too much pain to see risk-to-reward 1 to 20 going back to zero"

    WHY THIS MATTERS:
        "You cannot have 1 to 20 risk to reward with 75%.
         If you have, call me because you are some billionaire."

        Fabio's actual stats:
            Win rate: 43-49%
            Avg winner: ₹equivalent of $1,000 per contract
            Avg loser: ₹equivalent of $600 per contract
            Max winner: $10,000/contract, Max loser: $3,200/contract
            Payoff ratio: ~1.7:1 on average, up to 10:1 on best trades

    For NSE Options:
        Bought CE at ₹200 when NIFTY at VAL
        Target: sell when NIFTY reaches POC
        If option premium went from ₹200 → ₹320 at POC → EXIT 100%

        Do NOT hold hoping for "NIFTY to reach VAH"
        The extra ₹40-50 in premium is not worth risking ₹120 already gained
```

---

### Rule 7: Protection Levels — "Cover Behind Aggressive Trades"

**Transcript Evidence:**
> "What we can do is get a buy stop here because if we arrive there, we put all our risk here"
> "I'm taking a trade that is protected by a buy wall"
> "I want to be covered below aggressive sellers failure"
> "So we are capitalizing on other trades failure"
> "This is the model. I'm going to take profit as soon as the market goes up"

**Extracted Rule:**
```
STOP PLACEMENT LOGIC:

    The stop goes BEHIND a visible protection level.
    Not at arbitrary price points or fixed tick distances.

    "Protection level" = where aggressive orders are holding:
        For LONG stops: place below where aggressive BUYERS are absorbing
        For SHORT stops: place above where aggressive SELLERS are absorbing

    NSE Observable Proxies for "Absorption":
        1. Volume at level: high volume candle that reversed price = support/resistance
        2. Multiple touches without break: price tested level 3+ times and bounced
        3. Open Interest buildup: significant OI at a strike price = protection level
        4. Candle structure: long wicks (rejections) at a price level

    Stop Placement Formula:
        protection_level = identified absorption/rejection level
        buffer = 2-3 NIFTY points (or 5-10 BANKNIFTY points)

        For LONG: stop = protection_level - buffer
        For SHORT: stop = protection_level + buffer

    "Add a 1-2 tick buffer before the obvious swing high/low to avoid slippage"
```

---

### Rule 8: Contraction = No Trade — "The Market Is Saying We Are In Contraction"

**Transcript Evidence:**
> "After a wave like this zero retracement the market will just go sideways and when go sideways it's expensive for me to trade"
> "The market condition that I'm used to trade is this one like you build you accumulate you expand"
> "If the condition gets this you cannot watch this and says I want to make because the market is saying to you we are in contraction"
> "70% of the time the market is stationary"
> "I want to make money also when it's stationary" [with the consolidation model, not the AAA]

**Extracted Rule:**
```
CONTRACTION DETECTION:

    The market alternates: Expansion → Contraction → Expansion

    AFTER an expansion move, EXPECT contraction.
    DO NOT try to force momentum trades in contraction.

    Detection formula:
        last_expansion_range = range of the displacement leg
        current_range_N_candles = high - low of last N candles (e.g., 20)

        IF current_range_N_candles < 0.30 × last_expansion_range:
            market = CONTRACTING → reduce or stop trading

    Observable signs:
        - Volume profile developing bell curve (balanced)
        - Higher highs and lower lows alternating (no direction)
        - "Sellers trying to get aggressive getting absorbed"
          + buyers trying, also absorbed = both sides stuck
        - ATR declining compared to session average

    "You can try only the limit... but if the auction is failing,
     they are getting back in the range. I don't want to be inside."

    Action:
        - No new Trend Model trades
        - Mean Reversion model can work (trade VAH→POC or VAL→POC)
        - If already in profit: STOP TRADING
          "If I get the 20,000 profit for the day, my rules say it's done"
```

---

### Rule 9: Maximum 3 Stop-Losses Then Pause — "Three Losing Trades to Stop"

**Transcript Evidence:**
> "My rule was three losing trades to stop"
> "I give more room. I have four or five because usually you have consolidation and then expansion"
> "If I see that the session goes bad, the condition are not bad, usually I walk away"
> "I noticed that the days that start with three or four or five stop-loss end up with a losing of 20,000 15,000"

**Extracted Rule:**
```
CONSECUTIVE LOSS MANAGEMENT:

    Standard rule: 3 consecutive losses → PAUSE
    Extended rule (if in profit for session): up to 5 losses allowed

    Implementation:
        consecutive_losses = 0

        On each loss:
            consecutive_losses += 1

            IF consecutive_losses >= 3 AND session_pnl <= 0:
                STOP TRADING for remainder of session
                "Three losing trades to stop"

            IF consecutive_losses >= 5 AND session_pnl > 0:
                STOP TRADING
                "I don't let the market take seven, eight stop loss"

        On each win:
            consecutive_losses = 0  (reset counter)

    Daily max drawdown:
        max_daily_loss = ₹equivalent of configured limit
        Fabio uses: ~$10,000 on a multi-million account (~1%)

        For ₹10,00,000 account: max_daily_loss = ₹10,000 (1%)

        IF daily_pnl <= -max_daily_loss:
            CIRCUIT BREAKER: close everything, no more trades today
```

---

### Rule 10: The Momentum Squeeze — "Betting on Liquidation"

**Transcript Evidence:**
> "We are betting here on the squeeze"
> "If we reach these aggressive buyers, these sellers will need to close. If sellers needs to close, we have an expansion higher"
> "This level is creating a liquidation. There is a big probability that this level will create a liquidation"
> "My stop loss will be really tight... I can capitalize on the squeeze"

**Extracted Rule:**
```
MOMENTUM SQUEEZE SETUP:

    This is a SECONDARY setup (not AAA). Higher risk, requires:
        - Already in profit for the session (cushion built)
        - Clear compression visible after expansion
        - One side "locked" (visible protection level holding)

    Entry:
        Buy stop ABOVE the compression range high (for longs)
        Sell stop BELOW the compression range low (for shorts)

        "If we break this high, we will see exactly the same squeeze"

    Stop:
        IMMEDIATELY below the breakout level
        Very tight: "My stop loss will be really tight"

    Target:
        Previous session high/low or VWAP ±2 SD
        "If sellers needs to close, we have an expansion higher"

    Risk:
        Maximum $800-1,500 (smallest risk of any setup)
        "Consider it's only $800 risk"

    For NSE Options:
        When NIFTY/BANKNIFTY breaks above compression high:
            Buy ATM CE with very tight stop (5-10 NIFTY points)
            Target: next resistance level or previous session high
            The premium will expand rapidly if squeeze happens
            Option Greeks advantage: delta + gamma + vega all in your favor

    CRITICAL: This trade is about SPEED.
        Enter on breakout → move to BE in < 1 minute → trail or exit
        "As soon as we go high trail stop-loss and get back inside"
```

---

### Rule 11: Failed Auction = Done — "If the Auction Fails, Walk Away"

**Transcript Evidence:**
> "Philuction. Okay. So we don't want to be in this trade again"
> "We took the stop. But we didn't do a stop loss. Why? Because we analyze exactly the interaction"
> "If you're wrong, you should be wrong immediately. Never widen the stop."
> "There is only one condition where we can be in this trade again if we break this eye"

**Extracted Rule:**
```
FAILED AUCTION RULES:

    IF the price breaks your protection level:
        The thesis is INVALID. Exit immediately.
        DO NOT re-enter at the same level.

    Re-entry only allowed if:
        Price forms a NEW structure
        OR price reaches a NEW key level
        "There is only one condition where we can be in this trade again
         if we break this eye [high]"

    For NSE implementation:
        If your NIFTY LONG was stopped out at VAL:
            Do NOT buy again at the same level
            Wait for either:
                a) New LVN formation at a lower level → new entry zone
                b) Price breaks above the compression high → momentum entry
                c) Next session phase (e.g., Power Hour) → fresh evaluation
```

---

### Rule 12: Win Rate vs Risk-Reward Balance

**Transcript Evidence:**
> "I have 43 to 49% [win rate]"
> "The average winning trade is $1,000 on one contract... The average losing trade is 600"
> "All the losing trades are contained in 2500. All the best trades are like 6,000, 10,000"
> "I prefer to have consistent 10,000 7,000 10,000 days"
> "You cannot have 1 to 20 risk to reward with 75%"
> "If you try to shoot to get the maximum high, my W rate will get lower"

**Extracted Rule:**
```
EXPECTED PERFORMANCE PARAMETERS:

    Win Rate Target: 43-50%
    Average Winner to Loser Ratio: ~1.7:1
    Best trades: 4-10× the average loss
    Worst loss: capped at ~5× average loss (by rules above)

    Expectancy formula:
        E = (win_rate × avg_win) - ((1 - win_rate) × avg_loss)
        E = (0.46 × 1000) - (0.54 × 600) = 460 - 324 = +136 per contract

    For NSE Options (scaled):
        If avg option win = ₹40/unit, avg option loss = ₹25/unit
        Win rate 46%:
        E = (0.46 × 40) - (0.54 × 25) = 18.4 - 13.5 = +₹4.9/unit/trade
        Over 1000 trades/year: ₹4,900 per unit traded
        With 8 lots × 25 units = 200 units: ₹9,80,000/year expectancy

    KEY INSIGHT:
        "I have also a trading model... one to one risk-to-reward, 75%.
         The equity line is like this because it's consistent"

        Two viable approaches:
        A) AMT model: 45% WR, 1:3-5 RR → higher variance, higher peaks
        B) Consolidation model: 75% WR, 1:1 RR → lower variance, steadier

        Fabio uses BOTH depending on market condition.
```

---

### Rule 13: VWAP Bands — "Extension from Fair Value"

**Research Evidence:**
> "VWAP standard deviation bands are used to identify potential overextensions of price from the fair value"
> "When price reaches the second or third standard deviation, there's a higher probability of returning to the VWAP"
> "He often considers reversal trades only after accumulating some profit and when price reaches these extreme standard deviations"
> "Trail stop to VWAP band after a +1.5R gain"

**Extracted Rule:**
```
VWAP USAGE (3 distinct purposes):

    1. BIAS FILTER:
        Price ABOVE session VWAP → bullish bias (prefer longs)
        Price BELOW session VWAP → bearish bias (prefer shorts)
        "Simple directional filter before any setup"

    2. OVEREXTENSION DETECTOR:
        VWAP + 2σ / VWAP - 2σ = "extended" zone
        VWAP + 3σ / VWAP - 3σ = "extreme" zone

        At 2σ: tighten stops, take partials
        At 3σ: consider counter-trend ONLY if:
            - Already in profit for session (cushion built)
            - Absorption visible at that level
            - This is a mean-reversion setup, not prediction

    3. TRAILING STOP REFERENCE:
        After +1.5R profit on a trade:
            Move stop to the nearest VWAP band
            (typically VWAP + 1σ for longs, VWAP - 1σ for shorts)

        This replaces fixed trailing distances.
        "Dynamic trailing based on where fair value actually is"

    For NSE Implementation:
        Calculate session VWAP on NIFTY/BANKNIFTY futures:
            VWAP = Σ(Price × Volume) / Σ(Volume)
            σ = standard deviation of price from VWAP
        Plot bands at ±1σ, ±2σ, ±3σ
        Use 1-minute candles for calculation
```

---

### Rule 14: Big Trades as Breakout Levels — "Not Just Aggression"

**Research Evidence:**
> "Big Trades indicator to spot significant institutional activity... treating these as breakout levels"
> "Deep Trades filter goes beyond simple trade bubbles by incorporating MBO data, Icebergs, and aggregation"
> "He uses big trades not just to detect aggression but as levels themselves — where a big trade occurred becomes a breakout/breakdown reference"
> "Deep M Effort NQ identifies sensitive zones where buyers or sellers are absorbed"

**Extracted Rule:**
```
BIG TRADES AS STRUCTURE (not just confirmation):

    Standard use: big trade = confirmation of aggression ✅
    ADDITIONAL use: big trade LOCATION becomes a level itself

    How it works:
        1. A large trade ("big print") occurs at price level X
        2. That level X is now marked as a structural reference
        3. If price returns to X → watch for reaction
        4. If price breaks through X → that's a breakout signal

    Think of it as: "big trades create temporary POC-like levels"

    For NSE (proxy implementation):
        Since we can't see individual large trades:

        1. Volume spike detection:
            If a 1-min candle has volume > 3× 20-period average:
                Mark that candle's VWAP as a "big trade level"
                This level acts as support/resistance going forward

        2. OI spike detection:
            If OI at a strike changes by > 2× average OI change:
                Mark that strike price as a "big trade level"
                This is the options market equivalent

        3. Usage:
            - Stop loss placement: behind the nearest big trade level
            - Breakout trigger: when price breaks a big trade level with volume
            - Mean reversion target: big trade levels as interim targets
```

---

### Rule 15: Intraday Compounding — "The Cushion System"

**Research Evidence:**
> "He starts with low risk and compounds profits throughout the day"
> "If he makes 3% profit from three successful trades, he reallocates 2% of that profit to open new trades with increased risk"
> "Starts at 0.25%, scales to 0.35% or 0.40% after successful start"
> "I only risk the profit of the session"
> "On a $25,000 day, what I'm risking 2,000, not even 10%"

**Extracted Rule:**
```
INTRADAY COMPOUNDING PROTOCOL:

    Phase 1 — Conservative Start (first 1-2 trades):
        risk_per_trade = 0.25% of account
        "Start small, prove the market is readable today"

    Phase 2 — Cushion Built (after first profitable trade):
        IF session_pnl > 0:
            risk_per_trade = 0.35% of account
            Additional allowed: up to 20% of session profit

        Example:
            Account: ₹10,00,000
            Phase 1 risk: ₹2,500
            Won ₹7,500 on first trade
            Phase 2 risk: ₹3,500 (0.35%) + ₹1,500 (20% of ₹7,500) = ₹5,000

    Phase 3 — Momentum Day (2+ consecutive wins):
        IF session_pnl > 2 × base_risk:
            risk_per_trade = 0.40% of account
            Can increase lot count by 1-2 lots
            "I can start to build my position"

    COMPOUNDING CAP:
        NEVER risk more than 0.50% of account on a single trade
        NEVER risk more than session_profit × 0.30 on a single trade
        "If I'm up 20,000, I don't risk 20,000 on one trade"

    REVERSE SCALING (losing day):
        After 1st loss: stay at current risk level
        After 2nd consecutive loss: reduce to 0.25%
        After 3rd consecutive loss: STOP TRADING

    For NSE Options:
        Phase 1: 3 lots NIFTY CE/PE
        Phase 2 (cushion): 5 lots
        Phase 3 (momentum): 7-8 lots
        NEVER exceed risk cap regardless of lot count
```

---

### Rule 16: Pre-Session Daily Narrative — "Know Before You Trade"

**Research Evidence:**
> "He first establishes a daily narrative based on price structure and volume to determine if the market is dominated by aggressive buyers or sellers"
> "Identify points of interest and wait for order flow confirmation at these critical levels"
> "Use previous day session profile as baseline"
> "Mark impulse leg, profile it, mark LVNs"

**Extracted Rule:**
```
PRE-SESSION CHECKLIST (before 09:15 IST):

    1. PREVIOUS SESSION ANALYSIS (5 min of work):
        □ Build yesterday's volume profile (POC, VAH, VAL)
        □ Mark yesterday's developing POC position:
            P-shape = bullish (volume concentrated at top)
            b-shape = bearish (volume concentrated at bottom)
            D-shape = balanced (bell curve)
        □ Note yesterday's close relative to VA:
            Close above VAH = bullish gap potential
            Close below VAL = bearish gap potential
            Close inside VA = balanced open expected

    2. OVERNIGHT CONTEXT:
        □ Any gap from previous close?
            Gap > 0.5% = significant, will affect morning behavior
        □ Global cues (SGX NIFTY, US futures overnight)
        □ Any scheduled events today? (RBI, results, expiry)

    3. KEY LEVELS MARKED (before market opens):
        □ Yesterday's POC, VAH, VAL
        □ Previous week's POC, VAH, VAL (for weekly context)
        □ Recent swing highs/lows
        □ VWAP from previous session close
        □ Max pain strike for current expiry
        □ Highest OI CE strike (resistance)
        □ Highest OI PE strike (support)

    4. DAILY BIAS (one sentence):
        Write it down: "Today I expect [TREND UP / TREND DOWN / RANGE]
        because [specific reason: e.g., yesterday P-shape, gap up, OI buildup at X]"

        This is NOT a prediction to marry.
        This is a starting framework to update as data comes in.
        "If the market tells you different, listen to the market."
```

---

### Rule 17: Trade Abort Signals — "Kill the Trade"

**Research Evidence:**
> "Abort trades if there's an aggressive unwind shown by delta divergence"
> "Opposing stacked imbalances indicate position reversal"
> "Clean VWAP reclaim against trade bias = exit immediately"
> "Scales out of partial positions at first sign of opposing order flow"
> "If confirmation disappears quickly (no follow-through), scratch/exit early"

**Extracted Rule:**
```
TRADE ABORT SIGNALS (exit immediately, don't wait for SL):

    ANY ONE of these → EXIT the trade:

    1. DELTA DIVERGENCE:
        You are LONG but CVD is making lower lows
        = buyers are trying but losing ground
        "The pressure has shifted, get out before SL"

    2. OPPOSING STACKED IMBALANCES:
        You are LONG but 3+ consecutive price bins show
        sell-side imbalance (sellers dominating at multiple levels)
        = institutional selling pressure building against you

    3. VWAP RECLAIM AGAINST YOU:
        You are LONG and price drops back below VWAP
        with volume (not just a wick, a close below)
        = the fair value has shifted against your trade

    4. NO FOLLOW-THROUGH:
        Entry was triggered but within 5-10 candles:
            - No new high (for longs) / no new low (for shorts)
            - Volume declining, not expanding
            - "The trade should work immediately or not at all"

    5. SPREAD BLOWOUT:
        Option bid-ask spread widens to > 3% of premium
        = liquidity is leaving, something is wrong
        Exit at market before it gets worse

    NSE Proxy Implementation:
        Delta divergence → estimate from candle-level CVD
        Stacked imbalances → not available, use volume decline instead
        VWAP reclaim → directly observable
        No follow-through → directly observable (candle count + range)
        Spread blowout → directly observable from option chain

    CRITICAL DIFFERENCE FROM STOP LOSS:
        Stop loss = price-based, mechanical safety net
        Abort signal = behavior-based, proactive exit

        Abort signals trigger EXIT before the stop loss is hit.
        This is how Fabio keeps average losses small:
        "The average losing trade is $600" when the stop was $2,000
        because most losses are ABORTED early, not stopped out.
```

---

## Part B: NSE Options Implementation Guide

### B1. Instrument Selection

```
UNDERLYING: NIFTY 50 or BANKNIFTY (NIFTY preferred for liquidity)

OPTION TYPE SELECTION:

    For Trend Model (buying directional moves):
        Buy ATM or 1-strike OTM Call/Put
        Why: highest delta exposure for directional move
        Premium range: ₹150-300 (sweet spot for risk management)

        For LONG (expecting up): BUY CE (Call)
        For SHORT (expecting down): BUY PE (Put)

    For Mean Reversion Model (fade back to POC):
        Buy ATM Call/Put (same logic)
        These moves are smaller → need higher delta

    NEVER use:
        - Deep OTM options (delta too low, premium decay kills you)
        - Options with < 2 days to expiry (theta crush)
        - Weekly expiry on Wednesday/Thursday (theta acceleration)

    EXPIRY SELECTION:
        Preferred: current week expiry if Monday/Tuesday
        Preferred: next week expiry if Wednesday-Friday
        Minimum: 3 trading days to expiry
        "I don't want that time decay eats my premium while
         I wait for the setup" [adapted principle]

STRIKE SELECTION FORMULA:
    spot_price = current NIFTY/BANKNIFTY spot
    atm_strike = round(spot_price / strike_interval) × strike_interval

    For NIFTY: strike_interval = 50
    For BANKNIFTY: strike_interval = 100

    Trade ATM or first OTM:
        For LONG (CE): atm_strike or atm_strike + 50 (NIFTY)
        For SHORT (PE): atm_strike or atm_strike - 50 (NIFTY)

    Check option liquidity:
        bid_ask_spread <= 2% of premium
        OI > 10 lakh (NIFTY) or > 5 lakh (BANKNIFTY)
        Volume today > 50,000 contracts
```

### B2. Volume Profile on Underlying (NOT on Options)

```
CRITICAL: Build the volume profile on the UNDERLYING (NIFTY/BANKNIFTY spot or futures).
          NOT on option premium charts.

    Why: Options have their own supply/demand dynamics (theta, gamma).
         The AMT framework is about the UNDERLYING's auction process.

    Profile Data Source:
        NIFTY/BANKNIFTY futures (preferred, actual exchange volume)
        OR NIFTY/BANKNIFTY spot (acceptable, derived)

    Profile Period:
        Previous session: yesterday's 09:15-15:30 candles
        Current session: today's candles so far (developing)
        Impulse leg: specific displacement candles only

    Timeframe for candles:
        1-minute candles for building volume profile (more data points)
        5-minute candles for reading price action / identifying setups
        Fabio uses "40 range" chart ≈ close to 5-min for execution

    Profile Resolution:
        NIFTY: bin_size = 5 points (100-200 bins per session)
        BANKNIFTY: bin_size = 10-15 points
```

### B3. Mapping Order Flow to NSE Observable Data

```
Fabio uses order flow (tape, footprint, big trades).
NSE doesn't provide tick-by-tick order flow to retail.

AVAILABLE PROXIES:

1. VOLUME (replacement for "big trades" / "bubbles"):
    - Per-candle volume from exchange
    - Relative volume: current vs 20-period average
    - Volume spike = potential absorption or aggression

2. OPEN INTEREST (OI) — NSE's UNIQUE ADVANTAGE:
    NSE publishes OI data per strike every 3 minutes.
    This is MORE granular than what futures traders get.

    OI interpretation (Fabio's "absorption" in OI terms):

    Price DOWN + OI UP = new SHORT positions being built (bearish)
    Price DOWN + OI DOWN = old LONGS closing (less bearish, potential bottom)
    Price UP + OI UP = new LONG positions being built (bullish)
    Price UP + OI DOWN = old SHORTS closing (short squeeze, less sustainable)

    "Absorption" in OI terms:
        Price pushing down but OI in PEs DECREASING
        = sellers hitting but positions are closing, not new conviction
        = equivalent of "aggressive sellers being absorbed"

3. PUT-CALL RATIO (PCR) — Directional Sentiment:
    PCR = Put OI / Call OI (for the current expiry)

    PCR > 1.2: bullish sentiment (more puts being written = support)
    PCR < 0.8: bearish sentiment (more calls being written = resistance)
    PCR 0.8-1.2: neutral / balanced

    Change in PCR matters more than absolute level:
        PCR rising = sentiment turning bullish
        PCR falling = sentiment turning bearish

4. MAX PAIN — Market Maker "Fair Value":
    max_pain_strike = strike where total OI loss for option writers is minimum
    This acts like a "POC" for the options market.
    Price tends to gravitate toward max pain near expiry.

5. OPTION CHAIN OI DISTRIBUTION — "Volume Profile of Options":
    Map OI by strike price → creates its own "volume profile"
    High OI at a CE strike = resistance (call writers defending)
    High OI at a PE strike = support (put writers defending)

    This is the NSE equivalent of Fabio's "protection levels"
    and "walls" that he references throughout the transcript.

6. DELTA/CVD PROXY:
    Candle-level estimation:
        buy_volume = volume × (0.5 + 0.5 × (close-open)/(high-low)) if close > open
        sell_volume = volume - buy_volume
        candle_delta = buy_volume - sell_volume
        CVD = cumulative sum of candle_delta
```

### B4. Complete Signal Flow for NSE Options

```
EVERY CANDLE (5-min on underlying):

    ┌────────────────────────────────────────────────┐
    │ 1. UPDATE VOLUME PROFILE (on underlying)       │
    │    → POC, VAH, VAL, LVNs, HVNs                │
    │    → Mark "big trade levels" (vol > 3× avg)    │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │ 2. UPDATE VWAP + BANDS (Rule 13)               │
    │    → Session VWAP, ±1σ, ±2σ, ±3σ              │
    │    → BIAS: above VWAP = bullish, below = bear  │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │ 3. UPDATE NSE OPTION PROXIES                   │
    │    → OI changes, PCR, max pain, OI distribution│
    │    → Volume relative to average                 │
    │    → Delta estimate from candle structure       │
    │    → CVD (cumulative volume delta)              │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │ 4. SESSION FILTER                              │
    │    Phase 1 (09:15-09:30): SKIP                 │
    │    Phase 2 (09:30-11:30): ALL MODELS ACTIVE    │
    │    Phase 3 (11:30-14:00): REVERSION ONLY       │
    │    Phase 4 (14:00-15:15): ALL MODELS ACTIVE    │
    │    Phase 5 (15:15-15:30): EXIT ONLY            │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │ 5. CONSECUTIVE LOSS CHECK (Rule 9 + 15)        │
    │    IF losses >= 3 AND session_pnl <= 0: STOP   │
    │    IF losses >= 5 AND session_pnl > 0: STOP    │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │ 6. MARKET STATE GATE                           │
    │    Balanced / Imbalanced / Transitioning        │
    │    (using VP on underlying + OI changes)        │
    │    IF contraction detected → skip trend model   │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │ 7. MODEL SELECTION                             │
    │    IMBALANCED → Trend Continuation              │
    │    BALANCED/Failed breakout → Mean Reversion    │
    │    Compression post-expansion → Momentum Squeeze│
    │    + VWAP bias must align with model direction  │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │ 8. LOCATION GATE                               │
    │    Price at VAL/VAH/LVN on underlying?          │
    │    + Near a high-OI strike (wall alignment)?    │
    │    + Near a "big trade level" (Rule 14)?        │
    │    + VWAP band proximity check (Rule 13)        │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │ 9. CONFIRMATION GATE (adapted for NSE)         │
    │                                                 │
    │    Sub-score 1: Option Spread                   │
    │      bid_ask_spread <= 2% of premium            │
    │                                                 │
    │    Sub-score 2: Volume Impulse                  │
    │      underlying volume >= 1.5× 20-period avg    │
    │                                                 │
    │    Sub-score 3: OI Pressure                     │
    │      For LONG: OI in PEs increasing at support  │
    │        (put writers adding = bullish)            │
    │      For SHORT: OI in CEs increasing at resist  │
    │        (call writers adding = bearish)           │
    │                                                 │
    │    Sub-score 4: CVD alignment (Rule 17)         │
    │      CVD trending in trade direction             │
    │                                                 │
    │    Pass if >= 2 of 4 sub-scores pass            │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │10. DYNAMIC RISK SIZING (Rule 15)               │
    │    Phase 1: 0.25% (start of day / after loss)  │
    │    Phase 2: 0.35% + 20% session profit         │
    │    Phase 3: 0.40% (momentum day, 2+ wins)      │
    │    HARD CAP: never exceed 0.50%                 │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │11. OPTION SELECTION                            │
    │    ATM or 1-strike OTM                          │
    │    Check: liquidity, spread, OI, expiry         │
    │    Compute: lots based on dynamic risk sizing   │
    │    Theta cost check: holding_cost < 20% of TP   │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │12. EXECUTION                                   │
    │    Scale in: 40% → 30% → 30%                   │
    │    Stop in UNDERLYING terms (not premium)       │
    │    Move to BE ASAP (Rule 5)                     │
    │    Take profit at POC/target (Rule 6)           │
    └──────────────────┬─────────────────────────────┘
                       │
    ┌──────────────────▼─────────────────────────────┐
    │13. POST-ENTRY: ABORT MONITOR (Rule 17)         │
    │    Every candle while in trade, check:          │
    │    □ Delta divergence → EXIT                    │
    │    □ VWAP reclaim against bias → EXIT           │
    │    □ No follow-through (5-10 candles) → EXIT    │
    │    □ Spread blowout (> 3%) → EXIT               │
    │    □ Volume declining → tighten stop             │
    │                                                 │
    │    After +1.5R: trail stop to VWAP band         │
    └────────────────────────────────────────────────┘
```

### B5. Stop Loss: Underlying-Based vs Premium-Based

```
CRITICAL DESIGN DECISION:

    Stop loss is defined on the UNDERLYING price, NOT on option premium.

    Why:
        Option premium fluctuates due to IV, theta, gamma effects.
        Fabio's model is about WHERE the underlying is trading.
        "Below this level I don't want to be long" = underlying level.

    Implementation:
        underlying_stop = VAL - buffer (for longs) in NIFTY points
        When NIFTY hits underlying_stop → sell the option at market

    Premium-based monitoring (secondary):
        max_premium_loss = initial_premium × 0.30 (30% of premium)
        If option premium drops 30% due to IV crush (even if underlying
        hasn't hit stop): EXIT as a safety net.

    Example:
        NIFTY at 24,800 (at VAL)
        Buy 24,800 CE at ₹200
        Underlying stop: 24,770 (VAL - 30 pts buffer)
        Premium safety stop: ₹140 (30% loss on premium)

        Exit when EITHER is hit (whichever first)
```

### B6. Theta Management (Options-Specific)

```
Fabio trades futures (no time decay). Options have theta.

THETA RULES:

    1. Time of day matters:
        Morning (09:30-11:30): theta is slowest → best time for options
        Afternoon (14:00-15:15): theta accelerating → need faster moves
        Last 30 min: theta at maximum → DO NOT hold

    2. Expiry day rules:
        On expiry day (Thursday):
            Only trade in Phase 2 (09:30-11:30)
            Use NEXT week expiry if entering after 11:30
            Premium decay is brutal after 12:00 on expiry day
            "Weekly expiry on Thursday = theta kills you"

    3. IV crush risk:
        After major events (RBI policy, budget, election results):
            IV drops → premiums collapse even if direction is right
            Reduce position size by 50% around events
            OR use spreads (bull call spread / bear put spread)

    4. Maximum holding time per trade:
        Scalp model (Fabio's primary): < 30 minutes
        Momentum model: < 2 hours
        If trade hasn't worked in 2 hours: EXIT regardless
        "Getting from A to B... this probability in ticks is contained
         and distributed through days"

    5. Theta cost calculation:
        daily_theta = approximate theta from option chain
        per_minute_theta = daily_theta / 375  (375 trading minutes)
        holding_cost = per_minute_theta × expected_holding_minutes × lots × lot_size

        IF holding_cost > 20% of expected profit:
            Trade is NOT worth taking (theta eats the edge)
```

### B7. Option-Chain "Wall" Integration (NSE Unique Edge)

```
This is the NSE adaptation of Fabio's "big trades" and "protection levels."

OI WALL DETECTION:

    Scan the option chain for strikes with unusually high OI:

    For each strike:
        ce_oi = Call OI at this strike
        pe_oi = Put OI at this strike
        total_oi = ce_oi + pe_oi
        avg_oi = average OI across all strikes

    CALL WALL (resistance):
        ce_oi > 3 × avg_ce_oi → strong call writing = resistance
        Price level: this strike is the "seller protection level"

    PUT WALL (support):
        pe_oi > 3 × avg_pe_oi → strong put writing = support
        Price level: this strike is the "buyer protection level"

    Integration with Fabio model:
        VP-based VAH aligns with CE wall strike → VERY STRONG resistance
        VP-based VAL aligns with PE wall strike → VERY STRONG support
        When both VP level and OI wall agree: AAA setup confidence increases

    Change in OI walls (real-time):
        If PE wall at 24,500 is GROWING: support strengthening → bullish
        If PE wall at 24,500 is SHRINKING: support weakening → watch out
        "What they are doing is that these buyers are trying to protect it"
        = put writers adding OI at support = they are "protecting" the level

    This is EQUIVALENT to Fabio watching:
        "Big buy aggression hitting right at that LVN"
        = In NSE terms: put writers aggressively adding OI at support level
          while price tests that level
```

### B8. Day-of-Week Filters

```
Fabio discovered through statistical testing:
    "On Friday you always lose money... in four weeks of the month
     three Friday you lose. Remove Friday."

NSE EQUIVALENT FILTERS (to be validated with your data):

    EXPIRY DAY (Thursday):
        High gamma, high theta, erratic moves
        Reduce position size by 50%
        Only trade Phase 2 (09:30-11:30)
        Use next week expiry options

    FRIDAY:
        Often low volume, weekend positioning
        Fabio removes it entirely for NASDAQ
        For NSE: consider removing or reducing size

    MONDAY:
        Gap risk from weekend events
        Wait longer in Phase 1 (extend to 09:45)
        Let the gap resolution play out

    RBI POLICY DAYS:
        Similar to "Trump tweet" days in the transcript
        "Market condition like this is the tweet... the market
         condition that I'm used to trade is this one like you
         build you accumulate you expand"
        Pre-event: DO NOT trade
        Post-event: wait for first balance to form, then trade normally

    BUDGET DAY / ELECTION RESULTS:
        No trading. Full stop.
        "Market makers can lose the profit of the month because
         liquidity completely disappear"

    VALIDATE WITH YOUR OWN DATA:
        Export trades → group by day of week → compare win rates
        "I export all the data I put in Python... you can know
         everything about your trading history"
```

---

## Part C: Implementation Checklist for backend_v2

### Phase 1 Changes (Single Symbol → Options-Aware)

```
□ Volume profile computed on UNDERLYING (not option chart)
□ Session phases configured for NSE (09:15-15:30 IST)
□ Option chain data source integrated (NSE API or broker API)
□ OI wall detection module added
□ PCR calculation module added
□ Strike selection logic implemented
□ Theta decay estimator added
□ Stop loss in underlying terms (with premium safety net)
□ Expiry-aware sizing (reduce on expiry day)
```

### Phase 2 Changes (Risk Engine → Options-Specific)

```
□ Theta cost validation (reject if theta > 20% of expected profit)
□ IV crush filter (reduce size around events)
□ Expiry selection logic (min 3 days to expiry)
□ Bid-ask spread check on option (reject if > 2%)
□ Liquidity check on option (min OI, min volume)
□ Day-of-week filters (configurable per instrument)
□ Session phase enforcement (no trades in Phase 1/5)
```

### Phase 3 Changes (Confirmation Gate → OI-Enhanced)

```
□ Replace "spread tightness" with option bid-ask spread
□ Replace "pressure proxy" with OI change direction
□ Add OI wall alignment bonus to location gate
□ Add PCR trend as supplementary signal
□ Add max pain proximity as additional context
□ Add CVD alignment as 4th confirmation sub-score
```

### Phase 4 Changes (New Rules 13-17)

```
□ VWAP calculator (session VWAP + ±1σ/2σ/3σ bands on underlying)
□ VWAP bias filter integrated into model selection gate
□ VWAP band trailing stop logic (after +1.5R, trail to nearest band)
□ Big trade level detector (volume > 3× 20-period avg → mark level)
□ OI spike level detector (OI change > 2× avg → mark strike as level)
□ Intraday compounding engine (phase 1/2/3 risk scaling)
□ Session P&L tracker for dynamic risk adjustment
□ Consecutive loss counter with circuit breaker (3-loss / 5-loss rules)
□ Trade abort signal monitor (5 abort conditions checked every candle)
□ Delta divergence detector (CVD lower lows while price holds)
□ No-follow-through detector (range + volume declining over N candles)
□ Spread blowout alert (bid-ask > 3% of premium → force exit)
```

### Phase 5 Changes (Pre-Session Automation)

```
□ Previous session profile auto-builder (POC, VAH, VAL from yesterday)
□ Profile shape classifier (P-shape / b-shape / D-shape)
□ Gap detector (current open vs previous close)
□ Auto-mark key levels (yesterday's VP + weekly VP + OI walls)
□ Daily narrative generator (bias suggestion based on profile shape + gap)
□ Event calendar integration (RBI, expiry, budget day → auto-filter)
```

### Data Structures

```python
@dataclass
class OptionSelection:
    underlying: str          # "NIFTY" or "BANKNIFTY"
    strike: int              # e.g., 24800
    option_type: str         # "CE" or "PE"
    expiry: date             # e.g., 2026-02-19
    premium: float           # current premium
    delta: float             # option delta
    theta: float             # daily theta decay
    iv: float                # implied volatility
    bid_ask_spread: float    # in rupees
    oi: int                  # open interest
    volume: int              # today's volume

@dataclass
class OIWall:
    strike: int
    wall_type: str           # "CALL_WALL" (resistance) or "PUT_WALL" (support)
    oi: int
    oi_change: int           # change in last interval
    strength: float          # oi / avg_oi (> 3 = strong wall)

@dataclass
class NSEConfirmation:
    spread_ok: bool          # option bid-ask <= 2%
    volume_ok: bool          # underlying volume >= 1.5× avg
    oi_pressure_ok: bool     # OI aligns with trade direction
    pcr_aligned: bool        # PCR trend supports direction
    wall_aligned: bool       # OI wall at same level as VP level
    bundle_score: int        # count of passed sub-scores
    passed: bool             # bundle_score >= 2

@dataclass
class ThetaCheck:
    daily_theta: float       # per unit per day
    expected_hold_minutes: int
    holding_cost: float      # theta × time × lots × lot_size
    expected_profit: float   # target - entry in premium terms × lots × lot_size
    theta_ratio: float       # holding_cost / expected_profit
    viable: bool             # theta_ratio < 0.20

@dataclass
class VWAPState:
    vwap: float              # session VWAP price
    sigma: float             # standard deviation from VWAP
    band_1_upper: float      # VWAP + 1σ
    band_1_lower: float      # VWAP - 1σ
    band_2_upper: float      # VWAP + 2σ
    band_2_lower: float      # VWAP - 2σ
    band_3_upper: float      # VWAP + 3σ
    band_3_lower: float      # VWAP - 3σ
    bias: str                # "BULLISH" / "BEARISH" (price vs VWAP)
    extension: str           # "NORMAL" / "EXTENDED" / "EXTREME"

@dataclass
class BigTradeLevel:
    price: float             # price where big trade occurred
    timestamp: datetime      # when it occurred
    volume: float            # volume of the candle
    volume_ratio: float      # volume / 20-period avg (must be > 3×)
    direction: str           # "BUY" / "SELL" (estimated from candle)
    still_valid: bool        # False if price has traded through it 3+ times

@dataclass
class CompoundingState:
    phase: int               # 1 (conservative), 2 (cushion), 3 (momentum)
    base_risk_pct: float     # 0.25% baseline
    current_risk_pct: float  # dynamically adjusted (0.25-0.50%)
    session_pnl: float       # running P&L for the session
    consecutive_wins: int    # for phase advancement
    consecutive_losses: int  # for circuit breaker
    lots_allowed: int        # computed from current risk
    trading_halted: bool     # True if circuit breaker triggered

@dataclass
class AbortSignal:
    delta_divergence: bool   # CVD lower lows while price holds
    vwap_reclaim: bool       # price reclaims VWAP against trade bias
    no_follow_through: bool  # no new high/low in N candles + vol declining
    spread_blowout: bool     # bid-ask > 3% of premium
    volume_declining: bool   # volume < 50% of entry candle volume
    should_abort: bool       # True if ANY of the above is True
    should_tighten: bool     # True if volume_declining (not full abort)

@dataclass
class DailyNarrative:
    prev_poc: float          # yesterday's POC
    prev_vah: float          # yesterday's VAH
    prev_val: float          # yesterday's VAL
    profile_shape: str       # "P" / "b" / "D"
    gap_pct: float           # (open - prev_close) / prev_close × 100
    bias: str                # "TREND_UP" / "TREND_DOWN" / "RANGE"
    bias_reason: str         # human-readable reason for bias
    key_levels: list         # sorted list of all pre-marked levels
    event_filter: str        # "NORMAL" / "REDUCED" / "NO_TRADE"
```

---

## Part D: Key Differences Summary — Futures vs NSE Options

| Aspect | Fabio's Futures | NSE Options |
|--------|----------------|-------------|
| Time Decay | None | Theta — must account for holding cost |
| Holding Period | Unlimited intraday | Minimize — theta accelerates |
| Stop Loss | Direct price-based | Underlying-based + premium safety net |
| "Absorption" Signal | Tape/footprint/big trades | OI changes + volume + candle structure |
| "Protection Level" | Visible buy/sell walls on DOM | OI walls (high OI at strike) |
| Scaling In | Add contracts at same price | Add lots (same or different strike) |
| Liquidity | Very high (NQ futures) | Check per-strike (varies hugely) |
| Session | NY session (US hours) | NSE 09:15-15:30 IST |
| Expiry | Quarterly (far away) | Weekly (Thursday) — critical factor |
| Cost | Commission only | Premium + spread + theta |
| Leverage | Built into futures | Built into options (delta) |
| "CVD" Proxy | Actual CVD from exchange | Estimated from candle + OI data |
| "Big Trades" | Visible on tape, used as levels | Volume spike levels + OI spike levels |
| Maximum Holding | "Till POC" (could be hours) | Stricter: < 2 hours typical |
| Day Filters | "Remove Friday" | Remove expiry-day afternoon + Fridays |
| VWAP Usage | Direct from exchange, trail at bands | Calculated from candles, same trailing |
| Abort Signals | Delta flip, stacked imbalances | CVD proxy + VWAP reclaim + spread |
| Compounding | Add contracts from session profit | Add lots from session profit (capped) |
| Pre-Session | Mark levels on Deep Charts | Auto-build from yesterday's profile + OI |

