"""Generate training data for Fabio Valentini AMT/Orderflow trading model.

Output format: ChatML conversations matching the MLX inference adapter exactly.
Each example includes full indicator context (LVN, HVN, CVD, VWAP, profile shape)
matching the exact phrasing from generative_ai_service._build_prompt().

Target: 5000 examples with ~38% LONG / ~35% SHORT / ~27% FLAT
"""

import hashlib
import json
import random

NUM_EXAMPLES = 5000
SYSTEM_INSTRUCTION = (
    "Analyze the trading scenario based on Fabio Valentini's "
    "methodology (Orderflow, Auction Market Theory). "
    "Always respond with exactly three lines:\n"
    "Market State: Balance or Imbalance\n"
    "Logic: brief reasoning\n"
    "Trigger: Enter Long, Enter Short, or Stay Flat"
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

SOL_VAL = (120, 150)
SOL_VAH = (160, 190)
SOL_POC = (140, 170)

PRICE_SETS = [
    (ES_VAL, ES_VAH, ES_POC),
    (BTC_VAL, BTC_VAH, BTC_POC),
    (ETH_VAL, ETH_VAH, ETH_POC),
    (SOL_VAL, SOL_VAH, SOL_POC),
]

SESSIONS = [
    "New York Open", "London Open", "Asia session", "Pre-market",
    "NY morning", "London close", "European session", "US cash open",
]


# ── Helpers ──────────────────────────────────────────────────────

def _rp(r):
    return random.randint(r[0], r[1])


def _pick_prices():
    val_r, vah_r, poc_r = random.choice(PRICE_SETS)
    val = _rp(val_r)
    vah = _rp(vah_r)
    poc = _rp(poc_r)
    return val, vah, poc


def _delta(lo=300, hi=2000):
    return random.randint(lo, hi)


def _vol(lo=1000, hi=5000):
    return random.randint(lo, hi)


def _session():
    return random.choice(SESSIONS)


def _vwap_for(val, vah):
    """Generate a VWAP near the middle of value area."""
    return random.randint(val, vah)


def _hvn_levels(val, vah, count=2):
    """Generate HVN price levels within value area."""
    step = (vah - val) // max(count + 1, 2)
    return [val + step * (i + 1) + random.randint(-5, 5) for i in range(count)]


def _lvn_levels(val, vah, count=1):
    """Generate LVN price levels (thin volume nodes between HVNs)."""
    mid = (val + vah) // 2
    return [mid + random.randint(-20, 20) for _ in range(count)]


# ── Indicator context builders (match _build_prompt phrasing exactly) ──

def _profile_shape_text(shape):
    if shape == "P":
        return "A 'P-Shape' profile is forming. Long liquidation visible — sellers in control."
    elif shape == "b":
        return "A 'b-Shape' profile is forming. Short covering — buyers absorbing at lows."
    elif shape == "D":
        return "D-shaped profile. Market is balanced and rotational."
    return ""


def _volume_bubbles_text(desc):
    if desc:
        return f"Volume bubbles detected: {desc}."
    return "No significant volume bubbles."


def _hvn_text(hvns):
    if hvns:
        hvn_str = ", ".join(f"{h:.0f}" for h in hvns[:3])
        return f"Key HVN levels: {hvn_str}."
    return ""


def _lvn_text(lvns):
    """LVN context — Fabio's core entry levels."""
    if lvns:
        lvn_str = ", ".join(f"{l:.0f}" for l in lvns[:3])
        return f"Low Volume Nodes (LVN): {lvn_str}. Price moves quickly through these levels."
    return ""


def _cvd_text(cvd_type, slope=None):
    if cvd_type == "BEARISH_DIV":
        return "CVD divergence: price rising but buying pressure declining. Caution for longs."
    elif cvd_type == "BULLISH_DIV":
        return "CVD divergence: price falling but selling pressure declining. Accumulation possible."
    elif cvd_type == "UP":
        return "CVD trending up. Buyers in control."
    elif cvd_type == "DOWN":
        return "CVD trending down. Sellers in control."
    return ""


def _vwap_text(price, vwap):
    if vwap <= 0 or price <= 0:
        return ""
    if price > vwap * 1.001:
        return f"Price above VWAP ({vwap:.0f}). Bullish bias."
    elif price < vwap * 0.999:
        return f"Price below VWAP ({vwap:.0f}). Bearish bias."
    return f"Price at VWAP ({vwap:.0f}). Neutral."


def _build_input(location_text, *, profile_shape="D", volume_bubbles="",
                 hvns=None, lvns=None, cvd_type="", price=0, vwap=0):
    """Assemble a full input prompt matching live _build_prompt() structure."""
    parts = [location_text]

    ps = _profile_shape_text(profile_shape)
    if ps:
        parts.append(ps)

    parts.append(_volume_bubbles_text(volume_bubbles))

    ht = _hvn_text(hvns or [])
    if ht:
        parts.append(ht)

    lt = _lvn_text(lvns or [])
    if lt:
        parts.append(lt)

    ct = _cvd_text(cvd_type)
    if ct:
        parts.append(ct)

    vt = _vwap_text(price, vwap)
    if vt:
        parts.append(vt)

    return " ".join(parts)


def _chatml_entry(user_input, assistant_output):
    """Format as ChatML conversation (matching MLX adapter prompt structure)."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": assistant_output},
        ]
    }


# ── Bubble descriptions ──

BUBBLE_BUY = [
    "2.5σ aggressive buy at {price:.0f} ({vol} contracts)",
    "Large buy imprint at {price:.0f}",
    "Aggressive buyers stacking at {price:.0f} ({vol} lots)",
]

BUBBLE_SELL = [
    "2.5σ aggressive sell at {price:.0f} ({vol} contracts)",
    "Large sell imprint at {price:.0f}",
    "Aggressive sellers hitting at {price:.0f} ({vol} lots)",
]


def _buy_bubble(price, vol):
    return random.choice(BUBBLE_BUY).format(price=price, vol=vol)


def _sell_bubble(price, vol):
    return random.choice(BUBBLE_SELL).format(price=price, vol=vol)


# ===================================================================
# AAA LONG (Absorption at VAL -> Long)
# ===================================================================

def generate_aaa_long():
    val, vah, poc = _pick_prices()
    d = _delta()
    v = _vol()
    session = _session()
    price = val + random.randint(-5, 10)
    vwap = _vwap_for(val, vah)
    hvns = _hvn_levels(val, vah)
    lvns = _lvn_levels(val, vah)

    locations = [
        f"{session}. VAL test at {val}. Aggressive selling with -{d} Delta. Price not moving down. Iceberg buyers visible in the footprint.",
        f"Price at VAL {val} with +{d} Delta. Buyers defending. {v} contracts absorbed.",
        f"Price pushed below VAL {val} during {session} but dragging back inside. {v} contracts sold at lows with no follow-through.",
        f"Market is rotational. Bottom of distribution ({val}). Delta continuously red but price ticking higher.",
        f"Price at {val}, sellers dumped {v} contracts but passive buyers absorbed everything. Delta -{d}.",
        f"VAL test at {val}. Aggressive selling with -{d} Delta. Footprint shows iceberg buyers. Price refuses to break lower.",
        f"Opening range near VAL {val}. Multiple attempts to break lower failed. Buy absorption visible with {v} contracts.",
        f"{session}. Sellers sweeping bids at {val} but getting absorbed every time. Delta -{d}, volume {v}.",
    ]

    outputs = [
        f"Market State: Balance (Bottom of Range)\nLogic: AAA Setup. Sellers aggressive but absorbed by passive buyers holding the wall at VAL.\nTrigger: Enter Long. Stop below {val}. Target VAH ({vah}).",
        f"Market State: Absorption\nLogic: AAA Setup. Iceberg buyers consuming all sell pressure. Demand > Supply.\nTrigger: Enter Long. Stop below absorption low. Target rotation to VAH ({vah}).",
        f"Market State: Balance (Failed Breakdown)\nLogic: AAA Setup. Sellers attempted to push but failed. Trapped Sellers. Absorption confirms support.\nTrigger: Enter Long on re-entry into Value. Target VAH.",
        f"Market State: Absorption\nLogic: AAA Setup. Passive buyers consuming all sell pressure at VAL.\nTrigger: Enter Long with size. Target rotation to top of balance ({vah}).",
    ]

    loc = random.choice(locations)
    bubble = _buy_bubble(val, v) if random.random() > 0.3 else ""
    shape = random.choice(["b", "D", "D"])
    inp = _build_input(loc, profile_shape=shape, volume_bubbles=bubble,
                       hvns=hvns, lvns=lvns, cvd_type=random.choice(["", "BULLISH_DIV", "UP"]),
                       price=price, vwap=vwap)
    out = random.choice(outputs)
    return _chatml_entry(inp, out)


# ===================================================================
# AAA SHORT (Absorption at VAH -> Short)
# ===================================================================

def generate_aaa_short():
    val, vah, poc = _pick_prices()
    d = _delta()
    v = _vol()
    session = _session()
    price = vah + random.randint(-10, 5)
    vwap = _vwap_for(val, vah)
    hvns = _hvn_levels(val, vah)
    lvns = _lvn_levels(val, vah)

    locations = [
        f"Price testing VAH at {vah}. Buyers aggressive with +{d} Delta but price not moving up. Passive sellers holding the wall.",
        f"Price pushed above VAH {vah} but dragging back inside. {v} contracts bought at highs with no follow-through.",
        f"Top of distribution ({vah}). Delta continuously green but price ticking lower. Sellers absorbing.",
        f"VAH test at {vah}. Aggressive buying with +{d} Delta. Iceberg sellers visible. Price refuses to break higher.",
        f"Price at {vah}, buyers pushed {v} contracts but passive sellers absorbed everything. Delta +{d}.",
        f"{session}. Buyers stacking bids at {vah} but offers keep absorbing. Delta +{d}, volume {v}.",
        f"Top of range at {vah}. Spoofing on the bid side pulled, real sellers stepping in. Delta flipping from +{d} to negative.",
    ]

    outputs = [
        f"Market State: Balance (Top of Range)\nLogic: AAA Setup. Buyers aggressive but absorbed by passive sellers holding the wall at VAH.\nTrigger: Enter Short. Stop above {vah}. Target VAL ({val}).",
        f"Market State: Absorption\nLogic: AAA Setup. Passive sellers consuming all buy pressure. Supply > Demand.\nTrigger: Enter Short. Stop above absorption high. Target rotation to VAL ({val}).",
        f"Market State: Balance (Failed Breakout)\nLogic: AAA Setup. Buyers attempted push but failed. Trapped Buyers.\nTrigger: Enter Short on re-entry into Value. Target VAL.",
        f"Market State: Absorption\nLogic: AAA Setup. Iceberg sellers consuming all buy pressure at VAH.\nTrigger: Enter Short with size. Target rotation to bottom of balance ({val}).",
    ]

    loc = random.choice(locations)
    bubble = _sell_bubble(vah, v) if random.random() > 0.3 else ""
    shape = random.choice(["P", "D", "D"])
    inp = _build_input(loc, profile_shape=shape, volume_bubbles=bubble,
                       hvns=hvns, lvns=lvns, cvd_type=random.choice(["", "BEARISH_DIV", "DOWN"]),
                       price=price, vwap=vwap)
    out = random.choice(outputs)
    return _chatml_entry(inp, out)


# ===================================================================
# MOMENTUM LONG (Breakout / Squeeze)
# ===================================================================

def generate_momentum_long():
    val, vah, poc = _pick_prices()
    d = _delta(500, 2500)
    v = _vol(2000, 8000)
    session = _session()
    price = vah + random.randint(10, 60)
    vwap = _vwap_for(val, vah)
    hvns = _hvn_levels(val, vah)

    locations = [
        f"Price broke above VAH {vah} with strong +{d} Delta. Aggressive buyers lifting the offer.",
        f"Volatility spike. Price blasted through {vah}. Short covering in progress. Delta +{d}.",
        f"Aggressive buyers pushing. Making Higher Highs. Wall of bids at {vah + 10}. Delta +{d}.",
        f"Breakout above {vah} confirmed. Volume surge with +{d} Delta. No sellers stepping in.",
        f"{session}. Price ripping through {vah} with +{d} Delta. Offers getting swept. Shorts scrambling.",
    ]

    outputs = [
        f"Market State: Imbalance (Trend)\nLogic: Momentum Squeeze. Buyers in full control. Sellers trapped.\nTrigger: Enter Long on pullback to Protection Level. Trail stop. Target extension.",
        f"Market State: Imbalance (Short Covering)\nLogic: Momentum. Market rebalancing higher. P-Shape forming.\nTrigger: Enter Long on any dip. Do not fade. Target session highs.",
        f"Market State: Imbalance (Trend)\nLogic: Momentum. Clean breakout with aggressive buying.\nTrigger: Enter Long on pullback. Stop below breakout. Target extension move.",
    ]

    loc = random.choice(locations)
    bubble = _buy_bubble(price, v)
    inp = _build_input(loc, profile_shape="P", volume_bubbles=bubble,
                       hvns=hvns, cvd_type="UP", price=price, vwap=vwap)
    out = random.choice(outputs)
    return _chatml_entry(inp, out)


# ===================================================================
# MOMENTUM SHORT (Breakdown / Squeeze)
# ===================================================================

def generate_momentum_short():
    val, vah, poc = _pick_prices()
    d = _delta(500, 2500)
    v = _vol(2000, 8000)
    session = _session()
    price = val - random.randint(10, 60)
    vwap = _vwap_for(val, vah)
    hvns = _hvn_levels(val, vah)

    locations = [
        f"Price broke below VAL {val} with strong -{d} Delta. Aggressive sellers hammering the bid.",
        f"Volatility spike. Price crashed through {val}. Long liquidation in progress. Delta -{d}.",
        f"Aggressive sellers pushing. Making Lower Lows. Wall of offers at {val - 10}. Delta -{d}.",
        f"{session}. Price crashing through {val} with -{d} Delta. Bids getting swept. Longs liquidating.",
    ]

    outputs = [
        f"Market State: Imbalance (Trend Down)\nLogic: Momentum Squeeze. Sellers in full control. Buyers trapped.\nTrigger: Enter Short on pullback to Protection Level. Trail stop. Target extension.",
        f"Market State: Imbalance (Long Covering)\nLogic: Momentum. Market rebalancing lower. b-Shape forming.\nTrigger: Enter Short on any bounce. Do not buy. Target session lows.",
        f"Market State: Imbalance (Trend Down)\nLogic: Momentum. Clean breakdown with aggressive selling.\nTrigger: Enter Short on pullback. Stop above breakdown. Target extension.",
    ]

    loc = random.choice(locations)
    bubble = _sell_bubble(price, v)
    inp = _build_input(loc, profile_shape="b", volume_bubbles=bubble,
                       hvns=hvns, cvd_type="DOWN", price=price, vwap=vwap)
    out = random.choice(outputs)
    return _chatml_entry(inp, out)


# ===================================================================
# FAILED AUCTION (Reversal)
# ===================================================================

def generate_failed_auction():
    val, vah, poc = _pick_prices()
    d = _delta()
    v = _vol()
    session = _session()
    hvns = _hvn_levels(val, vah)
    lvns = _lvn_levels(val, vah)

    # Failed auction at high → SHORT
    high_templates = [
        (
            f"Price broke VAH {vah} but immediately stalled. Delta was +{d} but price ticked down. Buyers trapped at highs.",
            vah + random.randint(0, 15),
            f"Market State: Failed Auction\nLogic: Breakout failed. Aggressive buyers trapped. Market seeks value lower.\nTrigger: Enter Short. Target rotation to VAL ({val}).",
        ),
        (
            f"Tried to squeeze high at {vah} three times. Each time rejected. Volume drying up on bid.",
            vah + random.randint(0, 10),
            f"Market State: Balance (Rejection)\nLogic: Buyers exhausted. Punching a wall.\nTrigger: Enter Short on rotation back inside. Target mid-range then VAL.",
        ),
        (
            f"Failed breakout above {vah}. Delta turned from +{d} to negative. Market rotating back inside.",
            vah + random.randint(-5, 10),
            f"Market State: Failed Auction\nLogic: Breakout failed. Buyers exhausted. Sellers stepping in.\nTrigger: Enter Short. Stop above failed high. Target POC ({poc}) then VAL ({val}).",
        ),
        (
            f"{session}. Failed breakout at {vah}. Buyers got aggressive +{d} Delta but absorbed and rejected.",
            vah + random.randint(0, 15),
            f"Market State: Failed Auction\nLogic: Breakout failed. Buyers trapped after aggressive push.\nTrigger: Enter Short. Stop above failed high. Target POC ({poc}) then VAL ({val}).",
        ),
    ]

    # Failed auction at low → LONG
    low_templates = [
        (
            f"Price broke below VAL {val} but immediately stalled. Delta was -{d} but price ticked up. Sellers trapped at lows.",
            val - random.randint(0, 15),
            f"Market State: Failed Auction\nLogic: Breakdown failed. Aggressive sellers trapped. Market seeks value higher.\nTrigger: Enter Long. Target rotation to VAH ({vah}).",
        ),
        (
            f"Breakdown below {val} attracted aggressive shorts but price bounced {random.randint(10, 50)} points. Bear trap confirmed.",
            val - random.randint(0, 15),
            f"Market State: Failed Auction (Bear Trap)\nLogic: Trapped Shorts. Sellers chased breakdown and are trapped. Covering will accelerate move.\nTrigger: Enter Long. Stop below trap low. Target VAH ({vah}).",
        ),
    ]

    if random.random() < 0.6:  # 60% short (more common at highs)
        loc_text, price, output = random.choice(high_templates)
        vwap = _vwap_for(val, vah)
        cvd = random.choice(["BEARISH_DIV", "DOWN", ""])
        bubble = _sell_bubble(vah, v) if random.random() > 0.4 else ""
    else:
        loc_text, price, output = random.choice(low_templates)
        vwap = _vwap_for(val, vah)
        cvd = random.choice(["BULLISH_DIV", "UP", ""])
        bubble = _buy_bubble(val, v) if random.random() > 0.4 else ""

    inp = _build_input(loc_text, profile_shape=random.choice(["D", "P", "b"]),
                       volume_bubbles=bubble, hvns=hvns, lvns=lvns,
                       cvd_type=cvd, price=price, vwap=vwap)
    return _chatml_entry(inp, output)


# ===================================================================
# LVN PULLBACK — TREND MODEL (Fabio's core: out-of-balance → pull to LVN → enter)
# ===================================================================

def generate_lvn_trend_long():
    val, vah, poc = _pick_prices()
    d = _delta(400, 1800)
    v = _vol(1500, 6000)
    session = _session()
    lvn = _lvn_levels(val, vah, 1)[0]
    hvns = _hvn_levels(val, vah)
    price = lvn + random.randint(-3, 3)
    vwap = _vwap_for(val, vah)

    locations = [
        f"Market imbalanced to upside. Price pulled back to LVN at {lvn:.0f}. Aggressive buyers stepping in with +{d} Delta.",
        f"After breakout above {vah}, price retracing to LVN {lvn:.0f}. Buyers absorbing. Delta +{d}. Volume {v}.",
        f"{session}. Trend is up. Price at LVN {lvn:.0f} — thin volume node. Aggressive buy prints appearing. Delta +{d}.",
        f"Uptrend pullback to LVN {lvn:.0f}. Price moving quickly through this low-volume zone. Buyers aggressive with +{d} Delta.",
    ]

    outputs = [
        f"Market State: Imbalance (Trend Up)\nLogic: Trend Model. LVN pullback entry. Price at thin volume node with aggressive buying.\nTrigger: Enter Long at LVN {lvn:.0f}. Stop below LVN. Target extension above {vah}.",
        f"Market State: Imbalance (Trend Up)\nLogic: Trend Model. Pullback to LVN in established uptrend. Aggression confirms continuation.\nTrigger: Enter Long. Stop just beyond aggressive print. Target new highs.",
    ]

    loc = random.choice(locations)
    bubble = _buy_bubble(lvn, v)
    inp = _build_input(loc, profile_shape=random.choice(["P", "D"]),
                       volume_bubbles=bubble, hvns=hvns, lvns=[lvn],
                       cvd_type="UP", price=price, vwap=vwap)
    return _chatml_entry(inp, random.choice(outputs))


def generate_lvn_trend_short():
    val, vah, poc = _pick_prices()
    d = _delta(400, 1800)
    v = _vol(1500, 6000)
    session = _session()
    lvn = _lvn_levels(val, vah, 1)[0]
    hvns = _hvn_levels(val, vah)
    price = lvn + random.randint(-3, 3)
    vwap = _vwap_for(val, vah)

    locations = [
        f"Market imbalanced to downside. Price pulled back to LVN at {lvn:.0f}. Aggressive sellers stepping in with -{d} Delta.",
        f"After breakdown below {val}, price retracing to LVN {lvn:.0f}. Sellers absorbing. Delta -{d}. Volume {v}.",
        f"{session}. Trend is down. Price at LVN {lvn:.0f} — thin volume node. Aggressive sell prints appearing. Delta -{d}.",
        f"Downtrend pullback to LVN {lvn:.0f}. Price moving quickly through this low-volume zone. Sellers aggressive with -{d} Delta.",
    ]

    outputs = [
        f"Market State: Imbalance (Trend Down)\nLogic: Trend Model. LVN pullback entry. Price at thin volume node with aggressive selling.\nTrigger: Enter Short at LVN {lvn:.0f}. Stop above LVN. Target extension below {val}.",
        f"Market State: Imbalance (Trend Down)\nLogic: Trend Model. Pullback to LVN in established downtrend. Aggression confirms continuation.\nTrigger: Enter Short. Stop just beyond aggressive print. Target new lows.",
    ]

    loc = random.choice(locations)
    bubble = _sell_bubble(lvn, v)
    inp = _build_input(loc, profile_shape=random.choice(["b", "D"]),
                       volume_bubbles=bubble, hvns=hvns, lvns=[lvn],
                       cvd_type="DOWN", price=price, vwap=vwap)
    return _chatml_entry(inp, random.choice(outputs))


# ===================================================================
# LVN PULLBACK — MEAN REVERSION (failed breakout → reclaim → pullback to LVN)
# ===================================================================

def generate_lvn_meanrev_long():
    val, vah, poc = _pick_prices()
    d = _delta(300, 1500)
    v = _vol()
    session = _session()
    lvn = _lvn_levels(val, vah, 1)[0]
    hvns = _hvn_levels(val, vah)
    price = lvn + random.randint(-3, 3)
    vwap = _vwap_for(val, vah)

    locations = [
        f"Failed breakdown below {val}. Price reclaimed value area. Now pulling back to LVN {lvn:.0f}. Buyers absorbing with +{d} Delta.",
        f"{session}. Market tried to break {val}, failed. Mean reversion in play. Price at LVN {lvn:.0f}. Aggressive buying +{d} Delta.",
        f"Bear trap below {val} reversed. Price back inside value. Pulling back to LVN {lvn:.0f}. Trapped shorts covering. Delta +{d}.",
    ]

    outputs = [
        f"Market State: Balance (Mean Reversion)\nLogic: Mean Reversion Setup. Failed breakdown, price reclaimed value. LVN pullback entry with aggression.\nTrigger: Enter Long at LVN {lvn:.0f}. Stop below failed low. Target VAH ({vah}).",
        f"Market State: Balance (Mean Reversion)\nLogic: Mean Reversion. Failed auction reversed. LVN provides optimal entry with thin volume.\nTrigger: Enter Long. Stop below trap low. Target rotation to VAH ({vah}).",
    ]

    loc = random.choice(locations)
    bubble = _buy_bubble(lvn, v) if random.random() > 0.3 else ""
    inp = _build_input(loc, profile_shape="D",
                       volume_bubbles=bubble, hvns=hvns, lvns=[lvn],
                       cvd_type=random.choice(["BULLISH_DIV", "UP"]),
                       price=price, vwap=vwap)
    return _chatml_entry(inp, random.choice(outputs))


def generate_lvn_meanrev_short():
    val, vah, poc = _pick_prices()
    d = _delta(300, 1500)
    v = _vol()
    session = _session()
    lvn = _lvn_levels(val, vah, 1)[0]
    hvns = _hvn_levels(val, vah)
    price = lvn + random.randint(-3, 3)
    vwap = _vwap_for(val, vah)

    locations = [
        f"Failed breakout above {vah}. Price reclaimed value area. Now pulling back to LVN {lvn:.0f}. Sellers absorbing with -{d} Delta.",
        f"{session}. Market tried to break {vah}, failed. Mean reversion in play. Price at LVN {lvn:.0f}. Aggressive selling -{d} Delta.",
        f"Bull trap above {vah} reversed. Price back inside value. Pulling back to LVN {lvn:.0f}. Trapped longs liquidating. Delta -{d}.",
    ]

    outputs = [
        f"Market State: Balance (Mean Reversion)\nLogic: Mean Reversion Setup. Failed breakout, price reclaimed value. LVN pullback entry with aggression.\nTrigger: Enter Short at LVN {lvn:.0f}. Stop above failed high. Target VAL ({val}).",
        f"Market State: Balance (Mean Reversion)\nLogic: Mean Reversion. Failed auction reversed. LVN provides optimal entry with thin volume.\nTrigger: Enter Short. Stop above trap high. Target rotation to VAL ({val}).",
    ]

    loc = random.choice(locations)
    bubble = _sell_bubble(lvn, v) if random.random() > 0.3 else ""
    inp = _build_input(loc, profile_shape="D",
                       volume_bubbles=bubble, hvns=hvns, lvns=[lvn],
                       cvd_type=random.choice(["BEARISH_DIV", "DOWN"]),
                       price=price, vwap=vwap)
    return _chatml_entry(inp, random.choice(outputs))


# ===================================================================
# POC SCENARIOS
# ===================================================================

def generate_poc_scenario():
    val, vah, poc = _pick_prices()
    d = _delta(50, 600)
    session = _session()
    price = poc + random.randint(-10, 10)
    vwap = _vwap_for(val, vah)
    hvns = _hvn_levels(val, vah)
    lvns = _lvn_levels(val, vah)

    templates = [
        (
            f"Price sitting at POC {poc}. No directional pressure. Volume declining. Delta neutral.",
            f"Market State: Balance (Rotating)\nLogic: No setup. Price at fair value with no aggression.\nTrigger: Stay Flat. Wait for price to test VAH ({vah}) or VAL ({val}).",
        ),
        (
            f"At POC {poc}, delta flipped from negative to +{d}. Buyers stepping in. Absorption confirmed.",
            f"Market State: Balance (Accumulation)\nLogic: AAA Setup at POC. Buyers absorbing at fair value.\nTrigger: Enter Long. Stop below POC. Target VAH ({vah}).",
        ),
        (
            f"Price at POC {poc} with aggressive sellers. Delta -{d}. Breaking down toward VAL {val}. No buyer absorption.",
            f"Market State: Imbalance (Trend Down)\nLogic: Sellers pressing through POC with no resistance.\nTrigger: Enter Short. Stop above POC. Target VAL ({val}).",
        ),
        (
            f"{session}. Sitting at POC {poc}. Volume drying up. No one wants to trade here.",
            f"Market State: Balance (Rotating)\nLogic: No setup. Fair value with no conviction.\nTrigger: Stay Flat. Wait for price to reach extreme (VAH {vah} or VAL {val}).",
        ),
    ]

    loc, output = random.choice(templates)
    inp = _build_input(loc, profile_shape="D",
                       volume_bubbles="", hvns=hvns, lvns=lvns,
                       cvd_type="", price=price, vwap=vwap)
    return _chatml_entry(inp, output)


# ===================================================================
# DELTA DIVERGENCE
# ===================================================================

def generate_delta_divergence():
    val, vah, poc = _pick_prices()
    d = _delta(500, 2000)
    v = _vol()
    session = _session()
    hvns = _hvn_levels(val, vah)

    templates = [
        (
            f"{session}. Price making new highs above {vah} but delta diverging negative at -{d}. Volume {v}. Buyers lifting but no real aggression.",
            vah + random.randint(5, 30),
            "DOWN",
            f"Market State: Delta Divergence (Bearish)\nLogic: Price rising on negative delta. Passive sellers absorbing. Hidden supply.\nTrigger: Enter Short. Stop above session high. Target POC ({poc}) then VAL ({val}).",
        ),
        (
            f"Price grinding lower toward {val} but delta positive at +{d}. Passive buyers accumulating while price drops.",
            val - random.randint(5, 20),
            "UP",
            f"Market State: Delta Divergence (Bullish)\nLogic: Price falling on positive delta. Passive buyers absorbing. Hidden demand.\nTrigger: Enter Long. Stop below session low. Target POC ({poc}) then VAH ({vah}).",
        ),
        (
            f"New highs being printed but cumulative delta flat. {v} contracts traded with no net aggression.",
            vah + random.randint(5, 30),
            "BEARISH_DIV",
            f"Market State: Delta Divergence (Bearish)\nLogic: Price advancing without aggressive buying. Moves without delta confirmation fail.\nTrigger: Enter Short on first sign of rejection. Target rotation to value ({poc}).",
        ),
        (
            f"Price at new lows below {val} but CVD turning positive at +{d}. Someone accumulating into weakness. Volume {v}.",
            val - random.randint(5, 20),
            "BULLISH_DIV",
            f"Market State: Delta Divergence (Bullish)\nLogic: Price dropping but buyers absorbing at lows. Divergence signals reversal.\nTrigger: Enter Long on price stabilization. Stop below swing low. Target VAH ({vah}).",
        ),
    ]

    loc, price, cvd, output = random.choice(templates)
    vwap = _vwap_for(val, vah)
    inp = _build_input(loc, profile_shape=random.choice(["D", "P", "b"]),
                       volume_bubbles="", hvns=hvns, cvd_type=cvd,
                       price=price, vwap=vwap)
    return _chatml_entry(inp, output)


# ===================================================================
# TRAPPED TRADERS
# ===================================================================

def generate_trapped_traders():
    val, vah, poc = _pick_prices()
    d = _delta(500, 2000)
    v = _vol()
    session = _session()
    hvns = _hvn_levels(val, vah)
    lvns = _lvn_levels(val, vah)

    templates = [
        (
            f"{session}. Price spiked above {vah} triggering buy stops, then immediately reversed. {v} contracts bought at high now underwater. Delta collapsing.",
            vah + random.randint(5, 20), "BEARISH_DIV",
            f"Market State: Failed Auction (Bull Trap)\nLogic: Trapped Longs. Stop hunt above VAH triggered and reversed. Trapped buyers will fuel move down.\nTrigger: Enter Short. Stop above spike high. Target VAL ({val}).",
        ),
        (
            f"Price dropped through {val} sweeping sell stops, then snapped back inside value. Sellers trapped. Delta flipping to +{d}.",
            val - random.randint(5, 20), "BULLISH_DIV",
            f"Market State: Failed Auction (Bear Trap)\nLogic: Trapped Shorts. Stop hunt below VAL triggered and reversed. Trapped sellers will fuel move up.\nTrigger: Enter Long. Stop below spike low. Target VAH ({vah}).",
        ),
        (
            f"Breakout above {vah} looked clean but volume dried up instantly. {v} contracts bought at top. Price stalling. Those longs are trapped.",
            vah + random.randint(0, 15), "DOWN",
            f"Market State: Failed Auction (Bull Trap)\nLogic: Trapped Longs. Breakout without follow-through. Trapped buyers become fuel for sellers.\nTrigger: Enter Short on re-entry below {vah}. Stop above spike. Target POC ({poc}) then VAL ({val}).",
        ),
        (
            f"Breakdown below {val} attracted aggressive shorts but price bounced {random.randint(10, 50)} points. -{d} Delta reversed to positive. Bear trap.",
            val - random.randint(5, 20), "UP",
            f"Market State: Failed Auction (Bear Trap)\nLogic: Trapped Shorts. Sellers chased breakdown and are trapped. Short covering will accelerate move.\nTrigger: Enter Long. Stop below trap low. Target VAH ({vah}).",
        ),
    ]

    loc, price, cvd, output = random.choice(templates)
    vwap = _vwap_for(val, vah)
    bubble = ""
    inp = _build_input(loc, profile_shape=random.choice(["D", "P", "b"]),
                       volume_bubbles=bubble, hvns=hvns, lvns=lvns,
                       cvd_type=cvd, price=price, vwap=vwap)
    return _chatml_entry(inp, output)


# ===================================================================
# SESSION TRANSITION
# ===================================================================

def generate_session_transition():
    val, vah, poc = _pick_prices()
    d = _delta()
    v = _vol()
    hvns = _hvn_levels(val, vah)

    templates = [
        (
            f"London established value at VAL {val} / VAH {vah}. NY opening and testing London high. Delta +{d}. Volume surging.",
            vah + random.randint(0, 10), "UP",
            f"Market State: Imbalance (Session Transition)\nLogic: NY testing London extremes. Acceptance above London VAH signals continuation.\nTrigger: Enter Long on acceptance above {vah}. Stop below London VAH. Target extension.",
        ),
        (
            f"London built tight range at {poc}. NY Open breaking below London VAL {val}. Delta -{d}. Fresh sellers.",
            val - random.randint(0, 10), "DOWN",
            f"Market State: Imbalance (Session Transition)\nLogic: NY rejecting London value lower. Fresh supply on NY Open.\nTrigger: Enter Short on breakdown confirmation. Stop above London POC ({poc}). Target extension.",
        ),
        (
            f"London/NY overlap. Price reversing entire London move. London was bearish but NY buying aggressively. Delta flipped to +{d}. Volume {v}.",
            poc + random.randint(-10, 10), "UP",
            f"Market State: Imbalance (Session Transition Reversal)\nLogic: NY reversing London direction. Fresh flow overrides prior session.\nTrigger: Enter Long on pullback. Stop below NY reversal low. Target above London high ({vah}).",
        ),
    ]

    loc, price, cvd, output = random.choice(templates)
    vwap = _vwap_for(val, vah)
    inp = _build_input(loc, profile_shape=random.choice(["D", "P"]),
                       volume_bubbles="", hvns=hvns, cvd_type=cvd,
                       price=price, vwap=vwap)
    return _chatml_entry(inp, output)


# ===================================================================
# RISK MANAGEMENT / FLAT
# ===================================================================

def generate_risk_management():
    val, vah, poc = _pick_prices()
    profit = random.randint(5000, 25000)
    drawdown = random.randint(1000, 5000)
    price = poc + random.randint(-20, 20)
    vwap = _vwap_for(val, vah)
    hvns = _hvn_levels(val, vah)

    templates = [
        (
            f"Up ${profit} for the session. Price entering chop zone/contraction.",
            f"Market State: No Setup\nLogic: Risk Management. Walk away. Do not give back profit.\nTrigger: Stay Flat. Protect the cushion.",
        ),
        (
            f"Two stop losses taken. Down ${drawdown}. Market not giving clear setup.",
            f"Market State: No Setup\nLogic: Discipline. Stop trading or reduce size significantly.\nTrigger: Stay Flat. Daily drawdown limit strict. Wait for AAA setup only.",
        ),
        (
            f"Floating ${profit} profit on Long. Price reaching technical resistance.",
            f"Market State: No Setup\nLogic: Bank Profit. Take partials or close.\nTrigger: Stay Flat. Don't hold for home run if structure breaks.",
        ),
        (
            f"Third losing trade today. Down ${drawdown} total. No clear setups visible.",
            f"Market State: No Setup\nLogic: Discipline. Three losses is the limit.\nTrigger: Stay Flat. Walk away. Protect capital.",
        ),
        (
            f"Market choppy, low volume. No clear direction. Flat for 30 minutes.",
            f"Market State: No Setup\nLogic: Risk Management. No edge in current conditions.\nTrigger: Stay Flat. Don't force trades. Wait for structure.",
        ),
        (
            f"Up ${profit} on day. Asia session coming up, liquidity thinning.",
            f"Market State: No Setup\nLogic: Risk Management. Session ending, liquidity dropping.\nTrigger: Stay Flat. Protect profits. Don't trade thin markets.",
        ),
    ]

    loc, output = random.choice(templates)
    inp = _build_input(loc, profile_shape="D", volume_bubbles="",
                       hvns=hvns, cvd_type="", price=price, vwap=vwap)
    return _chatml_entry(inp, output)


# ===================================================================
# EDGE CASES / NO-TRADE
# ===================================================================

def generate_edge_case():
    val, vah, poc = _pick_prices()
    price = poc + random.randint(-20, 20)
    vwap = _vwap_for(val, vah)
    hvns = _hvn_levels(val, vah)

    templates = [
        (
            f"News event just dropped. Huge volume spike. Price moved {random.randint(50, 200)} points in seconds. Delta extreme +{_delta(2000, 5000)}.",
            f"Market State: No Setup\nLogic: Discipline. Never trade into a news spike. Wait for dust to settle.\nTrigger: Stay Flat. Let market establish new levels.",
        ),
        (
            f"Market grinding slowly. No significant delta. Volume below average. Price at {poc} with tiny range.",
            f"Market State: Balance (Low Volume)\nLogic: Risk Management. No edge in thin markets.\nTrigger: Stay Flat. Low volume means low conviction. Wait for volume surge.",
        ),
        (
            f"Price whipsawing between {val} and {vah}. Multiple false breakouts in both directions. Delta flipping constantly.",
            f"Market State: Balance (Choppy)\nLogic: Discipline. Whipsaw market kills accounts.\nTrigger: Stay Flat. If you can't identify the setup, walk away.",
        ),
        (
            f"FOMC in 15 minutes. Price consolidating at {poc}. Volume dropping as traders step aside.",
            f"Market State: No Setup\nLogic: Discipline. Never trade ahead of major events.\nTrigger: Stay Flat. Wait for post-event structure.",
        ),
    ]

    loc, output = random.choice(templates)
    inp = _build_input(loc, profile_shape="D", volume_bubbles="",
                       hvns=hvns, cvd_type="", price=price, vwap=vwap)
    return _chatml_entry(inp, output)


# ===================================================================
# CVD KILL SIGNAL (CVD divergence during hold → tighten/exit)
# ===================================================================

def generate_cvd_kill():
    val, vah, poc = _pick_prices()
    d = _delta(400, 1500)
    hvns = _hvn_levels(val, vah)

    templates = [
        (
            f"Holding Long from {val}. Price at {poc} but CVD diverging bearish. Buying pressure declining despite price holding.",
            poc, "BEARISH_DIV",
            f"Market State: Balance (CVD Warning)\nLogic: CVD divergence during hold. Buying pressure fading. Tighten stop or exit.\nTrigger: Stay Flat. Close or tighten stop on existing long.",
        ),
        (
            f"Holding Short from {vah}. Price at {poc} but CVD diverging bullish. Selling pressure declining despite price holding.",
            poc, "BULLISH_DIV",
            f"Market State: Balance (CVD Warning)\nLogic: CVD divergence during hold. Selling pressure fading. Tighten stop or exit.\nTrigger: Stay Flat. Close or tighten stop on existing short.",
        ),
    ]

    loc, price, cvd, output = random.choice(templates)
    vwap = _vwap_for(val, vah)
    inp = _build_input(loc, profile_shape="D", volume_bubbles="",
                       hvns=hvns, cvd_type=cvd, price=price, vwap=vwap)
    return _chatml_entry(inp, output)


# ===================================================================
# Generator distribution
# Target: ~38% LONG / ~35% SHORT / ~27% FLAT
# ===================================================================

GENERATORS = [
    (0.14, generate_aaa_long),             # 14% AAA Long
    (0.26, generate_aaa_short),            # 12% AAA Short
    (0.32, generate_momentum_long),        # 6% Momentum Long
    (0.37, generate_momentum_short),       # 5% Momentum Short
    (0.44, generate_failed_auction),       # 7% Failed Auction (mix)
    (0.50, generate_lvn_trend_long),       # 6% LVN Trend Long
    (0.55, generate_lvn_trend_short),      # 5% LVN Trend Short
    (0.60, generate_lvn_meanrev_long),     # 5% LVN MeanRev Long
    (0.64, generate_lvn_meanrev_short),    # 4% LVN MeanRev Short
    (0.68, generate_poc_scenario),         # 4% POC
    (0.73, generate_delta_divergence),     # 5% Delta Divergence
    (0.78, generate_trapped_traders),      # 5% Trapped Traders
    (0.81, generate_session_transition),   # 3% Session Transition
    (0.84, generate_cvd_kill),             # 3% CVD Kill
    (0.93, generate_risk_management),      # 9% Risk Management (FLAT)
    (1.00, generate_edge_case),            # 7% Edge Cases (FLAT)
]


def main():
    random.seed(42)
    data = []
    seen_hashes = set()
    duplicates_skipped = 0
    print(f"Generating {NUM_EXAMPLES} ChatML training examples...")

    max_attempts = NUM_EXAMPLES * 3
    attempts = 0

    while len(data) < NUM_EXAMPLES and attempts < max_attempts:
        attempts += 1
        r = random.random()
        entry = None
        for threshold, gen_func in GENERATORS:
            if r < threshold:
                entry = gen_func()
                break

        if entry is None:
            continue

        # Dedup on user content
        user_content = entry["messages"][1]["content"]
        content_hash = hashlib.md5(user_content.encode()).hexdigest()
        if content_hash in seen_hashes:
            duplicates_skipped += 1
            continue
        seen_hashes.add(content_hash)
        data.append(entry)

    output_file = "training_data_fabio.jsonl"
    with open(output_file, "w") as f:
        for entry in data:
            json.dump(entry, f)
            f.write("\n")

    # Distribution stats
    from collections import Counter
    directions = Counter()
    for entry in data:
        out = entry["messages"][2]["content"].lower()
        if "enter long" in out or "long with size" in out or "long on any" in out or "add to longs" in out:
            directions["LONG"] += 1
        elif "enter short" in out or "short with size" in out or "short on any" in out:
            directions["SHORT"] += 1
        else:
            directions["FLAT"] += 1

    print(f"Generated {len(data)} examples to {output_file}")
    print(f"Duplicates skipped: {duplicates_skipped}")
    print(f"Direction distribution: {dict(directions)}")
    pct = {k: f"{100*v/len(data):.1f}%" for k, v in directions.items()}
    print(f"Percentages: {pct}")


if __name__ == "__main__":
    main()
