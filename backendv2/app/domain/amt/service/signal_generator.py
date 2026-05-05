"""Signal generation — Triple-A signal generation per Fabio spec."""

from __future__ import annotations

from app.domain.amt.model.amt_models import VolumeProfile, Absorption

Bar = dict


def generate_signal(
    bars: list[Bar],
    absorptions: list[Absorption],
    vp: VolumeProfile,
    vwap: float,
    tp_multiplier: float = 2.0,
    min_rr: float = 1.5,
) -> dict:
    """
    Generate trading signal based on Triple-A methodology.

    LONG: BUY absorption + price > VWAP + R:R >= min_rr
    SHORT: SELL absorption + price < VWAP + R:R >= min_rr
    """
    if not absorptions or not bars:
        return {
            "type": "NO_TRADE", "entry": 0.0, "sl": 0.0, "tp": 0.0,
            "rr": 0.0, "confidence": 0.0, "reason": "No absorption",
        }

    last_abs = absorptions[-1]
    last_bar = bars[absorptions[0].bar_index] if absorptions else bars[-1]
    price = last_bar.get("close", 0)

    # LONG
    if last_abs.side == "BUY" and price > vwap:
        entry = price
        sl = vp.val - vp.step
        tp = entry + (entry - sl) * tp_multiplier
        rr = (tp - entry) / (entry - sl) if (entry - sl) != 0 else 0
        if rr >= min_rr:
            return {
                "type": "LONG", "entry": entry, "sl": sl, "tp": tp,
                "rr": rr, "confidence": last_abs.strength,
                "reason": "Triple-A BUY absorption above VWAP",
            }

    # SHORT
    if last_abs.side == "SELL" and price < vwap:
        entry = price
        sl = vp.vah + vp.step
        tp = entry - (sl - entry) * tp_multiplier
        rr = (entry - tp) / (sl - entry) if (sl - entry) != 0 else 0
        if rr >= min_rr:
            return {
                "type": "SHORT", "entry": entry, "sl": sl, "tp": tp,
                "rr": rr, "confidence": last_abs.strength,
                "reason": "Triple-A SELL absorption below VWAP",
            }

    return {
        "type": "NO_TRADE", "entry": 0.0, "sl": 0.0, "tp": 0.0,
        "rr": 0.0, "confidence": 0.0, "reason": "Conditions not met",
    }
