import pytest

from quant.contracts.entities import Signal
from quant.contracts.enums import SetupType, SignalType, Source
from quant.execution.order import Order, Position
from quant.execution.oms import PaperOMS


def _sig(direction="LONG"):
    return Signal.create(
        type=SignalType.BUY if direction == "LONG" else SignalType.SELL,
        price=100.0,
        reason="Triple-A",
        stop_loss=99.0,
        take_profit=102.0,
        timestamp="t0",
        setup=SetupType.TREND_MODEL,
        source=Source.LLM,
        metadata={"quant_rr": 2.0, "confidence": 0.8},
    )


def test_submit_long():
    oms = PaperOMS()
    p = oms.submit(_sig(), quantity=10)
    assert p.size == 10 and p.open_price == 100.0
    assert p.order.signal.type == SignalType.BUY


def test_submit_short_is_negative_size():
    oms = PaperOMS()
    p = oms.submit(_sig("SHORT"), quantity=5)
    assert p.size == -5


def test_close_long_profit():
    oms = PaperOMS()
    p = oms.submit(_sig(), quantity=10)
    f = oms.close(p, price=102.0, time="t1", reason="TP")
    assert f.pnl == pytest.approx((102 - 100) * 10)
    assert f.reason == "TP"


def test_close_short_profit():
    oms = PaperOMS()
    p = oms.submit(_sig("SHORT"), quantity=5)
    f = oms.close(p, price=99.0, time="t1", reason="TP")
    assert f.pnl == pytest.approx((100 - 99) * 5)
