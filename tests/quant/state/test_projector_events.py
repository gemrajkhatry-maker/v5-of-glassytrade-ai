from dataclasses import dataclass

from quant.events import (
    AgentDecisionProduced,
    AmtUpdated,
    AuctionUpdated,
    BarClosed,
    DepthUpdated,
    LLMAnalysisProduced,
    OverseerProduced,
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


@dataclass(frozen=True)
class FakeVP:
    poc: float = 100.0
    vah: float = 102.0
    val: float = 98.0
    step: float = 1.0
    total_volume: float = 100.0


@dataclass(frozen=True)
class FakeVWAP:
    value: float = 100.0
    upper_1: float = 101.0
    lower_1: float = 99.0
    upper_2: float = 102.0
    lower_2: float = 98.0
    std: float = 1.0
    deviation_sigmas: float = 0.0


@dataclass(frozen=True)
class FakeOrderFlow:
    delta: float = 0.0
    cvd: float = 0.0
    cvd_slope: float = 0.0
    cvd_divergence: str = "NONE"


@dataclass(frozen=True)
class FakeLocation:
    ib_high: float = 105.0
    ib_low: float = 95.0
    ib_complete: bool = True
    zone: str = "INSIDE_VA"
    nearest_level: float = 100.0
    distance_to_level: float = 0.0


@dataclass(frozen=True)
class FakeAuction:
    time: str = "t"
    close: float = 100.0
    volume_profile: FakeVP = FakeVP()
    vwap: FakeVWAP = FakeVWAP()
    order_flow: FakeOrderFlow = FakeOrderFlow()
    absorption: object = None
    location: FakeLocation = FakeLocation()
    triple_a_phase: str = ""
    triple_a_signal: str | None = None


def test_depth_updated_folds():
    p = StateProjector()
    p.on_event(DepthUpdated(symbol="SYM", time="t1",
                            depth={"bids": [[1.0, 10.0]], "asks": [[1.1, 5.0]]}))
    assert p.snapshot("SYM").depth == {"bids": [[1.0, 10.0]], "asks": [[1.1, 5.0]]}


def test_amt_updated_folds():
    p = StateProjector()
    p.on_event(AmtUpdated(symbol="SYM", time="t1", amt={"poc": 1.0}))
    assert p.snapshot("SYM").amt["poc"] == 1.0


def test_llm_analysis_folds():
    p = StateProjector()
    p.on_event(LLMAnalysisProduced(symbol="SYM", time="t1",
                                   analysis={"direction": "LONG", "confidence": "High"}))
    assert p.snapshot("SYM").gen_ai["direction"] == "LONG"


def test_overseer_folds():
    p = StateProjector()
    p.on_event(OverseerProduced(symbol="SYM", time="t1", action="HOLD", reason="x"))
    v = p.snapshot("SYM")
    assert v.overseer_action == "HOLD"
    assert v.overseer_reason == "x"


def test_agent_decision_folds():
    p = StateProjector()
    p.on_event(AgentDecisionProduced(symbol="SYM", time="t1",
                                     decision={"direction": "SHORT", "probability": 0.7}))
    assert p.snapshot("SYM").agent_decision["direction"] == "SHORT"


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


def test_auction_updated_folds():
    p = StateProjector()
    p.on_event(AuctionUpdated(symbol="SYM", time="t1",
                              auction=FakeAuction(time="t1")))
    assert p.snapshot("SYM").auction is not None
