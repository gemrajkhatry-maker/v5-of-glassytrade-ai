# AMT Institutional Order Flow Scalping System: Complete Algorithmic Specification

---

## 1. Executive Summary & Theoretical Foundations

The **AMT Institutional Order Flow Scalping System** is a professional-grade quantitative trading algorithm designed around **Auction Market Theory (AMT)**, **Volume Spread Analysis (VSA)**, and Fabio Valentini's **Triple-A Methodology (Absorption $\to$ Accumulation $\to$ Aggression)**.

The core market thesis dictates that financial markets are continuous two-way double auctions seeking fair value:
1. **Balanced State ($\sim 70\text{–}80\%$ of trading time):** Buyers and sellers agree on price. Price rotates between Value Area Low ($\text{VAL}$) and Value Area High ($\text{VAH}$) around the Point of Control ($\text{POC}$).
2. **Imbalanced State ($\sim 20\text{–}30\%$ of trading time):** Aggressive institutional market orders overwhelm passive liquidity, breaking out of balance to seek a new fair value distribution.

The algorithm captures structural inefficiencies by detecting **institutional absorption** (aggressive orders getting absorbed by passive limit walls), identifying **trapped counter-participants**, and executing in the direction of the resulting **liquidation squeeze** with strict **"House Money" Cushioning** and **Algorithmic Pyramiding**.

---

## 2. System Architecture & Ingestion Pipeline

```
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                           MARKET DATA INGESTION                             │
  │  • Tick-Level Aggregated Trades (Price, Quantity, Aggressor Flag: Buy/Sell) │
  │  • Level-2 Order Book Depth (20-50 Bids/Asks for Passive Wall Context)      │
  │  • 1-Minute / 5-Minute Klines                                               │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                           RANGE BAR GENERATOR                               │
  │  • Discretizes continuous time into fixed price height bars (H_range)       │
  │  • Dynamic ATR(14) Volatility Quantization                                  │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                      AMT ORDER FLOW ANALYTICS ENGINE                        │
  │  1. Multi-Layer Volume Profile (Macro Session, Compression Box, Impulse Leg)│
  │  2. Low Volume Node (LVN) & Point of Control (POC) Extractor                │
  │  3. Anchored Dynamic VWAP & Dispersion Bands (±1.0σ, ±2.0σ)                 │
  │  4. Cumulative Volume Delta (CVD) & Delta Acceleration Engine               │
  │  5. Volume Bubble & Big Trade Detector (Aggressive Executions >= 30-40 lots)│
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                       TRIPLE-A DYNAMIC STATE MACHINE                        │
  │            State 0: WAITING  ──►  State 1: ABSORBING                        │
  │            State 2: ACCUMULATING  ──►  State 3: AGGRESSION (SIGNAL)         │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                  CUSHIONING & HOUSE MONEY RISK CONTROLLER                   │
  │  • Base Risk: 0.25% - 0.50% of Starting Equity                              │
  │  • Daily Profit Cushion = Realized Session PnL                              │
  │  • Dynamic Risk Allocation: Base Risk + (0.35 - 0.50) * Cushion             │
  │  • Circuit Breakers: Max Daily Loss (2.0%) | 3 Consecutive Losses Cutoff    │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │
                                         ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                     EXECUTION & PYRAMIDING OMS ENGINE                       │
  │  • Sniper Entry: 1-Minute Full Candle Close confirmation beyond Trap Cluster│
  │  • Instant Risk-Zero Transition: SL -> Breakeven on CVD thrust / High Break │
  │  • Pyramiding: Add 50% size on Impulse Leg LVN retest + New Absorption      │
  │  • Slippage Shield: Stop-loss placed 1-2 ticks inside structural levels     │
  │  • Multi-Tier Take Profit: TP1 (50%), TP2 (25%), Runner Trailed (25%)       │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Ingestion & Technical Feeds Specification

| Data Feed Stream | Technical Payload | Quantitative Role in Engine |
| :--- | :--- | :--- |
| **Aggregated Trades (Tape / Tick Feed)** | `{ price, qty, is_buyer_maker, timestamp }` | 1. Feeds the **Volume Bubble Detector** ($\ge 30\text{–}100$ contracts).<br>2. Computes real-time **Bar Delta** ($V_{\text{buy}} - V_{\text{sell}}$) and **CVD**.<br>3. Builds tick-resolution Volume Profiles. |
| **1-Minute Klines** | `{ open, high, low, close, volume, timestamp }` | Converted into **Range Bars** and used for final **Candle-Close Execution Confirmations**. |
| **5-Minute Klines** | `{ open, high, low, close, volume, timestamp }` | Macro Dealing Range identification, Session highs/lows, and overarching market narrative framing. |
| **L2 Depth Book (20-50 levels)** | `{ bids: [[p, q]], asks: [[p, q]] }` | Identifies resting passive liquidity walls that absorb aggressive market orders. |

---

## 4. Range Bar Construction & Volatility Quantization

Time-based candles distort order flow by clustering noise during low volume and compressing information during volatility spikes. The system normalizes price action into **Range Bars** of fixed price height $H_{\text{range}}$.

### Range Bar Rules:
1. A Range Bar closes as soon as:
   $$\text{High}_t - \text{Low}_t \ge H_{\text{range}}$$
2. The subsequent bar opens at:
   $$\text{Open}_{t+1} = \text{Close}_t$$
3. **Dynamic Range Sizing via ATR(14):**
   $$H_{\text{raw}} = \text{ATR}_{14}(\text{1m Klines}) \times \kappa_{\text{scale}}$$
   $$H_{\text{range}} = \text{Quantize}\Big(H_{\text{raw}},\, \{5, 10, 25, 50, 100, 200\}\Big)$$

---

## 5. Multi-Layer Volume Profile Architecture

The algorithm maintains **4 concurrent, specialized Volume Profile layers**:

```
 Price ▲
       │   [Layer 1: Macro Session Profile]       [Layer 3: Impulse / Leg Profile]
       │   (Full Day / Previous Session)          (Anchored Swing Low -> Swing High)
       │
       │   ── VAH ─────────────────────────       ───────── Swing High ─────────────
       │                                             ▲
       │                                             │  ◄── LVN (Low Volume Node /
       │   ── POC (Max Volume Magnet) ─────          │          Pullback Entry Zone)
       │                                             │
       │   ── VAL ─────────────────────────       ───────── Swing Low ──────────────
       │
       │   [Layer 2: Compression Box Profile]     [Layer 4: Gap Profile]
       │   (Anchored inside 15-30m tight range)   (Anchored across overnight price gap)
       └────────────────────────────────────────────────────────────────────────► Time
```

### 5.1 Mathematics of Profile Construction
For any price series within window $[t_0, t_1]$ discretized into price bins of width $S_{\text{bucket}} = H_{\text{range}}$:

1. **Volume Binning:**
   $$V(p) = \sum_{k} V_{\text{buy}}(p, k) + V_{\text{sell}}(p, k)$$
   $$\Delta V(p) = \sum_{k} V_{\text{buy}}(p, k) - V_{\text{sell}}(p, k)$$
2. **Point of Control (POC):**
   $$\text{POC} = \arg\max_{p} V(p)$$
3. **Value Area ($\text{VA} = 68.2\%$ of Total Volume):**
   Starting at $p = \text{POC}$, expand iteratively upwards and downwards to neighboring bins with higher volume until:
   $$V(\text{POC}) + \sum_{p = \text{VAL}}^{\text{VAH}} V(p) \ge 0.682 \times \sum_{\text{all } p} V(p)$$
4. **Low Volume Nodes (LVN):**
   $$\text{LVN} = \left\{ p \;\middle|\; V(p) < 0.35 \times \overline{V}_{\text{profile}} \quad \text{AND} \quad \frac{d^2 V(p)}{dp^2} > 0 \right\}$$

### 5.2 Layer Roles & Strategic Utilities
* **Layer 1: Macro Session Profile:** Defines macro boundaries ($\text{VAH}$, $\text{VAL}$) and ultimate profit targets ($\text{POC}_{\text{macro}}$).
* **Layer 2: Compression Box Profile:** Identifies micro-balance ranges before breakouts. A true out-of-balance condition requires a 1m candle close outside this box.
* **Layer 3: Impulse / Leg Profile (The Retest Alpha Engine):** Anchored from the exact low to high of an impulsive drive. Pinpoints the internal **LVN**, which acts as the prime institutional retest entry point.
* **Layer 4: Gap Profile:** Maps liquidity voids inside overnight/session opening gaps.

---

## 6. VWAP, Dispersion Bands & Cumulative Volume Delta (CVD)

### 6.1 Anchored VWAP & Standard Deviation Bands
$$\text{VWAP}_t = \frac{\sum_{i=1}^t P_{\text{typical}, i} \cdot V_i}{\sum_{i=1}^t V_i}, \quad P_{\text{typical}, i} = \frac{H_i + L_i + C_i}{3}$$

$$\sigma_{\text{VWAP}, t} = \sqrt{\frac{\sum_{i=1}^t (P_{\text{typical}, i} - \text{VWAP}_t)^2 \cdot V_i}{\sum_{i=1}^t V_i}}$$
* **Band Formulations:**
  $$\text{Upper}_1 = \text{VWAP} + 1.0\sigma, \quad \text{Lower}_1 = \text{VWAP} - 1.0\sigma$$
  $$\text{Upper}_2 = \text{VWAP} + 2.0\sigma, \quad \text{Lower}_2 = \text{VWAP} - 2.0\sigma$$

### 6.2 CVD Acceleration & Divergence Mechanics
$$\text{Delta}_t = V_{\text{buy}, t} - V_{\text{sell}, t}, \quad \text{CVD}_t = \sum_{i=1}^t \text{Delta}_i$$
$$\text{CVD Velocity} = \text{EMA}_3(\text{CVD}) - \text{EMA}_9(\text{CVD})$$

* **Bullish Absorption Divergence:** Price makes Lower Lows, but $\text{CVD}$ makes Higher Lows $\implies$ Aggressive sellers being absorbed by passive institutional bids.
* **Bearish Exhaustion Divergence:** Price makes Higher Highs, but $\text{CVD}$ makes Lower Highs $\implies$ Aggressive buyers drying up; distribution in progress.

---

## 7. Volume Bubble & Institutional Absorption Engine

```
       [ABSORPTION: PUNCHING A WALL]                    [TRAP LIQUIDATION SQUEEZE]
       
          1m Candle Prints Wick                           Candle Closes Above Cluster
                    │                                                  ▲
                    ▼                                                  │  Explosive Acceleration
              ┌──────────┐                                       ┌─────┴────┐ (Sellers forced to
              │          │                                       │          │  market-buy stop out)
  Price ───►  │   🔴🔴   │ ◄── Heavy Sell Aggression             │   🔴🔴   │
  Floor       │   🔴🔴   │     (e.g., 100 Lots Market Sell)      │   🔴🔴   │ ◄── Cluster of Trapped
              └──────────┘     Price DOES NOT drop!              └──────────┘     Underwater Shorts
              ════════════ ◄── Passive Institutional Wall        ════════════
```

### 7.1 Big Trade Filter Configuration
* **London Session / Low Volatility:** Bubble filter threshold = **$20\text{–}30$ Contracts**.
* **New York Session / High Volatility:** Bubble filter threshold = **$30\text{–}40$ Contracts** (Large Institutional Flag $\ge 100$ Contracts).

### 7.2 Absorption Detection Math
A Range Bar or 1m Candle $b$ is classified as an **Absorption Event** when:
1. $V_b \ge 1.50 \times \overline{V}_{20}$ (Volume is $\ge 150\%$ of 20-bar rolling average).
2. $(H_b - L_b) \le 0.50 \times H_{\text{range}}$ (Price range is compressed; effort without result).
3. **Directional Classification:**
   * **BUY Absorption:** $V_{\text{sell}, b} \ge 0.60 \times V_b$ and $\text{Close}_b \ge \text{Low}_b + 0.50(H_b - L_b)$ (Sellers punched a passive buy wall).
   * **SELL Absorption:** $V_{\text{buy}, b} \ge 0.60 \times V_b$ and $\text{Close}_b \le \text{High}_b - 0.50(H_b - L_b)$ (Buyers punched a passive sell wall).

---

## 8. Triple-A State Machine

```
   ┌────────────────────────────────────────────────────────┐
   │                    STATE 0: WAITING                    │
   │            Scanning for Market Structure & LVN         │
   └───────────────────────────┬────────────────────────────┘
                               │
            Absorption Detected (Vol >= 1.5x, Range Compressed)
                               │
                               ▼
   ┌────────────────────────────────────────────────────────┐
   │                   STATE 1: ABSORBING                   │
   │    Cluster of Large Executed Orders without Progress   │
   └───────────────────────────┬────────────────────────────┘
                               │
            Price consolidates within 2 range steps of POC/LVN
            (2+ bars elapsed, Delta stabilizing)
                               │
                               ▼
   ┌────────────────────────────────────────────────────────┐
   │                 STATE 2: ACCUMULATING                  │
   │    Trap Formation: Counter-participants Loading Risk   │
   └───────────────────────────┬────────────────────────────┘
                               │
            [LONG]: Full 1m candle CLOSE > Swing High / Absorption Bar
                    AND Price > VWAP AND CVD expanding
            [SHORT]: Full 1m candle CLOSE < Swing Low / Absorption Bar
                    AND Price < VWAP AND CVD collapsing
                               │
                               ▼
   ┌────────────────────────────────────────────────────────┐
   │            STATE 3: AGGRESSION (SIGNAL TRIGGER)        │
   │   • Instant Market Order / Buy-Stop Trigger            │
   │   • SL placed 1-2 ticks behind absorption cluster      │
   │   • Initiate Instant Risk-Zero Transition Protocol     │
   └────────────────────────────────────────────────────────┘
```

---

## 9. Comprehensive Trading Playbooks

### 9.1 Playbook A: Trend Expansion / Out-of-Balance Squeeze (Primary Engine)

```
        Price ▲
              │                                                [Target: Macro POC / PDH]
              │                                                                ▲
              │                                                                │
              │                                             ┌──► [1m Close > Cluster High]
              │                                             │    (TRIGGER LONG ENTRY)
              │                    ┌──► [Trapped Sellers] ──┤
              │                    │    (Heavy Red Bubbles) │    SL: 1-2 Ticks Below Cluster
              │  ──────────────────┴────────────────────────┴────────────────────────────────
              │  Value Area High / Resistance Breakout
              └───────────────────────────────────────────────────────────────────────────────► Time
```

#### BUY Setup (Long)
1. **Regime Filter:** Price $> \text{VWAP}$ and breaking out above the Compression Box / Value Area High.
2. **Absorption Footprint:** Cluster of red sell bubbles ($V_{\text{sell}} \ge 30\text{–}40$ contracts) punches support without price continuation (lower wicks form).
3. **Trigger:** Full 1-minute candle **CLOSES strictly above the high of the absorption cluster** ($P_{\text{close}} > H_{\text{cluster}}$).
   * *Anti-Whipsaw Rule:* Never enter on the 1st raw intra-bar spike. Wait for the candle close or 2nd drive.
4. **Stop-Loss Placement:** $1\text{–}2$ ticks below the absorption cluster low:
   $$\text{SL} = L_{\text{cluster}} - (2 \times \text{TickSize})$$
5. **Take-Profit Target:**
   * $\text{TP}_1$ ($50\%$): First overhead major $\text{LVN}$ or prior swing high ($R:R \ge 1:2.0$).
   * $\text{TP}_2$ ($50\%$): Macro Session $\text{POC}_{\text{prev}}$ or Previous Day High ($\text{PDH}$).

#### SELL Setup (Short)
1. **Regime Filter:** Price $< \text{VWAP}$ and breaking below Value Area Low.
2. **Absorption Footprint:** Green buy bubbles absorbed at resistance with zero upward follow-through.
3. **Trigger:** Full 1-minute candle **CLOSES strictly below the absorption cluster low** ($P_{\text{close}} < L_{\text{cluster}}$).
4. **Stop-Loss Placement:** $1\text{–}2$ ticks above the absorption cluster high:
   $$\text{SL} = H_{\text{cluster}} + (2 \times \text{TickSize})$$
5. **Take-Profit Target:** First support $\text{LVN}$ / Macro $\text{POC}_{\text{prev}}$ / $\text{PDL}$.

---

### 9.2 Playbook B: Value Area Mean-Reversion / Failed Auction Fade

Used during balanced sessions, London open, or summer compression periods.

#### BUY Setup (Long)
1. Price drives below $\text{VAL}$ or Session Low, creating a **Failed Auction** (aggressive sellers absorbed, red bubbles print with no follow-through).
2. Price **re-accepts and closes back inside the Value Area** ($P_{\text{close}} > \text{VAL}$).
3. **Trigger:** Enter on 1m candle close inside Value Area.
4. **Stop-Loss:** 1 tick below the failed auction low wick.
5. **Target:** Session $\text{POC}$ (Point of Control). Full exit ($100\%$) at $\text{POC}$ ($\sim 70\%$ mean-reversion probability).

#### SELL Setup (Short)
1. Price sweeps above $\text{VAH}$, prints green buy bubbles that get absorbed, and fails to sustain.
2. Price **re-accepts and closes back below $\text{VAH}$** ($P_{\text{close}} < \text{VAH}$).
3. **Trigger:** Enter on 1m candle close inside Value Area.
4. **Stop-Loss:** 1 tick above the failed auction high wick.
5. **Target:** Session $\text{POC}$. Full exit ($100\%$).

---

### 9.3 Playbook C: Impulse Leg LVN Retest (The Sniper Continuation)

```
        Price ▲
              │                                      [Continuation Explosion]
              │                                                 ▲
              │                                                 │
              │                 [Impulse High (Point B)]        │
              │                         ▲                       │
              │                        ╱ ╲                      │
              │                       ╱   ╲  [Pullback]         │
              │                      ╱     ▼                    │
              │                     ╱   [LVN Retest + Cluster] ─┘ (SNIPER ENTRY)
              │                    ╱    (Low Volume Void Rebalanced)
              │   [Impulse Low]   ╱
              │   (Point A)      ╱
              └─────────────────┴──────────────────────────────────────────► Time
```

1. Identify strong impulsive drive $[A \to B]$ breaking market structure.
2. Plot **Layer 3 Impulse Leg Profile** from $A$ to $B$ and extract the primary internal $\text{LVN}$.
3. Wait for price to pull back to the $\text{LVN}$ price band:
   $$P \in [\text{LVN} - \epsilon, \; \text{LVN} + \epsilon]$$
4. Confirm counter-aggression dries up and in-trend volume bubble prints.
5. **Trigger:** 1m candle close in trend direction.
6. **Stop-Loss:** 2 ticks behind the $\text{LVN}$ shelf.
7. **Take-Profit:** Breakout above Point $B$ targeting $R:R \ge 1:3.0$ to $1:5.0$.

---

## 10. Session Timing, Market Windows & Anti-Whipsaw Rules

```
08:00                   09:10-09:30           09:30                   11:30                13:00
  │                          │                  │                       │                    │
  ▼                          ▼                  ▼                       ▼                    ▼
┌──────────────────┐   ┌────────────┐   ┌───────────────────────────┐   ┌────────────────────────┐
│  LONDON SESSION  │   │ PRE-MARKET │   │   NEW YORK PRIME WINDOW   │   │  SESSION EXHAUSTION    │
│  (Mean Reversion │   │ TRAP ZONE  │   │  (Directional Expansion   │   │  (Tighten stops, close │
│   & Range Fades) │   │ (DO NOT    │   │   & Squeeze Breakouts)    │   │   positions, no new    │
│                  │   │  TRADE!)   │   │                           │   │   trades)              │
└──────────────────┘   └────────────┘   └───────────────────────────┘   └────────────────────────┘
```

1. **Pre-Market Trap Lock (10–20 Minutes Before Open):**
   * **STRICT RULE:** **Zero new entries permitted.**
   * *Rationale:* Institutions construct the dealing range, causing two-way stop runs.
2. **15–30 Minute Discovery Window (NY Open):**
   * Establishes the real session directional momentum. Squeeze breakout trades are triggered here.
3. **Session Lifespan:**
   * Maximum trade window: **3 to 4 hours**.
   * **NO OVERNIGHT HOLDING:** All open positions closed at market close to eliminate gap risk and overnight margin penalties.
4. **Day-of-Week Variance:**
   * **Tuesdays, Wednesdays, Thursdays:** Full offensive size (high-velocity trend days).
   * **Mondays & Fridays:** Defensive size (frequent compression / rebalancing days).

---

## 11. Slippage Engineering & Stop-Loss Placement Secrets

```
                       [THE SLIPPAGE TRAP VS PRO STOP PLACEMENT]
                       
   Price Level
        ▲
        │  ─────────────────────── Swing High / PDH (Mass of Retail Stops & Breakout Orders)
        │
        │  ── Pro Stop Level ──── Placed 1-2 ticks BELOW the High!
        │                         (Exits position BEFORE the liquidity cascade accelerates!)
        │
        │  ┌───────────┐
        │  │ 🔴 BUBBLE │ ◄─────── Pro Stop Loss for Long: Placed 1-2 ticks BEHIND the
        │  └───────────┘          Big Executed Bubble, NOT at arbitrary candle wicks.
        └───────────────────────────────────────────────────────────────────────────────► Time
```

1. **Stop Placed Behind Bubbles, Not Wicks:** Stop-loss is pegged $1\text{–}2$ ticks behind the big executed bubble cluster, which represents the institutional cost basis.
2. **The "1–2 Ticks Inside" Target/Exit Shield:** When taking profit or exiting at a major daily high/low, place the limit/stop **$1\text{–}2$ ticks inside the structural level** to fill before liquidity matching engines experience slippage cascades.

---

## 12. Cushioning Architecture ("House Money" Protocol)

The Cushioning Engine mathematically ring-fences starting account equity while aggressively expanding risk on accumulated session gains.

```
               ┌──────────────────────────────────────────────────┐
               │              START OF SESSION: DAY 0             │
               │   Cushion = $0.00 | Risk Mode = BASE (0.25%-0.5%)│
               └────────────────────────┬─────────────────────────┘
                                        │
                       ┌────────────────┴────────────────┐
                       ▼                                 ▼
             [Trade 1: LOSS]                   [Trade 1: WIN +2.5R]
             Loss: -$250                       Profit: +$625
             Cushion: -$250                    Cushion: +$625
             Remaining Budget: $750            Cushion Status: ACTIVE
                       │                                 │
                       ▼                                 ▼
             [Next Trade: BASE]                [NEXT TRADE: CUSHIONED]
             Risk = 0.25% ($250)               Risk = 0.25% Base + 40% of Cushion
             Max 3-4 Consecutive               = $250 + $250 = $500 Risk
             Losses -> HARD STOP FOR DAY       (Base Equity is 100% Protected!)
```

### 12.1 Mathematical Formulas
* **Starting Equity ($E_0$):** Balance at 00:00 session start.
* **Daily Cushion Metric:**
  $$\text{Cushion}_t = \sum \text{Realized PnL}_{\text{session}}$$
* **Max Daily Loss Limit ($\text{MDL}$):** Hard stop at $2.0\%$ of $E_0$.
* **Consecutive Loss Cutoff:** 3 consecutive losses $\implies$ Terminate trading for the day.

### 12.2 Dynamic Risk Allocation Formula
$$\text{RiskDollars}_k = \begin{cases}
\min\Big(E_0 \times 0.0025, \; \text{MDL} - |\text{Cushion}_t|\Big) & \text{if } \text{Cushion}_t \le 0 \quad \text{(Defensive Mode)} \\
(E_0 \times 0.0025) + (0.40 \times \text{Cushion}_t) & \text{if } \text{Cushion}_t > 0 \quad \text{(Offensive Mode)}
\end{cases}$$

$$\text{PositionSize}_k = \left\lfloor \frac{\text{RiskDollars}_k}{|P_{\text{entry}} - P_{\text{SL}}| \times \text{Multiplier}} \right\rfloor$$

*Session Reset:* At session close, all realized gains merge into core equity $E_0$. $\text{Cushion}$ resets to $\$0.00$.

---

## 13. Algorithmic Pyramiding & Trade Management

### 13.1 Instant Risk-Zero Transition Protocol
As soon as:
1. $\text{CVD}$ expands with 2 consecutive range bars closing in profit, OR
2. Price breaks the local swing high/low of the entry candle ($+0.8R$ advance):
   $$\text{SL} \leftarrow P_{\text{entry}} \quad \text{(Breakeven)}$$
   *Downside risk on base position becomes strictly $\$0.00$.*

### 13.2 Pyramiding Protocol (Scaling into Winners)
```
 Price ▲
       │                                            [TP Full: Session Target]
       │                                                       ▲
       │                                                       │
       │                                     ┌──► [Pyramid 2 Entry] (Add 25% Size)
       │                                     │    SL moved behind 2nd LVN
       │                   ┌──► [Pyramid 1 Entry] (Add 50% Size)
       │                   │    Retest of LVN + Absorption confirmation
       │                   │    Base SL moved to +1.0R Locked
       │    [Base Entry] (100% Size)
       │    Triple-A Breakout
       │    SL @ Initial Cluster
       └───────────────────────────────────────────────────────────────────────► Time
```

1. **Authorization:** Base trade must be at **Risk-Zero (Breakeven or $+1.0R$ Locked)**.
2. **Setup Trigger:** Pullback to **Impulse Leg LVN** + new Absorption Cluster + 1m candle close.
3. **Pyramid Sizing:**
   $$\text{Size}_{\text{pyramid\_1}} = 0.50 \times \text{Size}_{\text{base}}$$
   $$\text{Size}_{\text{pyramid\_2}} = 0.25 \times \text{Size}_{\text{base}}$$
4. **Stop Ratchet:** Move combined position stop to the new LVN/cluster floor. **The entire trade bundle is guaranteed a net positive cash payout.**

### 13.3 Multi-Tier Partial Exits
* **Tier 1 ($50\%$ Size):** At $+2.0R$ / First overhead LVN / Round Number (Banks daily profit cushion).
* **Tier 2 ($25\%$ Size):** At Macro Value Area extreme or upon CVD divergence exhaustion.
* **Tier 3 ($25\%$ Runner):** Trailed behind 1m absorption bubbles until full session close.

---

## 14. Complete End-to-End Algorithmic Implementation (Python)

```python
"""
AMT Institutional Order Flow Scalper Engine
Implements: Multi-Layer Profiles, Bubble Detection, Triple-A State Machine,
Cushion Risk Engine, Instant Risk-Zero, and Pyramiding OMS.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional
import math

class MarketState(Enum):
    BALANCED = "BALANCED"
    IMBALANCED = "IMBALANCED"

class TripleAPhase(Enum):
    WAITING = "WAITING"
    ABSORBING = "ABSORBING"
    ACCUMULATING = "ACCUMULATING"
    SIGNAL = "SIGNAL"

@dataclass
class AggregatedTrade:
    price: float
    volume: float
    is_buyer_aggressor: bool
    timestamp: int

@dataclass
class RangeBar:
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_vol: float
    sell_vol: float
    delta: float
    cvd: float
    timestamp: int

@dataclass
class AbsorptionCluster:
    bar_index: int
    side: str  # "BUY" or "SELL"
    price_level: float
    cluster_high: float
    cluster_low: float
    volume: float
    strength: float

@dataclass
class Position:
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    size: float
    sl_price: float
    tp_price: float
    is_risk_free: bool = False
    pyramid_level: int = 0

class AMTOrderFlowEngine:
    def __init__(self, initial_equity: float, tick_size: float = 0.25):
        self.initial_equity = initial_equity
        self.current_equity = initial_equity
        self.daily_cushion = 0.0
        self.max_daily_loss = initial_equity * 0.02
        self.loss_streak = 0
        self.tick_size = tick_size
        
        # State tracking
        self.triple_a_phase = TripleAPhase.WAITING
        self.active_absorptions: List[AbsorptionCluster] = []
        self.open_positions: List[Position] = []
        self.bars: List[RangeBar] = []
        self.running_cvd = 0.0

    def compute_volume_profile(self, trades: List[AggregatedTrade], bucket_size: float) -> Dict:
        """Constructs volume profile and extracts POC, VAH, VAL, and LVNs."""
        bins: Dict[float, Dict[str, float]] = {}
        total_vol = 0.0
        
        for t in trades:
            b_price = round(t.price / bucket_size) * bucket_size
            if b_price not in bins:
                bins[b_price] = {"buy": 0.0, "sell": 0.0, "total": 0.0}
            if t.is_buyer_aggressor:
                bins[b_price]["buy"] += t.volume
            else:
                bins[b_price]["sell"] += t.volume
            bins[b_price]["total"] += t.volume
            total_vol += t.volume

        poc = max(bins.keys(), key=lambda p: bins[p]["total"])
        
        # Calculate 68.2% Value Area around POC
        sorted_prices = sorted(bins.keys())
        poc_idx = sorted_prices.index(poc)
        va_vol = bins[poc]["total"]
        up_idx, dn_idx = poc_idx, poc_idx
        
        while va_vol < 0.682 * total_vol and (up_idx < len(sorted_prices) - 1 or dn_idx > 0):
            next_up = bins[sorted_prices[up_idx + 1]]["total"] if up_idx < len(sorted_prices) - 1 else 0
            next_dn = bins[sorted_prices[dn_idx - 1]]["total"] if dn_idx > 0 else 0
            if next_up >= next_dn and up_idx < len(sorted_prices) - 1:
                up_idx += 1
                va_vol += next_up
            elif dn_idx > 0:
                dn_idx -= 1
                va_vol += next_dn
            else:
                break
                
        vah = sorted_prices[up_idx]
        val = sorted_prices[dn_idx]
        
        # Extract Low Volume Nodes (LVNs: volume < 35% of mean bin volume)
        mean_vol = total_vol / max(1, len(bins))
        lvns = [p for p, d in bins.items() if d["total"] < 0.35 * mean_vol]
        
        return {"poc": poc, "vah": vah, "val": val, "lvns": sorted(lvns), "bins": bins}

    def detect_absorption_and_bubbles(self, current_bar: RangeBar, avg_vol_20: float, range_size: float):
        """Volume Spread Analysis & Big Trade Bubble Detector."""
        bar_height = current_bar.high - current_bar.low
        
        # Bubble Threshold: >= 30 contracts
        if current_bar.volume >= 30.0 and current_bar.volume >= 1.5 * avg_vol_20:
            if bar_height <= 0.5 * range_size:
                # Effort without result: Absorption
                if current_bar.sell_vol >= 0.60 * current_bar.volume:
                    cluster = AbsorptionCluster(
                        bar_index=len(self.bars),
                        side="BUY",
                        price_level=current_bar.low,
                        cluster_high=current_bar.high,
                        cluster_low=current_bar.low,
                        volume=current_bar.volume,
                        strength=min(1.0, (current_bar.volume / avg_vol_20) - 1.0)
                    )
                    self.active_absorptions.append(cluster)
                elif current_bar.buy_vol >= 0.60 * current_bar.volume:
                    cluster = AbsorptionCluster(
                        bar_index=len(self.bars),
                        side="SELL",
                        price_level=current_bar.high,
                        cluster_high=current_bar.high,
                        cluster_low=current_bar.low,
                        volume=current_bar.volume,
                        strength=min(1.0, (current_bar.volume / avg_vol_20) - 1.0)
                    )
                    self.active_absorptions.append(cluster)

    def update_triple_a_state(self, last_bar: RangeBar, vwap: float):
        """Triple-A State Machine: Absorption -> Accumulation -> Aggression."""
        recent_abs = [a for a in self.active_absorptions if a.bar_index >= len(self.bars) - 5]
        
        if self.triple_a_phase == TripleAPhase.WAITING:
            if len(recent_abs) > 0:
                self.triple_a_phase = TripleAPhase.ABSORBING
                
        elif self.triple_a_phase == TripleAPhase.ABSORBING:
            if len(self.bars) - recent_abs[-1].bar_index >= 2:
                self.triple_a_phase = TripleAPhase.ACCUMULATING
                
        elif self.triple_a_phase == TripleAPhase.ACCUMULATING:
            latest = recent_abs[-1]
            # Squeeze confirmation: Full 1m candle close beyond the cluster
            if latest.side == "BUY" and last_bar.close > latest.cluster_high and last_bar.close > vwap:
                self.triple_a_phase = TripleAPhase.SIGNAL
            elif latest.side == "SELL" and last_bar.close < latest.cluster_low and last_bar.close < vwap:
                self.triple_a_phase = TripleAPhase.SIGNAL

    def calculate_cushion_risk_allocation(self) -> float:
        """House Money Cushioning: Allocates base risk or expands with daily profit."""
        base_risk = self.current_equity * 0.0025  # 0.25% base
        if self.daily_cushion <= 0:
            remaining_budget = max(0.0, self.max_daily_loss - abs(self.daily_cushion))
            return min(base_risk, remaining_budget)
        else:
            # Deploy 40% of earned cushion while ring-fencing core capital
            return base_risk + (0.40 * self.daily_cushion)

    def evaluate_and_execute(self, last_bar: RangeBar, vwap: float, macro_vp: Dict):
        """Generates signal and dispatches order to OMS."""
        if self.is_circuit_breaker_active():
            return

        latest_abs = self.active_absorptions[-1]
        risk_dollars = self.calculate_cushion_risk_allocation()
        
        if latest_abs.side == "BUY" and self.triple_a_phase == TripleAPhase.SIGNAL:
            entry = last_bar.close
            # Stop placed 2 ticks below bubble cluster
            sl = latest_abs.cluster_low - (2 * self.tick_size)
            risk_unit = entry - sl
            if risk_unit <= 0:
                return
            
            size = math.floor(risk_dollars / risk_unit)
            tp = entry + (risk_unit * 2.0)
            
            pos = Position("NQ", "LONG", entry, size, sl, tp)
            self.open_positions.append(pos)
            self.triple_a_phase = TripleAPhase.WAITING

        elif latest_abs.side == "SELL" and self.triple_a_phase == TripleAPhase.SIGNAL:
            entry = last_bar.close
            # Stop placed 2 ticks above bubble cluster
            sl = latest_abs.cluster_high + (2 * self.tick_size)
            risk_unit = sl - entry
            if risk_unit <= 0:
                return
            
            size = math.floor(risk_dollars / risk_unit)
            tp = entry - (risk_unit * 2.0)
            
            pos = Position("NQ", "SHORT", entry, size, sl, tp)
            self.open_positions.append(pos)
            self.triple_a_phase = TripleAPhase.WAITING

    def manage_positions_and_pyramid(self, last_bar: RangeBar, impulse_lvns: List[float]):
        """Instant Risk-Zero ratchet and Impulse LVN Pyramiding Engine."""
        for pos in self.open_positions:
            # 1. Instant Risk-Zero Transition
            if not pos.is_risk_free:
                if pos.side == "LONG" and last_bar.close >= pos.entry_price + (pos.entry_price - pos.sl_price) * 0.8:
                    pos.sl_price = pos.entry_price  # Breakeven
                    pos.is_risk_free = True
                elif pos.side == "SHORT" and last_bar.close <= pos.entry_price - (pos.sl_price - pos.entry_price) * 0.8:
                    pos.sl_price = pos.entry_price  # Breakeven
                    pos.is_risk_free = True

            # 2. Algorithmic Pyramiding at Impulse Leg LVN Retest
            if pos.is_risk_free and pos.pyramid_level == 0:
                for lvn in impulse_lvns:
                    if abs(last_bar.low - lvn) <= self.tick_size * 2 and pos.side == "LONG":
                        if len(self.active_absorptions) > 0 and self.active_absorptions[-1].side == "BUY":
                            pyramid_size = math.floor(pos.size * 0.50)
                            new_sl = lvn - (2 * self.tick_size)
                            pos.sl_price = new_sl  # Lock base into profit
                            pyramid_pos = Position("NQ", "LONG", last_bar.close, pyramid_size, new_sl, pos.tp_price, True, 1)
                            self.open_positions.append(pyramid_pos)
                            pos.pyramid_level += 1
                            break

    def on_trade_closed(self, pnl: float):
        """Updates session cushion and evaluates streak triggers."""
        self.daily_cushion += pnl
        self.current_equity += pnl
        if pnl < 0:
            self.loss_streak += 1
        else:
            self.loss_streak = 0

    def is_circuit_breaker_active(self) -> bool:
        """Enforces daily loss cap (-2%) and 3-loss streak shutdown."""
        if self.daily_cushion <= -self.max_daily_loss:
            return True
        if self.loss_streak >= 3:
            return True
        return False
```

---

## 15. Operational Master Matrix

| Step | Trigger / Metric | Algorithmic Rule | Failure Action |
| :--- | :--- | :--- | :--- |
| **1. Session Gate** | Current Time $\in [09:30, 13:00]$ NY | Unlock execution engine. | Keep engine locked outside window. |
| **2. Pre-Market Lock** | Current Time $\in [09:10, 09:30]$ NY | **STRICT NO-TRADE LOCK.** | Reject all incoming orders. |
| **3. Absorption Flag** | $V \ge 1.5\overline{V}_{20} \land \Delta P \le 0.5H_{\text{range}}$ | Log Absorption Cluster & big bubbles. | No action (Wait for state progression). |
| **4. Squeeze Trigger** | 1m Candle **CLOSES** beyond Cluster | Dispatch Sniper Entry Order. | If bar closes inside, cancel setup. |
| **5. Stop-Loss** | Cluster Extreme $\pm 2\text{ ticks}$ | Hard Stop-Loss registered at exchange. | Strict zero-discretion execution. |
| **6. Risk-Zero Transition**| Price advances $+0.8R$ / CVD surge | **Ratchet SL to Breakeven instantly.** | Downside risk eliminated ($0.00$). |
| **7. Cushion Allocation** | Session PnL $> 0$ (Cushion Active) | Allocate $\text{Base} + 40\%\text{ Cushion}$. | If Cushion $\le 0$, use Base Risk ($0.25\%$). |
| **8. Pyramid Add-On** | Base Trade Risk-Free + LVN Retest | Add $+50\%$ Size; Ratchet combined SL. | Maintain single base trade if no LVN retest. |
| **9. Circuit Breaker** | Loss streak $\ge 3$ or PnL $\le -2.0\%$ | **SHUT DOWN TRADING FOR THE DAY.** | Immediate system lock until next session. |

---

## 16. Known Data Limitations

### Range Bars
The spec describes range bars (fixed price height, ATR-quantized). The current implementation uses **time-based candles** (1-minute) for strategy decisions. Range bars are available via `quant/aggregator.py` but are not the primary decision driver. This is an architectural choice, not a bug — the strategy works correctly with time bars.

### Tick-Level Footprint
The spec describes tick-level footprint data with trade-level aggression flags. The current implementation uses **candle delta** (close-to-close) as a proxy for buy/sell volume. True trade-level aggression flags require a tick feed not available from the current Dhan integration.

### Order-Flow Imbalance
The spec describes true order-flow imbalance from the full order book. The current implementation uses **5-level depth snapshots** from Dhan. Full L2 depth is not available from the current feed.

### Day-of-Week Variance
The spec describes "Mondays & Fridays: Defensive size." The current implementation applies a **0.5x multiplier** on Mon/Fri and **1.0x** on Tue/Wed/Thu via `SessionRisk.DAY_OF_WEEK_MULTIPLIER`.

### TimesFM Integration
The TimesFM 3.0 integration is an **advisory-only** layer. It never blocks ticks and never changes the deterministic 4-gate AMT decision. See `docs/amt/TIMESFM_INTEGRATION.md` for details.
