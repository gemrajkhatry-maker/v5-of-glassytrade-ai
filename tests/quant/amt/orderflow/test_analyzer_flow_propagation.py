"""The active analyzer supplies candidate direction to order-flow scoring."""

from types import SimpleNamespace
from unittest.mock import patch

from quant.amt.analyzer import AMTAnalyzer
from quant.contracts.value_objects import OHLC


def _bar(index: int) -> OHLC:
    return OHLC(
        time=f"2026-01-01T00:0{index}:00Z",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=100.0,
        vwap=100.0,
        taker_buy_volume=50.0,
        delta=0.0,
    )


def test_analyzer_passes_candidate_direction_to_order_flow_compute():
    with patch("quant.amt.orderflow.compute.compute_order_flow_metrics") as compute:
        compute.return_value = {
            "avg_candle_vol": 0.0, "obi": 0.0, "toxicity": 0.0,
            "norm_delta": 0.0, "footprint_confirmed": False,
            "cvd_confirmed": False, "cvd_state": None,
            "big_trade_confirmed": False, "absorption_detected": False,
            "absorption_side": "", "absorption_range_ratio": 0.0,
            "absorption_vol_ratio": 0.0, "absorption_active": False,
            "absorption_cluster_high": 0.0, "absorption_cluster_low": 0.0,
            "ofi_result": SimpleNamespace(ofi=0.0), "ofi_aligned": False,
            "confluence_bonus": False, "volume_bubble_near": False,
            "agg_result": None, "aggression_score": 0.0,
            "has_aggression": False,
        }
        AMTAnalyzer().analyze([_bar(i) for i in range(5)], candidate_direction="LONG")

    assert compute.call_args is not None
    assert compute.call_args.kwargs["candidate_direction"] in {"LONG", "SHORT"}
