"""Integration tests for frontend ↔ backend contract.

Tests the WebSocket gameloop, REST endpoints, and DTO serialization
to verify the exact JSON shape the frontend expects.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create a minimal FastAPI app with all routers mounted."""
    from app.main import app as fastapi_app
    mock = MagicMock()
    mock.trading_session = MagicMock()
    mock.llm_inference = MagicMock()
    mock.llm_inference.is_ready.return_value = True
    mock.probability_engine = MagicMock()
    mock.probability_engine.is_ready.return_value = True
    mock.active_symbols = ["NIFTY 24 FEB 25750 CALL"]
    mock.market_data = MagicMock()
    fastapi_app.state.service_graph = mock

    yield fastapi_app, mock


@pytest.fixture
def client(app):
    app_inst, mock = app
    return TestClient(app_inst), mock


# =====================================================================
# REST endpoint tests
# =====================================================================

class TestHealthEndpoints:
    def test_health(self, client):
        c, _ = client
        res = c.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_system_config(self, client):
        c, _ = client
        res = c.get("/api/system/config")
        assert res.status_code == 200
        data = res.json()
        # Frontend expects these keys
        assert "dataSource" in data
        assert "serverDriven" in data
        assert "defaultSymbol" in data
        assert "activeSymbols" in data
        assert isinstance(data["activeSymbols"], list)
        assert len(data["activeSymbols"]) >= 1
        assert data["defaultSymbol"] == data["activeSymbols"][0]
        assert "probabilityReady" in data
        assert "playbookGuardMaxRejections" in data
        assert "explainabilityAlertMinTrades" in data
        assert "explainabilityMinCoverageRate" in data
        assert "explainabilityMinAggressionRate" in data


class TestAIHistory:
    def test_history_endpoint_removed_with_llm_layer(self, client):
        """The /api/ai/history endpoint was removed with the LLM layer;
        decision history is now streamed over WS as deterministic quantDecision
        events only."""
        c, mock = client
        res = c.get("/api/ai/history")
        assert res.status_code == 404


# =====================================================================
# WebSocket gameloop tests
# =====================================================================

class TestWebSocketGameloop:
    """WebSocket viewer contract.

    The legacy client-driven mode (process_tick / history seeding via the
    TradingSessionService) was removed in the backend swap — the WS is now a
    read-only viewer over QuantCoordinator snapshots. These tests verify the
    viewer rejects unsupported payloads cleanly.
    """

    def test_invalid_payload_rejected(self, client):
        """Test that a non-subscribe payload is rejected with an error."""
        c, mock = client

        with c.websocket_connect("/api/trading/ws/gameloop") as ws:
            # Client-driven tick mode no longer exists — must be rejected
            ws.send_json({
                "symbol": "NIFTY",
                "tick": {
                    "time": "2026-02-23T10:00:00Z",
                    "open": 67500,
                    "high": 67000,  # high < low = invalid
                    "low": 67400,
                    "close": 67550,
                    "volume": 1000,
                },
            })

            response = ws.receive_json()
            assert "error" in response


# =====================================================================
# DTO serialization contract tests
# =====================================================================

class TestDTOContract:
    """Verify DTOs produce camelCase keys matching frontend types.ts."""

    def test_portfolio_dto_keys(self):
        from app.infrastructure.serialization.schemas import portfolio_to_dto
        from quant.contracts.aggregates import Portfolio

        p = Portfolio.create_default()
        dto = portfolio_to_dto(p)

        # Frontend Portfolio interface expects these keys
        assert "balance" in dto
        assert "equity" in dto
        assert "leverage" in dto
        assert "positions" in dto
        assert "closedTrades" in dto  # camelCase

    def test_amt_result_dto_keys(self):
        from quant.amt.dto import amt_result_to_dto

        amt = MagicMock()
        amt.market_state = "BALANCED"
        amt.poc = 100
        amt.value_area_high = 105
        amt.value_area_low = 95
        amt.lvns = [98, 102]
        amt.hvns = [100]
        amt.aggression = 0.5
        amt.signal = None
        amt.setup = None
        amt.profile = []
        amt.aggressive_prints = []
        amt.cvd_slope = 0.1
        amt.cvd_divergence = ""
        amt.profile_shape = "D"
        amt.session_vwap = 100
        amt.vwap_upper_1 = 102
        amt.vwap_lower_1 = 98
        amt.vwap_upper_2 = 104
        amt.vwap_lower_2 = 96
        amt.balance_ratio = 1.0
        amt.leg_profile = []
        amt.leg_lvns = []
        amt.leg_poc = 0
        amt.leg_vah = 0
        amt.leg_val = 0
        amt.has_displacement = False

        dto = amt_result_to_dto(amt)

        # Frontend AMTAnalysis interface expects camelCase
        assert "marketState" in dto
        assert "poc" in dto
        assert "valueAreaHigh" in dto
        assert "valueAreaLow" in dto
        assert "lvns" in dto
        assert "hvns" in dto
        assert "aggression" in dto
        assert "aggressivePrints" in dto
        assert "cvdSlope" in dto
        assert "profileShape" in dto
        assert "legProfile" in dto
        assert "legPoc" in dto
        assert "hasDisplacement" in dto

    def test_stats_dto_keys(self):
        from app.infrastructure.serialization.schemas import stats_to_dto
        from quant.contracts.value_objects import StrategyStats

        s = StrategyStats(
            total_trades=5, wins=3, losses=2, win_rate=60.0,
            net_profit=500, avg_profit=100, largest_win=250, largest_loss=-100,
        )
        dto = stats_to_dto(s)

        # Frontend StrategyStats interface expects camelCase
        assert "totalTrades" in dto
        assert "wins" in dto
        assert "losses" in dto
        assert "winRate" in dto
        assert "netProfit" in dto
        assert "avgProfit" in dto
        assert "largestWin" in dto
        assert "largestLoss" in dto

    def test_genai_analysis_removed_with_llm_layer(self):
        """The projector no longer exposes a gen_ai (LLM) view — decision data
        is carried by the deterministic quantDecision/agentDecision keys only."""
        from quant.state import StateProjector

        projector = StateProjector()
        snapshot = projector.snapshot("SYM")
        assert not hasattr(snapshot, "gen_ai")
        assert not hasattr(snapshot, "overseer")
        assert hasattr(snapshot, "quant_decision")
