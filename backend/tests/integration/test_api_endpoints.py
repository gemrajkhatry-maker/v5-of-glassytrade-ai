"""Integration tests for FastAPI REST endpoints via TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


class TestHealthEndpoint:
    def test_health_ok(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "service" in body


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
