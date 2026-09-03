# tests/quant/amt/test_half_trend_scale_parity.py
"""Phase 3: HalfTrend scale + REST/live parity.

Two verified defects from the architectural review:

1. **Scale leak** — on an option engine with an underlying futures feed,
   ``_emit_merged_amt`` started the WS ``amt`` payload from the futures DTO
   (~24,000 scale) and only overrode profile/poc/VAH/VAL/hvns/lvns/leg*.
   ``halfTrend`` (and sessionVwap, IB/prior levels, absorption clusters,
   …) therefore rode through at FUTURES scale onto the OPTION chart
   (~50-200 scale) — the overlay was drawn tens of thousands of points
   off-scale.

2. **Live/REST time mismatch** — REST /halftrend rows carry ISO-8601 IST
   times (fetch_history normalizes), but the live WS ``amt.halfTrend.time``
   carried the raw epoch string. The frontend merges by raw timestamp
   equality, so live rows never replaced/joined history rows, and
   ``toISTTimestamp(epoch)`` is 0, dropping the live tail entirely.
"""
from __future__ import annotations

import pytest

from quant.amt.dto import amt_result_to_dto
from quant.amt.market.half_trend import HalfTrendResult
from quant.brokers.gateway import Tick
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import AMTResult
from quant.events import AmtUpdated
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


# ---------------------------------------------------------------------------
# 1. DTO time normalization (live rows must carry ISO-IST like REST rows)
# ---------------------------------------------------------------------------


def _result_with_half_trend(time: str, ht: float) -> AMTResult:
    return AMTResult(
        market_state=MarketState.BALANCED,
        poc=100.0,
        value_area_high=110.0,
        value_area_low=90.0,
        half_trend_result=HalfTrendResult(
            time=time, trend=0, ht=ht, atr_high=None, atr_low=None,
            buy_signal=False, sell_signal=False,
        ),
    )


def test_dto_normalizes_half_trend_time_to_iso_ist():
    """Epoch-string live bar times become ISO-8601 IST (REST row format)."""
    dto = amt_result_to_dto(_result_with_half_trend("1786095001", 100.0))
    t = dto["halfTrend"]["time"]
    assert t != "1786095001"
    assert t.endswith("+05:30")
    assert "T" in t
    # Same normalization the WS candle tick uses — the two merge keys match.
    from quant.state import _epoch_to_iso
    assert t == _epoch_to_iso("1786095001")


def test_dto_passes_iso_time_through_unchanged():
    """ISO inputs (REST-style bars) are not double-shifted."""
    dto = amt_result_to_dto(_result_with_half_trend("2026-08-07T14:50:00+05:30", 100.0))
    assert dto["halfTrend"]["time"] == "2026-08-07T14:50:00+05:30"


# ---------------------------------------------------------------------------
# 2. Option-engine WS merge must stay on option-premium scale
# ---------------------------------------------------------------------------


def _make_engine():
    opt = SyntheticGateway([Tick("o0", 100.0, 10, 5, 5)])
    fut = SyntheticGateway([Tick("f0", 25000.0, 100, 50, 50)])
    return QuantEngine(
        opt,
        "NIFTY 1 SEP 25000 CALL",
        interval_seconds=1,
        market="NSE",
        underlying_gateway=fut,
    )


def _futures_scale_dto():
    """A futures-scale DTO (what the underlying AMT engine produces)."""
    return {
        "halfTrend": {
            "time": "t", "trend": 0, "ht": 25010.0,
            "atrHigh": 25100.0, "atrLow": 24900.0,
            "buySignal": False, "sellSignal": False,
        },
        "sessionVwap": 25050.0,
        "vwapUpper1": 25150.0,
        "vwapLower1": 24950.0,
        "poc": 25000.0,
        "valueAreaHigh": 25200.0,
        "valueAreaLow": 24800.0,
        "ibHigh": 25200.0,
        "ibLow": 24800.0,
        "priorPoc": 25100.0,
        "profile": [{"price": 25000.0, "volume": 10}],
        "legProfile": [],
        "legLvns": [],
        "hvns": [25200.0],
        "lvns": [24800.0],
        "aggressivePrints": [],
        "npocAbove": 25100.0,
        "npocBelow": 24900.0,
        "absorptionClusterHigh": 0.0,
        "absorptionClusterLow": 0.0,
        "breakLevel": 0.0,
        "contestedZone": 0.0,
        "acceptanceAbove": 0.0,
        "acceptanceBelow": 0.0,
        "rejectionAtHigh": 0.0,
        "rejectionAtLow": 0.0,
        "squeezeTrappedLevel": 0.0,
        "dailyVah": 0.0,
        "dailyVal": 0.0,
        "dailyPoc": 0.0,
        "hourlyPoc": 0.0,
        "valueMigration": {"direction": "", "pocDrift": 0.0, "vahDrift": 0.0,
                           "valDrift": 0.0, "windowLabel": "", "hasMigration": False},
        "footprints": {},
    }


def _option_scale_dto():
    dto = _futures_scale_dto()
    dto["halfTrend"] = {
        "time": "t", "trend": 0, "ht": 100.5,
        "atrHigh": 102.0, "atrLow": 99.0,
        "buySignal": False, "sellSignal": False,
    }
    dto["sessionVwap"] = 101.0
    dto["vwapUpper1"] = 103.0
    dto["vwapLower1"] = 99.0
    dto["poc"] = 100.0
    dto["valueAreaHigh"] = 102.0
    dto["valueAreaLow"] = 98.0
    dto["ibHigh"] = 102.0
    dto["ibLow"] = 98.0
    dto["priorPoc"] = 99.0
    dto["profile"] = [{"price": 100.0, "volume": 10}]
    return dto


def test_merged_amt_uses_option_scale_half_trend():
    """Option engine + futures context: WS halfTrend is the OPTION's, never
    the futures' (the review's off-scale overlay)."""
    eng = _make_engine()
    eng._underlying_amt_dto = _futures_scale_dto()
    eng._option_amt_dto = _option_scale_dto()
    eng._emit_merged_amt(eng._underlying_amt_dto, "t")
    evt = eng._trace[-1]
    assert isinstance(evt, AmtUpdated)
    assert evt.amt["halfTrend"]["ht"] == pytest.approx(100.5)
    assert evt.amt["halfTrend"]["atrHigh"] == pytest.approx(102.0)
    assert evt.amt["sessionVwap"] == pytest.approx(101.0)
    assert evt.amt["vwapUpper1"] == pytest.approx(103.0)
    assert evt.amt["poc"] == pytest.approx(100.0)
    assert evt.amt["ibHigh"] == pytest.approx(102.0)
    assert evt.amt["priorPoc"] == pytest.approx(99.0)


def test_merged_amt_clears_option_scale_keys_when_option_dto_missing():
    """Before the option engine has analysis, futures-scale values must NOT
    ride through — the safe empty shape replaces them."""
    eng = _make_engine()
    eng._underlying_amt_dto = _futures_scale_dto()
    eng._option_amt_dto = None  # fresh option engine: last_amt_dto is also None
    eng._emit_merged_amt(eng._underlying_amt_dto, "t")
    evt = eng._trace[-1]
    assert isinstance(evt, AmtUpdated)
    assert evt.amt["halfTrend"]["ht"] == 0.0
    assert evt.amt["sessionVwap"] == 0.0
    assert evt.amt["poc"] == 0.0
    assert evt.amt["profile"] == []
    # Futures-scale values must be gone entirely.
    assert evt.amt["halfTrend"]["ht"] != pytest.approx(25010.0)


def test_live_engine_run_emits_option_scale_half_trend():
    """End-to-end: driving an option engine + futures gateway produces WS
    halfTrend rows on the option scale, never the futures scale."""
    opt_ticks = [Tick(f"o{i}", 100.0 + (i % 3), 10, 6, 4) for i in range(12)]
    fut_ticks = [Tick(f"f{i}", 25000.0 + (i % 5), 100, 60, 40) for i in range(12)]
    eng = QuantEngine(
        SyntheticGateway(opt_ticks),
        "NIFTY 1 SEP 25000 CALL",
        interval_seconds=1,
        market="NSE",
        underlying_gateway=SyntheticGateway(fut_ticks),
    )
    eng.run()

    updates = [e for e in eng._trace if isinstance(e, AmtUpdated)]
    assert updates, "expected WS amt updates"

    # Sanity: the futures engine really did produce futures-scale halfTrend
    # (proves this test would catch a leak back to the old behavior).
    fut_ht = (eng._underlying_amt_dto or {}).get("halfTrend") or {}
    if fut_ht.get("ht"):
        assert fut_ht["ht"] > 10000, "futures-scale ht must be far from option scale"

    seen_option_ht = False
    for e in updates:
        ht = (e.amt or {}).get("halfTrend") or {}
        if ht.get("ht"):
            seen_option_ht = True
            assert abs(ht["ht"]) < 1000, (
                f"WS halfTrend ht={ht['ht']} leaked futures scale onto the option chart"
            )
        vwap = (e.amt or {}).get("sessionVwap") or 0.0
        if vwap:
            assert abs(vwap) < 1000, (
                f"WS sessionVwap={vwap} leaked futures scale onto the option chart"
            )
    assert seen_option_ht, "expected at least one option-scale halfTrend row"