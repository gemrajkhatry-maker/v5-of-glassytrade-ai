"""Integration tests for lot-size API endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.dependencies import get_market_data

client = TestClient(app)

class MockMarketData:
    def get_lot_size(self, symbol: str) -> int:
        sym = symbol.upper()
        if "BANKNIFTY" in sym:
            return 15
        if "NIFTY" in sym:
            return 25
        if "CRUDEOIL" in sym:
            return 100
        return 1

@pytest.fixture
def mock_market_data():
    md = MockMarketData()
    app.dependency_overrides[get_market_data] = lambda: md
    yield md
    app.dependency_overrides.pop(get_market_data, None)

def test_get_lot_size_nifty(mock_market_data):
    response = client.get("/api/market/lot-size/NIFTY24JAN25000CE")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "NIFTY24JAN25000CE"
    assert data["lotSize"] == 25

def test_get_lot_size_banknifty(mock_market_data):
    response = client.get("/api/market/lot-size/BANKNIFTY24JAN48000PE")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "BANKNIFTY24JAN48000PE"
    assert data["lotSize"] == 15

def test_get_lot_size_default(mock_market_data):
    response = client.get("/api/market/lot-size/RELIANCE")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE"
    assert data["lotSize"] == 1
