from quant.decision.vwap_breakout import detect_vwap_breakout as new
from app.domain.fabio_ai.services.vwap_breakout import detect_vwap_breakout as legacy
from tests.quant.parity import assert_parity


# (kwargs, expected) — cases mapped against the real branches:
#   guard (vwap<=0 or std<=0 or avg_volume<=0) -> None
#   LONG:  price > vwap+std and volume > avg_volume*1.2
#   SHORT: price < vwap-std and volume > avg_volume*1.2
#   else:  None
CASES = [
    (dict(vwap=100.0, std=1.0, price=102.0, volume=500, avg_volume=100), "LONG"),   # LONG, high volume
    (dict(vwap=100.0, std=1.0, price=98.0, volume=500, avg_volume=100), "SHORT"),   # SHORT, high volume
    (dict(vwap=100.0, std=1.0, price=100.5, volume=50, avg_volume=100), None),      # None, in-band low volume
    (dict(vwap=100.0, std=0.0, price=100.0, volume=0, avg_volume=0), None),         # None, guard: std=0
    (dict(vwap=100.0, std=1.0, price=102.0, volume=150, avg_volume=100), "LONG"),   # LONG, vol just above 1.2x
    (dict(vwap=50.0, std=0.5, price=49.0, volume=121, avg_volume=100), "SHORT"),    # SHORT, vol just above 1.2x
    (dict(vwap=100.0, std=1.0, price=102.0, volume=120, avg_volume=100), None),     # None, vol exactly 1.2x (strict >)
    (dict(vwap=0.0, std=1.0, price=102.0, volume=500, avg_volume=100), None),       # None, guard: vwap=0
    (dict(vwap=100.0, std=1.0, price=102.0, volume=500, avg_volume=0), None),       # None, guard: avg_volume=0
]


def test_parity():
    for kw, expected in CASES:
        assert_parity(legacy, new, **kw)
        assert new(**kw) == expected, f"case {kw} -> expected {expected!r}"
