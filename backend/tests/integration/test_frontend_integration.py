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
    # Patch service graph before importing app
    with patch("app.api.dependencies.get_service_graph") as mock_graph:
        mock = MagicMock()
        mock.trading_session = MagicMock()
        mock.llm_inference = MagicMock()
        mock.llm_inference.is_ready.return_value = True
        mock.probability_engine = MagicMock()
        mock.probability_engine.is_ready.return_value = True
        mock.active_symbols = ["NIFTY 24 FEB 25750 CALL"]
        mock.market_data = MagicMock()
        mock_graph.return_value = mock

        from app.main import app as fastapi_app
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
        assert "llmReady" in data
        assert "probabilityReady" in data


class TestAICommand:
    def test_command_symbol_switch(self, client):
        c, _ = client
        res = c.post("/api/ai/command", json={
            "prompt": "show me nifty",
            "currentConfig": {"symbol": "NIFTY"},
        })
        assert res.status_code == 200
        data = res.json()
        assert "message" in data
        assert data["configUpdates"]["symbol"] == "NIFTY"
        assert data["action"] == "UPDATE_CONFIG"

    def test_command_interval(self, client):
        c, _ = client
        res = c.post("/api/ai/command", json={
            "prompt": "set interval 15m",
            "currentConfig": {},
        })
        data = res.json()
        assert data["configUpdates"]["interval"] == "15m"

    def test_command_unknown(self, client):
        c, _ = client
        res = c.post("/api/ai/command", json={
            "prompt": "xyzzy foobar",
            "currentConfig": {},
        })
        data = res.json()
        assert data["configUpdates"] is None
        assert data["action"] is None

    def test_command_volume_profile_toggle(self, client):
        c, _ = client
        res = c.post("/api/ai/command", json={
            "prompt": "hide volume profile",
            "currentConfig": {},
        })
        data = res.json()
        assert data["configUpdates"]["showVolumeProfile"] == False
        assert data["configUpdates"]["vpMode"] == "off"


class TestAIHistory:
    def test_history_endpoint_exists(self, client):
        c, mock = client
        res = c.get("/api/ai/history")
        # Should return 200 (even if storage returns empty/mock data)
        assert res.status_code == 200
        data = res.json()
        assert "decisions" in data


# =====================================================================
# WebSocket gameloop tests
# =====================================================================

class TestWebSocketGameloop:
    def test_client_driven_tick(self, client):
        """Test client-driven mode: send tick, get state snapshot back."""
        c, mock = client

        # Mock process_tick to return a valid state snapshot
        mock.trading_session.process_tick.return_value = {
            "_symbol": "NIFTY",
            "portfolio": {
                "balance": 1_000_000,
                "equity": 1_000_000,
                "leverage": 10,
                "positions": [],
                "closedTrades": [],
                "history": [],
            },
            "amt": {
                "marketState": "BALANCED",
                "poc": 67500,
                "valueAreaHigh": 67600,
                "valueAreaLow": 67400,
                "lvns": [],
                "hvns": [],
                "aggression": 0.5,
                "signal": None,
                "setup": None,
                "profile": [],
                "aggressivePrints": [],
            },
            "genAIAnalysis": {
                "direction": "FLAT",
                "rationale": "Waiting",
                "confidence": "Low",
                "inputPrompt": "",
                "rawOutput": "",
            },
            "stats": {
                "totalTrades": 0,
                "wins": 0,
                "losses": 0,
                "winRate": 0,
                "netProfit": 0,
                "avgProfit": 0,
                "largestWin": 0,
                "largestLoss": 0,
            },
            "riskState": {
                "halted": False,
                "haltReason": "",
                "consecutiveLosses": 0,
                "dailyPnl": 0,
            },
            "overseerAction": "",
            "overseerReason": "",
            "modelWeights": {"trend": 0.4, "momentum": 0.25, "delta": 0.15, "orderBook": 0.15, "volatility": 0.05},
            "generation": 0,
        }

        with c.websocket_connect("/api/trading/ws/gameloop") as ws:
            # Send a valid tick
            ws.send_json({
                "symbol": "NIFTY",
                "tick": {
                    "time": "2026-02-23T10:00:00Z",
                    "open": 67500,
                    "high": 67600,
                    "low": 67400,
                    "close": 67550,
                    "volume": 1000,
                    "vwap": 67500,
                    "takerBuyVolume": 600,
                    "delta": 200,
                },
            })

            state = ws.receive_json()

            # Verify frontend-expected keys
            assert state["_symbol"] == "NIFTY"
            assert "portfolio" in state
            assert "balance" in state["portfolio"]
            assert "equity" in state["portfolio"]
            assert "positions" in state["portfolio"]
            assert "closedTrades" in state["portfolio"]
            assert "amt" in state
            assert "genAIAnalysis" in state
            assert "stats" in state
            assert "riskState" in state
            assert "overseerAction" in state
            assert "overseerReason" in state
            assert "modelWeights" in state

    def test_history_seeding(self, client):
        """Test history seeding message."""
        c, mock = client
        mock.trading_session.get_or_create_session.return_value = MagicMock(data=[])

        with c.websocket_connect("/api/trading/ws/gameloop") as ws:
            ws.send_json({
                "symbol": "NIFTY",
                "history": [
                    {"time": "2026-02-23T09:00:00Z", "open": 67000, "high": 67100,
                     "low": 66900, "close": 67050, "volume": 500, "vwap": 67000,
                     "takerBuyVolume": 300, "delta": 100},
                ],
            })

            response = ws.receive_json()
            assert response["status"] == "history_loaded"

    def test_invalid_tick_rejected(self, client):
        """Test that invalid ticks are rejected with error."""
        c, mock = client

        with c.websocket_connect("/api/trading/ws/gameloop") as ws:
            # Send tick with high < low
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
        from app.domain.trading.models.aggregates import Portfolio

        p = Portfolio.create_default()
        dto = portfolio_to_dto(p)

        # Frontend Portfolio interface expects these keys
        assert "balance" in dto
        assert "equity" in dto
        assert "leverage" in dto
        assert "positions" in dto
        assert "closedTrades" in dto  # camelCase
        assert "history" in dto

    def test_amt_result_dto_keys(self):
        from app.infrastructure.serialization.schemas import amt_result_to_dto

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
        from app.domain.trading.models.value_objects import StrategyStats

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

    def test_genai_analysis_camelcase(self):
        """Verify _camel_case_ai produces keys matching frontend GenAIAnalysis."""
        from app.application.services.trading_session import TradingSessionService

        result = TradingSessionService._camel_case_ai({
            "direction": "LONG",
            "rationale": "test",
            "confidence": "High",
            "input_prompt": "prompt...",
            "raw_output": "output...",
            "market_state": "BALANCED",
            "aggression": "0.50",
        })

        # Frontend GenAIAnalysis interface
        assert result["direction"] == "LONG"
        assert result["rationale"] == "test"
        assert result["confidence"] == "High"
        assert result["inputPrompt"] == "prompt..."  # camelCase
        assert result["rawOutput"] == "output..."
        assert result["marketState"] == "BALANCED"
        assert result["aggression"] == "0.50"
