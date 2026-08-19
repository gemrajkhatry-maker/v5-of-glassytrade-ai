from dataclasses import dataclass

from quant.events import (
    AmtUpdated,
    BarClosed,
    DepthUpdated,
)
from quant.state import StateProjector


@dataclass(frozen=True)
class FakeBar:
    time: str
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta: float = 0.0
    oi: float = 0.0





def test_depth_updated_folds():
    p = StateProjector()
    p.on_event(DepthUpdated(symbol="SYM", time="t1",
                            depth={"bids": [[1.0, 10.0]], "asks": [[1.1, 5.0]]}))
    assert p.snapshot("SYM").depth == {"bids": [[1.0, 10.0]], "asks": [[1.1, 5.0]]}


def test_amt_updated_folds():
    p = StateProjector()
    p.on_event(AmtUpdated(symbol="SYM", time="t1", amt={"poc": 1.0}))
    assert p.snapshot("SYM").amt["poc"] == 1.0


def test_bar_close_folds_oi():
    p = StateProjector()
    p.on_event(BarClosed(symbol="SYM", time="t1",
                         bar=FakeBar(time="t1", open=100, high=101, low=99,
                                     close=100, volume=100, oi=42)))
    assert p.snapshot("SYM").oi == 42.0


def test_oi_default_zero_when_no_bar_oi():
    p = StateProjector()
    p.on_event(BarClosed(symbol="SYM", time="t1",
                         bar=FakeBar(time="t1", open=100, high=101, low=99,
                                     close=100, volume=100)))
    assert p.snapshot("SYM").oi == 0.0



