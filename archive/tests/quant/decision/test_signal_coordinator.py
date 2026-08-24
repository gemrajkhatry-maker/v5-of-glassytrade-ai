"""Tests for SignalCoordinator."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from quant.decision.signal_coordinator import SignalCoordinator, EntryEvaluation


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


def test_signal_coordinator_flats_when_has_position():
    """SignalCoordinator returns FLAT when position exists."""
    coordinator = SignalCoordinator()
    agent = MockAgentDecision(direction="LONG", probability=0.7, timing="ENTER_NOW")
    amt = MockAMTResult(market_state="IMBALANCED")
    session = MockSessionInfo(allow_entry=True)
    
    result = coordinator.evaluate_entry(
        agent_decision=agent,
        amt_result=amt,
        tick=None,
        session_info=session,
        confirmation_strong=True,
        is_new_candle=True,
        is_overseer_running=False,
        has_position=True,
    )
    assert result.should_enter is False
    assert result.direction == "FLAT"


def test_signal_coordinator_flats_when_no_agent_decision():
    """SignalCoordinator returns FLAT when no agent decision."""
    coordinator = SignalCoordinator()
    amt = MockAMTResult(market_state="IMBALANCED")
    session = MockSessionInfo(allow_entry=True)
    
    result = coordinator.evaluate_entry(
        agent_decision=None,
        amt_result=amt,
        tick=None,
        session_info=session,
        confirmation_strong=True,
        is_new_candle=True,
        is_overseer_running=False,
        has_position=False,
    )
    assert result.should_enter is False


def test_signal_coordinator_flats_when_overseer_running():
    """SignalCoordinator returns FLAT when overseer is running."""
    coordinator = SignalCoordinator()
    agent = MockAgentDecision(direction="LONG", probability=0.7, timing="ENTER_NOW")
    amt = MockAMTResult(market_state="IMBALANCED")
    session = MockSessionInfo(allow_entry=True)
    
    result = coordinator.evaluate_entry(
        agent_decision=agent,
        amt_result=amt,
        tick=None,
        session_info=session,
        confirmation_strong=True,
        is_new_candle=True,
        is_overseer_running=True,
        has_position=False,
    )
    assert result.should_enter is False
    assert result.timing == "WAIT"


def test_signal_coordinator_high_conviction():
    """SignalCoordinator returns HIGH conviction for high probability."""
    coordinator = SignalCoordinator()
    agent = MockAgentDecision(direction="LONG", probability=0.85, timing="ENTER_NOW")
    amt = MockAMTResult(market_state="IMBALANCED")
    session = MockSessionInfo(allow_entry=True)
    
    result = coordinator.evaluate_entry(
        agent_decision=agent,
        amt_result=amt,
        tick=None,
        session_info=session,
        confirmation_strong=True,
        is_new_candle=True,
        is_overseer_running=False,
        has_position=False,
    )
    assert result.should_enter is True
    assert result.conviction == "HIGH"


def test_signal_coordinator_medium_conviction():
    """SignalCoordinator returns MEDIUM conviction for medium probability."""
    coordinator = SignalCoordinator()
    agent = MockAgentDecision(direction="LONG", probability=0.60, timing="ENTER_NOW")
    amt = MockAMTResult(market_state="BALANCED")
    session = MockSessionInfo(allow_entry=True)
    
    result = coordinator.evaluate_entry(
        agent_decision=agent,
        amt_result=amt,
        tick=None,
        session_info=session,
        confirmation_strong=True,
        is_new_candle=True,
        is_overseer_running=False,
        has_position=False,
    )
    assert result.should_enter is True
    assert result.conviction == "MEDIUM"


def test_signal_coordinator_short_not_allowed():
    """SignalCoordinator blocks SHORT when not allowed."""
    coordinator = SignalCoordinator()
    agent = MockAgentDecision(direction="SHORT", probability=0.7, timing="ENTER_NOW")
    amt = MockAMTResult(market_state="IMBALANCED")
    session = MockSessionInfo(allow_entry=True)
    
    result = coordinator.evaluate_entry(
        agent_decision=agent,
        amt_result=amt,
        tick=None,
        session_info=session,
        confirmation_strong=True,
        is_new_candle=True,
        is_overseer_running=False,
        has_position=False,
        allow_short=False,
    )
    assert result.should_enter is False


def test_signal_coordinator_setup_type_mean_reversion():
    """SignalCoordinator returns MEAN_REVERSION for BALANCED state."""
    coordinator = SignalCoordinator()
    agent = MockAgentDecision(direction="LONG", probability=0.85, timing="ENTER_NOW")
    amt = MockAMTResult(market_state="BALANCED")
    session = MockSessionInfo(allow_entry=True)
    
    result = coordinator.evaluate_entry(
        agent_decision=agent,
        amt_result=amt,
        tick=None,
        session_info=session,
        confirmation_strong=True,
        is_new_candle=True,
        is_overseer_running=False,
        has_position=False,
    )
    assert result.setup_type == "MEAN_REVERSION"


def test_signal_coordinator_setup_type_trend():
    """SignalCoordinator returns TREND_CONTINUATION for IMBALANCED state."""
    coordinator = SignalCoordinator()
    agent = MockAgentDecision(direction="LONG", probability=0.85, timing="ENTER_NOW")
    amt = MockAMTResult(market_state="IMBALANCED")
    session = MockSessionInfo(allow_entry=True)
    
    result = coordinator.evaluate_entry(
        agent_decision=agent,
        amt_result=amt,
        tick=None,
        session_info=session,
        confirmation_strong=True,
        is_new_candle=True,
        is_overseer_running=False,
        has_position=False,
    )
    assert result.setup_type == "TREND_CONTINUATION"