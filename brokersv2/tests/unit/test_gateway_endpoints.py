"""Tests for Gateway historical data and market data endpoints."""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient

from brokersv2.gateway.server import create_app, GatewayConfig


@pytest.fixture
def app():
    """Create test application."""
    config = GatewayConfig(debug=False)
    return create_app(config)


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestHistoricalDataEndpoint:
    """Test historical data endpoints."""

    def test_post_historical_endpoint_exists(self, client):
        """Test /historical endpoint exists."""
        response = client.post(
            "/historical",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "from_date": "2024-01-01",
                "to_date": "2024-01-31",
                "interval": "1d",
            }
        )
        # Should not be 404
        assert response.status_code != 404

    def test_get_candles_endpoint_exists(self, client):
        """Test /candles/{symbol} endpoint exists."""
        response = client.get("/candles/NSE:RELIANCE")
        # Should not be 404
        assert response.status_code != 404


class TestMarketDataEndpoints:
    """Test market data endpoints."""

    def test_get_quote_endpoint(self, client):
        """Test /quote/{symbol} endpoint."""
        response = client.get("/quote/NSE:RELIANCE")
        assert response.status_code != 404

    def test_get_quotes_batch_endpoint(self, client):
        """Test /quotes/batch endpoint."""
        response = client.post(
            "/quotes/batch",
            json={
                "symbols": ["NSE:RELIANCE", "NSE:TCS"]
            }
        )
        assert response.status_code != 404


class TestOrderEndpoints:
    """Test order management endpoints."""

    def test_place_order_endpoint(self, client):
        """Test POST /orders endpoint."""
        response = client.post(
            "/orders",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "quantity": 1,
                "side": "BUY",
                "order_type": "MARKET",
            }
        )
        assert response.status_code != 404

    def test_get_order_status_endpoint(self, client):
        """Test GET /orders/{order_id} endpoint."""
        response = client.get("/orders/ORD001")
        assert response.status_code != 404

    def test_cancel_order_endpoint(self, client):
        """Test DELETE /orders/{order_id} endpoint."""
        response = client.delete("/orders/ORD001")
        assert response.status_code != 404


class TestOptionsEndpoints:
    """Test options chain endpoints."""

    def test_get_option_chain_endpoint(self, client):
        """Test /options/chain/{underlying} endpoint."""
        response = client.get("/options/chain/NIFTY?exchange=NSE")
        assert response.status_code != 404

    def test_get_expiry_list_endpoint(self, client):
        """Test /options/expiries/{underlying} endpoint."""
        response = client.get("/options/expiries/NIFTY?exchange=NSE")
        assert response.status_code != 404


class TestStreamingEndpoints:
    """Test WebSocket streaming endpoints."""

    def test_stream_ticks_endpoint_exists(self, app):
        """Test /ws/ticks WebSocket endpoint exists."""
        routes = [route.path for route in app.routes]
        assert "/ws/ticks" in routes

    def test_stream_quotes_endpoint_exists(self, app):
        """Test /ws/quotes WebSocket endpoint exists."""
        routes = [route.path for route in app.routes]
        assert "/ws/quotes" in routes

    def test_stream_depth_endpoint_exists(self, app):
        """Test /ws/depth WebSocket endpoint exists."""
        routes = [route.path for route in app.routes]
        assert "/ws/depth" in routes


class TestBrokerConnectionEndpoint:
    """Test broker connection management."""

    def test_connection_status_endpoint(self, client):
        """Test /broker/status endpoint."""
        response = client.get("/broker/status")
        assert response.status_code == 200

        data = response.json()
        assert "connected" in data
        assert "broker_type" in data

    def test_connection_health_endpoint(self, client):
        """Test /broker/health endpoint."""
        response = client.get("/broker/health")
        assert response.status_code == 200


class TestGatewayCompleteness:
    """Test gateway exposes all broker methods."""

    def test_all_market_data_routes_exist(self, app):
        """Test all market data routes are registered."""
        routes = {route.path for route in app.routes}

        # Market data endpoints
        assert "/quote/{symbol}" in routes
        assert "/quotes/batch" in routes
        assert "/historical" in routes
        assert "/candles/{symbol}" in routes

    def test_all_order_routes_exist(self, app):
        """Test all order routes are registered."""
        routes = {route.path for route in app.routes}

        # Order endpoints
        assert "/orders" in routes
        assert "/orders/{order_id}" in routes

    def test_all_options_routes_exist(self, app):
        """Test all options routes are registered."""
        routes = {route.path for route in app.routes}

        # Options endpoints
        assert "/options/chain/{underlying}" in routes
        assert "/options/expiries/{underlying}" in routes

    def test_all_streaming_routes_exist(self, app):
        """Test all streaming routes are registered."""
        routes = {route.path for route in app.routes}

        # WebSocket endpoints
        assert "/ws/ticks" in routes
        assert "/ws/quotes" in routes
        assert "/ws/depth" in routes

    def test_broker_management_routes_exist(self, app):
        """Test broker management routes are registered."""
        routes = {route.path for route in app.routes}

        # Broker management
        assert "/broker/status" in routes
        assert "/broker/health" in routes
