"""Partial-depth and depth-availability behavior for microstructure metrics."""

from app.runtime.pipeline.microstructure import MicrostructureAnalysis
from app.runtime.pipeline.events import NormalizedTick


def _tick(
    *, symbol: str, price: float, bid: float, ask: float, volume: float,
    bid_volume: float, ask_volume: float, sequence: int,
) -> NormalizedTick:
    return NormalizedTick(
        symbol=symbol,
        price=price,
        volume=volume,
        timestamp=0.0,
        bid=bid,
        ask=ask,
        bid_volume=bid_volume,
        ask_volume=ask_volume,
        sequence=sequence,
        tick_size=0.05,
        lot_size=1,
        multiplier=1.0,
    )


def test_non_depth_tick_with_zero_volume_marks_depth_unavailable() -> None:
    pipeline = MicrostructureAnalysis()
    metric = pipeline.process(_tick(
        symbol="BANKNIFTY",
        price=45000.0,
        bid=44999.0,
        ask=45001.0,
        volume=100.0,
        bid_volume=0.0,
        ask_volume=0.0,
        sequence=1,
    ))[0]

    assert not metric.depth_available
    assert metric.spread == 2.0


def test_depth_tick_and_stop_run_flags() -> None:
    pipeline = MicrostructureAnalysis()
    first = pipeline.process(_tick(
        symbol="BANKNIFTY",
        price=45000.0,
        bid=44999.0,
        ask=45001.0,
        volume=100.0,
        bid_volume=40.0,
        ask_volume=60.0,
        sequence=1,
    ))[0]

    second = pipeline.process(_tick(
        symbol="BANKNIFTY",
        price=45005.0,
        bid=45004.0,
        ask=45005.5,
        volume=120.0,
        bid_volume=30.0,
        ask_volume=70.0,
        sequence=2,
    ))[0]

    assert first.depth_available
    assert second.depth_available
    assert second.stop_run_detected
