"""Integration tests for FastAPI REST endpoints via TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.dependencies import get_storage


client = TestClient(app)


class TestHealthEndpoint:
    def test_health_ok(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "checks" in body


class TestTradingEndpoints:
    def test_create_portfolio(self):
        r = client.post("/api/trading/portfolio/create")
        assert r.status_code == 200
        body = r.json()
        assert "balance" in body
        assert "equity" in body
        assert "positions" in body
        assert isinstance(body["balance"], (int, float))
        assert body["balance"] > 0

    def test_compute_stats_empty(self):
        r = client.post(
            "/api/trading/stats",
            json={"closedTrades": [], "source": "AMT"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["totalTrades"] == 0
        assert body["winRate"] == 0

    def test_get_position_events(self):
        class _StubStorage:
            def query_position_events(self, position_id=None, symbol=None):
                assert position_id == "P1"
                assert symbol == "NIFTY25000CE"
                return [
                    {
                        "id": 1,
                        "event_id": "evt-open-1",
                        "position_id": "P1",
                        "symbol": "NIFTY25000CE",
                        "event_type": "OPENED",
                        "event_time": "2026-01-01T09:15:00Z",
                        "created_at": "2026-01-01T09:15:01Z",
                        "side": "LONG",
                        "entry_price": 100.5,
                        "stop_loss": 99.0,
                        "take_profit": 104.0,
                    }
                ]

        app.dependency_overrides[get_storage] = lambda: _StubStorage()
        try:
            r = client.get(
                "/api/trading/positions/events",
                params={"positionId": "P1", "symbol": "NIFTY25000CE"},
            )
        finally:
            app.dependency_overrides.pop(get_storage, None)

        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["events"][0]["positionId"] == "P1"
        assert body["events"][0]["eventId"] == "evt-open-1"
        assert body["events"][0]["eventType"] == "OPENED"
        assert body["events"][0]["entryPrice"] == 100.5

    def test_get_position_lifecycle(self):
        class _StubStorage:
            def query_position_events(self, position_id=None, symbol=None):
                assert position_id == "P1"
                assert symbol is None
                return [
                    {
                        "id": 1,
                        "event_id": "evt-open-1",
                        "position_id": "P1",
                        "symbol": "NIFTY25000CE",
                        "event_type": "OPENED",
                        "event_time": "2026-01-01T09:15:00Z",
                        "created_at": "2026-01-01T09:15:01Z",
                        "side": "LONG",
                        "entry_price": 100.5,
                        "source": "LLM",
                    },
                    {
                        "id": 2,
                        "event_id": "evt-partial-1",
                        "position_id": "P1",
                        "symbol": "NIFTY25000CE",
                        "event_type": "PARTIAL_EXIT",
                        "event_time": "2026-01-01T09:30:00Z",
                        "created_at": "2026-01-01T09:30:01Z",
                        "partial_pct": 0.5,
                    },
                    {
                        "id": 3,
                        "event_id": "evt-close-1",
                        "position_id": "P1",
                        "symbol": "NIFTY25000CE",
                        "event_type": "CLOSED",
                        "event_time": "2026-01-01T09:45:00Z",
                        "created_at": "2026-01-01T09:45:01Z",
                        "exit_price": 104.0,
                        "pnl": 87.5,
                    },
                ]

        app.dependency_overrides[get_storage] = lambda: _StubStorage()
        try:
            r = client.get("/api/trading/positions/P1/lifecycle")
        finally:
            app.dependency_overrides.pop(get_storage, None)

        assert r.status_code == 200
        body = r.json()
        assert body["positionId"] == "P1"
        assert body["status"] == "CLOSED"
        assert body["partialExitCount"] == 1
        assert body["events"][0]["eventId"] == "evt-open-1"
        assert body["eventTypes"] == ["OPENED", "PARTIAL_EXIT", "CLOSED"]


class TestAnalysisEndpoints:
    def _make_candles(self, n=30):
        return [
            {
                "time": f"2026-01-{i+1:02d}T00:00:00Z",
                "open": 100 + i, "high": 102 + i,
                "low": 98 + i, "close": 101 + i,
                "volume": 1000 + i * 10, "vwap": 100.5 + i,
                "takerBuyVolume": 600, "delta": 200,
            }
            for i in range(n)
        ]

    def test_amt_analysis(self):
        r = client.post(
            "/api/analysis/amt",
            json={"data": self._make_candles()},
        )
        assert r.status_code == 200
        body = r.json()
        assert "marketState" in body
        assert "poc" in body
        assert "valueAreaHigh" in body

    def test_prediction(self):
        r = client.post(
            "/api/analysis/predict",
            json={"data": self._make_candles(), "count": 5},
        )
        assert r.status_code == 200
        body = r.json()
        assert "predictions" in body
        assert "analysis" in body

    def test_footprint(self):
        r = client.post(
            "/api/analysis/footprint",
            json={"data": self._make_candles(5)},
        )
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)

    def test_amt_insufficient_data(self):
        r = client.post(
            "/api/analysis/amt",
            json={"data": self._make_candles(2)},
        )
        # Should still return 200 with default/empty analysis
        assert r.status_code == 200


class TestAIJournalEndpoints:
    def test_journal_promotion_endpoint(self, monkeypatch):
        from app.application.services.trade_journal import TradeJournal

        def _stub_assess(self, **kwargs):
            assert kwargs["start_date"] == "2026-01-01"
            assert kwargs["end_date"] == "2026-01-05"
            assert kwargs["run_ids"] == ["run-a", "run-b"]
            assert kwargs["min_trades"] == 12
            assert kwargs["min_expectancy"] == 0.25
            assert kwargs["min_profit_factor"] == 1.3
            assert kwargs["max_drawdown"] == 8.0
            assert kwargs["min_trading_days"] == 4
            assert kwargs["max_symbol_concentration_pct"] == 65.0
            assert kwargs["require_multi_session"] is True
            assert kwargs["min_thesis_completion_rate"] == 99.0
            assert kwargs["min_playbook_purity_rate"] == 97.0
            assert kwargs["max_playbook_session_misuse_rate"] == 0.0
            assert kwargs["min_feature_driver_coverage_rate"] == 95.0
            assert kwargs["min_aggression_driver_rate"] == 80.0
            return {
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
                "thresholds": {"min_trades": 12},
                "recommended_run_id": "run-a",
                "eligible_run_ids": ["run-a"],
                "assessments": [{"run_id": "run-a", "eligible": True}],
            }

        monkeypatch.setattr(TradeJournal, "assess_promotion", _stub_assess)

        r = client.get(
            "/api/ai/journal/promotion",
            params={
                "start": "2026-01-01",
                "end": "2026-01-05",
                "runIds": "run-a,run-b",
                "minTrades": 12,
                "minExpectancy": 0.25,
                "minProfitFactor": 1.3,
                "maxDrawdown": 8.0,
                "minTradingDays": 4,
                "maxSymbolConcentrationPct": 65.0,
                "requireMultiSession": True,
                "minThesisCompletionRate": 99.0,
                "minPlaybookPurityRate": 97.0,
                "maxPlaybookSessionMisuseRate": 0.0,
                "minFeatureDriverCoverageRate": 95.0,
                "minAggressionDriverRate": 80.0,
            },
        )

        assert r.status_code == 200
        body = r.json()
        assert body["recommended_run_id"] == "run-a"
        assert body["assessments"][0]["run_id"] == "run-a"
        assert body["assessments"][0]["eligible"] is True
