# tests/quant/test_ws_contract.py
"""Tests for the WebSocket schema contract.

Verifies that the WS snapshot produced by view_state_to_ws() contains all
the keys the frontend expects, and that the contract module's validation
functions work correctly.
"""

import pytest

from quant.ws_contract import (
    WS_SNAPSHOT_KEYS,
    WS_PORTFOLIO_KEYS,
    WS_AGENT_DECISION_KEYS,
    WSSnapshot,
    WSPortfolio,
    WSAgentDecision,
    validate_ws_snapshot,
)
from quant.ws_adapter import view_state_to_ws
from quant.state import StateProjector
from quant.events import BarClosed
from quant.bars import Bar


def _make_view_state():
    """Create a minimal ViewState for testing."""
    projector = StateProjector()
    projector.on_event(BarClosed(
        symbol="SYM", time="t0",
        bar=Bar(time="t0", open=100, high=101, low=99, close=100, volume=100),
    ))
    return projector.snapshot("SYM")


class TestWSSnapshotKeys:
    """Verify the WS snapshot has all required keys."""

    def test_snapshot_has_all_frontend_keys(self):
        """The view_state_to_ws output must contain all keys the frontend expects."""
        vs = _make_view_state()
        snapshot = view_state_to_ws(vs)
        
        missing = validate_ws_snapshot(snapshot)
        assert not missing, f"Missing WS snapshot keys: {missing}"

    def test_snapshot_keys_constant_matches_adapter(self):
        """WS_SNAPSHOT_KEYS should match what view_state_to_ws produces."""
        vs = _make_view_state()
        snapshot = view_state_to_ws(vs)
        
        assert set(snapshot.keys()) == WS_SNAPSHOT_KEYS


class TestWSPortfolio:
    """Verify the portfolio sub-schema."""

    def test_portfolio_has_required_keys(self):
        portfolio = WSPortfolio()
        d = {
            "balance": portfolio.balance,
            "equity": portfolio.equity,
            "leverage": portfolio.leverage,
            "positions": portfolio.positions,
            "closedTrades": portfolio.closedTrades,
        }
        assert set(d.keys()) == WS_PORTFOLIO_KEYS

    def test_portfolio_defaults(self):
        portfolio = WSPortfolio()
        assert portfolio.balance == 1_000_000.0
        assert portfolio.equity == 1_000_000.0
        assert portfolio.leverage == 10
        assert portfolio.positions == []
        assert portfolio.closedTrades == []


class TestWSAgentDecision:
    """Verify the agent decision sub-schema."""

    def test_agent_decision_has_required_keys(self):
        ad = WSAgentDecision()
        d = {
            "direction": ad.direction,
            "modelLabel": ad.modelLabel,
            "regime": ad.regime,
            "timing": ad.timing,
            "sizeFraction": ad.sizeFraction,
            "latencyUs": ad.latencyUs,
            "rationale": ad.rationale,
        }
        assert set(d.keys()) == WS_AGENT_DECISION_KEYS

    def test_agent_decision_defaults(self):
        ad = WSAgentDecision()
        assert ad.direction == "FLAT"
        assert ad.modelLabel == ""
        assert ad.regime == ""


class TestWSSnapshotDataclass:
    """Verify the WSSnapshot dataclass."""

    def test_snapshot_to_dict(self):
        snapshot = WSSnapshot(
            _symbol="NIFTY",
            portfolio=WSPortfolio(),
            ltp=24500.0,
            oi=100000,
        )
        d = snapshot.to_dict()
        assert d["_symbol"] == "NIFTY"
        assert d["ltp"] == 24500.0
        assert d["oi"] == 100000
        assert d["portfolio"]["balance"] == 1_000_000.0

    def test_snapshot_with_dict_portfolio(self):
        snapshot = WSSnapshot(
            _symbol="NIFTY",
            portfolio={"balance": 500000.0, "equity": 500000.0, "leverage": 5, "positions": [], "closedTrades": []},
        )
        d = snapshot.to_dict()
        assert d["portfolio"]["balance"] == 500000.0


class TestValidateWsSnapshot:
    """Verify the validation function."""

    def test_valid_snapshot_returns_empty(self):
        snapshot = {
            "_symbol": "NIFTY",
            "portfolio": {},
            "amt": None,
            "quantDecision": None,
            "agentDecision": None,
            "riskState": None,
            "tick": None,
            "ltp": 0.0,
            "oi": 0,
            "depth": {},
        }
        assert validate_ws_snapshot(snapshot) == []

    def test_missing_keys_returned(self):
        snapshot = {"_symbol": "NIFTY"}
        missing = validate_ws_snapshot(snapshot)
        assert len(missing) == len(WS_SNAPSHOT_KEYS) - 1
        assert "_symbol" not in missing
