"""VWAP-band breakout detector with volume confirmation.

Pure, dependency-free signal detection for the AMT scalper backend.
"""


def detect_vwap_breakout(
    vwap: float, std: float, price: float, volume: float, avg_volume: float
) -> str | None:
    """Return 'LONG'/'SHORT' on a VWAP-band breakout with volume confirmation, else None."""
    if vwap <= 0 or std <= 0 or avg_volume <= 0:
        return None
    if price > vwap + std and volume > avg_volume * 1.2:
        return "LONG"
    if price < vwap - std and volume > avg_volume * 1.2:
        return "SHORT"
    return None
