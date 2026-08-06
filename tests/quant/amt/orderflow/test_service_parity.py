"""Parity: order_flow_service moved module vs legacy shim.

Compare OrderFlowService.compute_metrics on a fixed candle + order book input.
OrderFlowMetrics is a plain object (not a dataclass), so we serialize its
public attributes to comparable dicts and diff them with assert_parity.
"""

from quant.amt.orderflow.service import OrderFlowService as NewService
from app.domain.fabio_ai.services.order_flow_service import OrderFlowService as LegacyService
from quant.contracts.value_objects import OHLC, OrderBook
from tests.quant.parity import assert_parity


def _candle(time, o, h, l, c, v, d):
    return OHLC(time, o, h, l, c, v, d)


def _order_book():
    return OrderBook(
        bids=[type("Bid", (), {"quantity": 100})(), type("Bid", (), {"quantity": 80})()],
        asks=[type("Ask", (), {"quantity": 50})(), type("Ask", (), {"quantity": 60})()],
    )


def _run(factory, data, order_book):
    return _run2(factory, data, order_book, data[-1] if data else None)


def _run2(factory, data, order_book, current):
    service = factory()
    metrics = service.compute_metrics(
        recent_data=data,
        order_book=order_book,
        current=current,
        agg_prints=[],
        market_state=type("MS", (), {"name": "BALANCED"})(),
        lvns=[98.0, 103.0],
        vah=105.0,
        val=95.0,
        poc=100.0,
        tick_size=0.05,
    )
    return {k: getattr(metrics, k) for k in (
        "avg_candle_vol", "obi", "toxicity", "norm_delta", "footprint_confirmed",
        "cvd_confirmed", "big_trade_confirmed", "absorption_detected",
        "absorption_side", "absorption_range_ratio", "absorption_vol_ratio",
        "ofi_aligned", "confluence_bonus", "volume_bubble_near",
        "aggression_score", "has_aggression",
    )}


def test_parity_compute_metrics_empty():
    data = []
    current = _candle("2024-01-01 09:15:00", 100, 102, 99, 101, 100, 10)
    assert_parity(lambda: _run2(LegacyService, data, None, current),
                  lambda: _run2(NewService, data, None, current))


def test_parity_compute_metrics_with_candles_and_book():
    data = [
        _candle("2024-01-01 09:15:00", 100, 102, 99, 101, 100, 10),
        _candle("2024-01-01 09:16:00", 101, 103, 100, 102, 150, 15),
        _candle("2024-01-01 09:17:00", 102, 104, 101, 103, 200, -20),
    ]
    assert_parity(lambda: _run(LegacyService, data, _order_book()),
                  lambda: _run(NewService, data, _order_book()))
