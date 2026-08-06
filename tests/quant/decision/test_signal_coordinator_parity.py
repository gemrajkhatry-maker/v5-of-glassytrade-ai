"""Parity: SignalCoordinator.evaluate_entry via legacy shim vs moved quant module."""

from __future__ import annotations

from dataclasses import dataclass

from quant.decision.signal_coordinator import SignalCoordinator
from tests.quant.parity import assert_parity


@dataclass
class MockAgentDecision:
    direction: str
    probability: float
    timing: str


@dataclass
class MockAMTResult:
    market_state: str


@dataclass
class MockSessionInfo:
    allow_entry: bool


def _kwargs(direction="LONG", probability=0.85, market_state="IMBALANCED",
            allow_entry=True, confirmation_strong=True, has_position=False,
            is_overseer_running=False, allow_short=True):
    return dict(
        agent_decision=MockAgentDecision(direction=direction, probability=probability, timing="ENTER_NOW"),
        amt_result=MockAMTResult(market_state=market_state),
        tick=None,
        session_info=MockSessionInfo(allow_entry=allow_entry),
        confirmation_strong=confirmation_strong,
        is_new_candle=True,
        is_overseer_running=is_overseer_running,
        has_position=has_position,
        allow_short=allow_short,
    )


def test_high_conviction_parity():
    SignalCoordinator().evaluate_entry(**_kwargs())


def test_flat_has_position_parity():
    SignalCoordinator().evaluate_entry(**_kwargs(has_position=True))


def test_short_not_allowed_parity():
    SignalCoordinator().evaluate_entry(**_kwargs(direction="SHORT", probability=0.7, allow_short=False))


def test_medium_conviction_parity():
    SignalCoordinator().evaluate_entry(**_kwargs(direction="LONG", probability=0.60, market_state="BALANCED"))
