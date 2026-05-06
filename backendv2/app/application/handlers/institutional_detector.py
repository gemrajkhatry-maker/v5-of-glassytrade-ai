"""Institutional activity detection helpers."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def detect_institutional_pressure(aggressive_prints: list) -> dict:
    if not aggressive_prints:
        return {"detected": False}

    volumes = [ap.volume for ap in aggressive_prints]
    if not volumes or len(volumes) < 2:
        return {"detected": False}

    sorted_vols = sorted(volumes)
    median_vol = sorted_vols[len(sorted_vols) // 2]
    if median_vol == 0:
        return {"detected": False}

    threshold = median_vol * 3
    institutional_prints = [ap for ap in aggressive_prints if ap.volume > threshold]
    if not institutional_prints:
        return {"detected": False, "median": median_vol, "threshold": threshold}

    total_inst_vol = sum(ap.volume for ap in institutional_prints)
    buy_inst = sum(ap.volume for ap in institutional_prints if getattr(ap, "side", "") == "BUY")
    sell_inst = sum(ap.volume for ap in institutional_prints if getattr(ap, "side", "") == "SELL")

    dominant = None
    if buy_inst > sell_inst * 1.5:
        dominant = "BUYING"
    elif sell_inst > buy_inst * 1.5:
        dominant = "SELLING"

    recent_prints = []
    for ap in institutional_prints[-3:]:
        recent_prints.append({
            "side": ap.side,
            "volume": float(ap.volume),
            "price": float(ap.price),
        })

    return {
        "detected": True,
        "count": len(institutional_prints),
        "threshold": threshold,
        "total_volume": total_inst_vol,
        "buy_volume": buy_inst,
        "sell_volume": sell_inst,
        "dominant": dominant,
        "recent_prints": recent_prints,
    }


def build_institutional_context(aggressive_prints: list) -> str:
    result = detect_institutional_pressure(aggressive_prints)
    if not result["detected"]:
        return ""

    parts = [f"[INSTITUTIONAL ALERT] {result['count']} large prints (>{result['threshold']:.0f} vol)"]
    parts.append(
        f"Total: {result['total_volume']:.0f} | Buy: {result['buy_volume']:.0f} | Sell: {result['sell_volume']:.0f}"
    )
    if result["dominant"]:
        parts.append(f"Dominant: INSTITUTIONAL {result['dominant']}")
    for p in result["recent_prints"]:
        parts.append(f"  {p['side']} {p['volume']:.0f} at {p['price']:.0f}")
    return " | ".join(parts)


def extract_stacked_imbalances(fp_domain: dict) -> str:
    if not fp_domain:
        return ""
    try:
        values = list(fp_domain.values()) if isinstance(fp_domain, dict) else None
        latest_fp = values[-1] if values else None
        if latest_fp and hasattr(latest_fp, "levels"):
            stacked = [lv for lv in latest_fp.levels if getattr(lv, "stacked", False)]
            if stacked:
                parts = []
                for lv in stacked[:3]:
                    side = getattr(lv, "direction", getattr(lv, "side", "UNKNOWN"))
                    price = float(getattr(lv, "price", 0))
                    parts.append(f"{side} imbalance at {price:.0f}")
                return "STACKED IMBALANCES: " + ", ".join(parts)
    except Exception:
        logger.debug("Stacked imbalance extraction failed", exc_info=True)
    return ""
