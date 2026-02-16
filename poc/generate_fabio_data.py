"""Generate training data for Fabio Valentini AMT/Orderflow trading model.

Expanded from 11 templates to 30+ with balanced SHORT representation,
POC scenarios, and standardized Trigger format for risk management.
"""

import json
import random

NUM_EXAMPLES = 2000
INSTRUCTION = (
    "Analyze the trading scenario based on Fabio Valentini's "
    "methodology (Orderflow, Auction Market Theory)."
)

# Price ranges — ES futures + crypto
ES_VAL = (14900, 15000)
ES_VAH = (15100, 15200)
ES_POC = (15000, 15100)

BTC_VAL = (61000, 64000)
BTC_VAH = (65000, 68000)
BTC_POC = (63000, 66000)

ETH_VAL = (3200, 3400)
ETH_VAH = (3500, 3700)
ETH_POC = (3400, 3600)

PRICE_SETS = [
    (ES_VAL, ES_VAH, ES_POC),
    (BTC_VAL, BTC_VAH, BTC_POC),
    (ETH_VAL, ETH_VAH, ETH_POC),
]


def _rp(r):
    return random.randint(r[0], r[1])


def _pick_prices():
    val_r, vah_r, poc_r = random.choice(PRICE_SETS)
    return _rp(val_r), _rp(vah_r), _rp(poc_r)


def _delta(lo=300, hi=2000):
    return random.randint(lo, hi)


def _vol(lo=1000, hi=5000):
    return random.randint(lo, hi)


# ===================================================================
# AAA LONG (Absorption at VAL → Long)
# ===================================================================

def generate_aaa_long():
    val, vah, poc = _pick_prices()
    d = _delta()
    v = _vol()
    templates = [
        {
            "input": f"New York Open. Price is testing Value Area Low (VAL) at {val}. Sellers are aggressive with -{d} Delta but price is not moving down. Big buy orders are hitting the bid.",
            "output": f"Market State: **Balance** (Bottom of Range). Logic: **AAA Setup**. Sellers are super aggressive but are being absorbed (passive buyers holding the wall). Trigger: **Enter Long**. Stop: Tight below absorption low. Target: Value Area High (~{vah}). Risk/Reward: Asymmetrical (High).",
        },
        {
            "input": f"Price pushed below VAL {val} during London close but is dragging back inside. Footprint shows {v} contracts sold at lows with no follow-through.",
            "output": f"Market State: **Balance** (Failed Breakdown). Logic: **AAA Setup**. Sellers attempted to push but failed (Trapped Sellers). Absorption confirms support. Trigger: **Enter Long** on re-entry into Value. Target: VAH or Session High. Rule: Don't short into absorption.",
        },
        {
            "input": f"Market is rotational. We are at the bottom of the distribution ({val}). Delta is continuously red but price is ticking higher.",
            "output": f"Market State: **Absorption**. Logic: **AAA Setup**. Passive buyers are consuming all sell pressure. Demand > Supply at this price. Trigger: **Long** with size. Target: Rotation to top of balance ({vah}).",
        },
        {
            "input": f"Price at {val}, sellers dumped {v} contracts but passive buyers absorbed everything. Price holding firm. Delta -{d}.",
            "output": f"Market State: **Balance** (Bottom of Range). Logic: **AAA Setup**. Iceberg buyers visible in footprint. Sellers unable to move price despite aggressive selling. Trigger: **Enter Long**. Stop: Below {val - 10}. Target: POC ({poc}) then VAH ({vah}).",
        },
        {
            "input": f"VAL test at {val}. Aggressive selling with -{d} Delta. Footprint shows iceberg buyers. Price refuses to break lower. Volume {v} contracts.",
            "output": f"Market State: **Absorption**. Logic: **AAA Setup**. Big passive buyers holding the wall at VAL. Sellers exhausting themselves. Trigger: **Enter Long**. Stop: Tight below absorption low. Target: Rotation to VAH ({vah}).",
        },
        {
            "input": f"Opening range established near VAL {val}. Multiple attempts to break lower failed. Buy absorption visible in orderflow with {v} contracts.",
            "output": f"Market State: **Balance** (Failed Breakdown). Logic: **AAA Setup**. Repeated failures to push below VAL indicate strong demand. Trigger: **Enter Long** on re-entry into Value. Target: Mid-range ({poc}) then VAH ({vah}).",
        },
    ]
    return random.choice(templates)


# ===================================================================
# AAA SHORT (Absorption at VAH → Short) — NEW
# ===================================================================

def generate_aaa_short():
    val, vah, poc = _pick_prices()
    d = _delta()
    v = _vol()
    templates = [
        {
            "input": f"Price is testing Value Area High (VAH) at {vah}. Buyers are aggressive with +{d} Delta but price is not moving up. Big sell orders are absorbing all buying pressure.",
            "output": f"Market State: **Balance** (Top of Range). Logic: **AAA Setup**. Buyers are super aggressive but are being absorbed (passive sellers holding the wall). Trigger: **Enter Short**. Stop: Tight above absorption high. Target: Value Area Low (~{val}). Risk/Reward: Asymmetrical (High).",
        },
        {
            "input": f"Price pushed above VAH {vah} but is dragging back inside. Footprint shows {v} contracts bought at highs with no follow-through.",
            "output": f"Market State: **Balance** (Failed Breakout). Logic: **AAA Setup**. Buyers attempted to push but failed (Trapped Buyers). Absorption confirms resistance. Trigger: **Enter Short** on re-entry into Value. Target: VAL or Session Low.",
        },
        {
            "input": f"Market is rotational. We are at the top of the distribution ({vah}). Delta is continuously green but price is ticking lower.",
            "output": f"Market State: **Absorption**. Logic: **AAA Setup**. Passive sellers are consuming all buy pressure. Supply > Demand at this price. Trigger: **Short** with size. Target: Rotation to bottom of balance ({val}).",
        },
        {
            "input": f"VAH test at {vah}. Aggressive buying with +{d} Delta. Iceberg sellers visible. Price refuses to break higher. Volume {v} contracts.",
            "output": f"Market State: **Absorption**. Logic: **AAA Setup**. Big passive sellers holding the wall at VAH. Buyers exhausting themselves. Trigger: **Enter Short**. Stop: Tight above absorption high. Target: Rotation to VAL ({val}).",
        },
        {
            "input": f"At the top of distribution ({vah}). Delta is continuously green but price is ticking lower. Sellers absorbing. Footprint shows {v} contracts.",
            "output": f"Market State: **Balance** (Top of Range). Logic: **AAA Setup**. Passive sellers consuming all buy pressure. Trigger: **Enter Short**. Stop: Above {vah + 10}. Target: POC ({poc}) then VAL ({val}).",
        },
        {
            "input": f"Price at {vah}, buyers pushed {v} contracts but passive sellers absorbed everything. Price failing to hold above VAH. Delta +{d}.",
            "output": f"Market State: **Absorption**. Logic: **AAA Setup**. Iceberg sellers visible in footprint. Buyers unable to move price despite aggressive buying. Trigger: **Short** on confirmation of rotation back inside. Target: Mid-range ({poc}) then VAL ({val}).",
        },
    ]
    return random.choice(templates)


# ===================================================================
# MOMENTUM LONG (Breakout / Squeeze)
# ===================================================================

def generate_momentum_long():
    val, vah, poc = _pick_prices()
    d = _delta(500, 2000)
    templates = [
        {
            "input": f"Price broke above Value Area High {vah} with strong +{d} Delta. Aggressive buyers are lifting the offer.",
            "output": f"Market State: **Imbalance** (Trend). Logic: **Momentum Squeeze**. Buyers are in full control. Sellers are trapped. Trigger: **Enter Long** on pullback to the **Protection Level** (where big buyers stepped in). Rule: Trail stop aggressively. Target: Extension/Blue Sky.",
        },
        {
            "input": f"Volatility spike. Price blasted through {vah}. A 'P-Shape' profile is forming. Short covering in progress.",
            "output": f"Market State: **Imbalance** (Short Covering). Logic: **Momentum**. Market is rebalancing higher. Structure is P-Shape (Short Covering). Trigger: **Long** on any dip. Do not fade. Target: Session Highs or Measured Move.",
        },
        {
            "input": f"Aggressive buyers pushing. We are making Higher Highs. A wall of bids has formed at {vah + 10}. Delta +{d}.",
            "output": f"Market State: **Trend**. Logic: **Momentum**. Buyers are protecting the level. Trigger: **Add to Longs** risk-free. Stop: Below the protection wall. Target: Squeeze until exhaustion.",
        },
        {
            "input": f"Breakout above {vah} confirmed. Volume surge with +{d} Delta. Buyers in full control. No sellers stepping in.",
            "output": f"Market State: **Imbalance** (Trend). Logic: **Momentum**. Clean breakout with aggressive buying. Trigger: **Enter Long** on pullback to the **Protection Level**. Stop: Below breakout level. Target: Extension move.",
        },
    ]
    return random.choice(templates)


# ===================================================================
# MOMENTUM SHORT (Breakdown / Squeeze) — NEW
# ===================================================================

def generate_momentum_short():
    val, vah, poc = _pick_prices()
    d = _delta(500, 2000)
    templates = [
        {
            "input": f"Price broke below Value Area Low {val} with strong -{d} Delta. Aggressive sellers are hammering the bid.",
            "output": f"Market State: **Imbalance** (Trend Down). Logic: **Momentum Squeeze**. Sellers are in full control. Buyers are trapped. Trigger: **Enter Short** on pullback to the **Protection Level** (where big sellers stepped in). Rule: Trail stop aggressively. Target: Extension/New Lows.",
        },
        {
            "input": f"Volatility spike. Price crashed through {val}. A 'b-Shape' profile is forming. Long liquidation in progress.",
            "output": f"Market State: **Imbalance** (Long Covering). Logic: **Momentum**. Market is rebalancing lower. Structure is b-Shape (Long Covering). Trigger: **Short** on any bounce. Do not buy. Target: Session Lows or Measured Move.",
        },
        {
            "input": f"Aggressive sellers pushing. Making Lower Lows. A wall of offers has formed at {val - 10}. Delta -{d}.",
            "output": f"Market State: **Trend**. Logic: **Momentum**. Sellers are protecting the level. Trigger: **Enter Short**. Stop: Above the protection wall. Target: Squeeze until exhaustion.",
        },
    ]
    return random.choice(templates)


# ===================================================================
# FAILED AUCTION (Reversal)
# ===================================================================

def generate_failed_auction():
    val, vah, poc = _pick_prices()
    d = _delta()
    templates = [
        {
            "input": f"Price broke VAH {vah} but immediately stalled. Delta was +{d} but price ticked down. Buyers are trapped at highs.",
            "output": f"Market State: **Failed Auction**. Logic: Breakout failed. Aggressive buyers are trapped. Market seeks value lower. Trigger: **Enter Short**. Target: Rotation back to Value Area Low (~{val}).",
        },
        {
            "input": f"Tried to squeeze the high at {vah} three times. Each time price rejected. Volume is drying up on the bid.",
            "output": f"Market State: **Balance** (Rejection). Logic: Buyers exhausted. 'Punching a wall'. Trigger: **Short** on confirmation of rotation back inside. Focus: Target middle of range first, then VAL.",
        },
        {
            "input": f"Failed breakout above {vah}. Aggressive buyers trapped. Delta turned from +{d} to negative. Market rotating back inside value area.",
            "output": f"Market State: **Failed Auction**. Logic: Breakout failed. Buyers exhausted at highs. Sellers stepping in. Trigger: **Enter Short**. Stop: Above failed high. Target: POC ({poc}) then VAL ({val}).",
        },
        {
            "input": f"Price tagged {vah}, delta flipped from +{d} to negative. Sellers stepping in aggressively. Buyers losing control.",
            "output": f"Market State: **Failed Auction**. Logic: Buyers are trapped. Aggressive buying met with absorption then reversal. Trigger: **Enter Short**. Stop: Above the failed auction high. Target: Rotation to VAL (~{val}).",
        },
        {
            "input": f"Price broke below VAL {val} but immediately stalled. Delta was -{d} but price ticked up. Sellers are trapped at lows.",
            "output": f"Market State: **Failed Auction**. Logic: Breakdown failed. Aggressive sellers are trapped. Market seeks value higher. Trigger: **Enter Long**. Target: Rotation back to Value Area High (~{vah}).",
        },
    ]
    return random.choice(templates)


# ===================================================================
# POC SCENARIOS — NEW
# ===================================================================

def generate_poc_scenario():
    val, vah, poc = _pick_prices()
    d = _delta(100, 600)
    templates = [
        {
            "input": f"Price sitting at POC {poc}. No directional pressure. Volume declining. Waiting for catalyst. Delta neutral.",
            "output": f"Market State: **Balance** (Rotating). Logic: No setup. Price at fair value with no aggression. Trigger: **Stay Flat**. Rule: Do not trade in the middle of the range without a catalyst. Wait for price to test VAH ({vah}) or VAL ({val}).",
        },
        {
            "input": f"At POC {poc}, delta flipped from negative to +{d}. Buyers stepping in. Absorption at POC confirmed.",
            "output": f"Market State: **Balance** (Accumulation). Logic: **AAA Setup** at POC. Buyers absorbing at fair value. Trigger: **Enter Long**. Stop: Below POC. Target: VAH ({vah}).",
        },
        {
            "input": f"Price at POC {poc} with aggressive sellers. Delta -{d}. Breaking down toward VAL {val}. No buyer absorption.",
            "output": f"Market State: **Imbalance** (Trend Down). Logic: Sellers pressing through POC with no resistance. Trigger: **Enter Short**. Stop: Above POC. Target: VAL ({val}).",
        },
    ]
    return random.choice(templates)


# ===================================================================
# RISK MANAGEMENT (Standardized with Trigger field)
# ===================================================================

def generate_risk_management():
    profit = random.randint(5000, 25000)
    drawdown = random.randint(1000, 5000)
    templates = [
        {
            "input": f"We are up ${profit} for the session. Price is entering a chop zone/contraction.",
            "output": f"Market State: **No Setup**. Logic: **Risk Management**. Walk away. Do not give back profit. 'We are done in 20 minutes'. Trigger: **Stay Flat**. Rule: Protect the cushion. Don't overtrade.",
        },
        {
            "input": f"I took two stop losses. Down ${drawdown}. Market is not giving a clear setup.",
            "output": f"Market State: **No Setup**. Logic: **Discipline**. Stop trading or reduce size significantly. Trigger: **Stay Flat**. Rule: Daily drawdown limit is strict. Better to close small red than huge red. Wait for AAA setup only.",
        },
        {
            "input": f"Floating ${profit} profit on a Long. Price is reaching a technical resistance.",
            "output": f"Market State: **No Setup**. Logic: **Bank Profit**. Take partials or close. 'If the market wants to give me ${profit}, I take it.' Trigger: **Stay Flat**. Don't hold for the home run if structure breaks.",
        },
        {
            "input": f"Third losing trade today. Down ${drawdown} total. No clear setups visible.",
            "output": f"Market State: **No Setup**. Logic: **Discipline**. Three losses is the limit. Trigger: **Stay Flat**. Rule: Walk away. Protect capital for tomorrow.",
        },
        {
            "input": f"Market is choppy, low volume. No clear direction. We've been flat for 30 minutes.",
            "output": f"Market State: **No Setup**. Logic: **Risk Management**. No edge in current conditions. Trigger: **Stay Flat**. Rule: Don't force trades. Wait for clear structure.",
        },
    ]
    return random.choice(templates)


# ===================================================================
# EDGE CASES — NEW
# ===================================================================

def generate_edge_case():
    val, vah, poc = _pick_prices()
    d = _delta(50, 300)
    templates = [
        {
            "input": f"News event just dropped. Huge volume spike. Price moved {random.randint(50, 200)} points in seconds. Delta is extreme at +{_delta(2000, 5000)}.",
            "output": f"Market State: **No Setup**. Logic: **Discipline**. Never trade into a news spike. Wait for the dust to settle. Trigger: **Stay Flat**. Rule: Let the market establish new levels before entering.",
        },
        {
            "input": f"Market is grinding slowly. No significant delta. Volume below average. Price at {poc} with tiny range.",
            "output": f"Market State: **Balance** (Low Volume). Logic: **Risk Management**. No edge in thin markets. Trigger: **Stay Flat**. Rule: Low volume = low conviction. Wait for volume surge.",
        },
        {
            "input": f"Price whipsawing between {val} and {vah}. Multiple false breakouts in both directions. Delta flipping constantly.",
            "output": f"Market State: **Balance** (Choppy). Logic: **Discipline**. Whipsaw market kills accounts. Trigger: **Stay Flat**. Rule: If you can't identify the setup, you don't have one. Walk away.",
        },
    ]
    return random.choice(templates)


# ===================================================================
# Main generator with rebalanced distribution
# ===================================================================

GENERATORS = [
    (0.20, generate_aaa_long),       # 20% AAA Long
    (0.35, generate_aaa_short),      # 15% AAA Short
    (0.48, generate_momentum_long),  # 13% Momentum Long
    (0.58, generate_momentum_short), # 10% Momentum Short
    (0.72, generate_failed_auction), # 14% Failed Auction (mix of long/short)
    (0.80, generate_poc_scenario),   # 8% POC
    (0.92, generate_risk_management),# 12% Risk Management
    (1.00, generate_edge_case),      # 8% Edge Cases
]


def main():
    random.seed(42)
    data = []
    print(f"Generating {NUM_EXAMPLES} synthetic training examples...")

    for _ in range(NUM_EXAMPLES):
        r = random.random()
        for threshold, gen_func in GENERATORS:
            if r < threshold:
                s = gen_func()
                break

        entry = {
            "instruction": INSTRUCTION,
            "input": s["input"],
            "output": s["output"],
        }
        data.append(entry)

    output_file = "training_data_fabio.jsonl"
    with open(output_file, "w") as f:
        for entry in data:
            json.dump(entry, f)
            f.write("\n")

    # Print distribution stats
    from collections import Counter
    directions = Counter()
    for entry in data:
        out = entry["output"].lower()
        if "enter long" in out or "**long**" in out or "long with size" in out or "add to longs" in out or "long on any" in out:
            directions["LONG"] += 1
        elif "enter short" in out or "**short**" in out or "short with size" in out or "short on confirmation" in out or "short on any" in out:
            directions["SHORT"] += 1
        else:
            directions["FLAT"] += 1

    print(f"Generated {len(data)} examples to {output_file}")
    print(f"Direction distribution: {dict(directions)}")
    pct = {k: f"{100*v/len(data):.0f}%" for k, v in directions.items()}
    print(f"Percentages: {pct}")


if __name__ == "__main__":
    main()
