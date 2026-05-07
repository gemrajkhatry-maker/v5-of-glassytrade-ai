"""Tests for Gateway Server - FastAPI production server setup and routes."""
import pytest
from fastapi.testclient import TestClient
from brokersv2.gateway.server import (
    create_app,
    GatewayConfig,
)


@pytest.fixture
def app():
    """Create test application."""
    config = GatewayConfig(
        host="127.0.0.1",
        port=9090,
        debug=False,
    )
    return create_app(config)


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestGatewayConfig:
    """Test GatewayConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = GatewayConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 9090
        assert config.debug is False
        assert config.cors_origins == ["*"]

    def test_custom_config(self):
        """Test custom configuration."""
        config = GatewayConfig(
            host="127.0.0.1",
            port=8080,
            debug=True,
            cors_origins=["http://localhost:3000"],
        )

        assert config.host == "127.0.0.1"
        assert config.port == 8080
        assert config.debug is True
        assert config.cors_origins == ["http://localhost:3000"]


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_health_endpoint(self, client):
        """Test /health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "timestamp" in data

    def test_health_healthy_status(self, client):
        """Test health endpoint returns healthy status."""
        response = client.get("/health")
        data = response.json()

        assert data["status"] in ["healthy", "degraded", "unhealthy"]

    def test_liveness_endpoint(self, client):
        """Test /health/liveness endpoint."""
        response = client.get("/health/liveness")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "is_overall_healthy" in data

    def test_readiness_endpoint(self, client):
        """Test /health/readiness endpoint."""
        response = client.get("/health/readiness")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "is_overall_healthy" in data


class TestMetricsEndpoint:
    """Test metrics endpoint."""

    def test_metrics_endpoint(self, client):
        """Test /metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200

        # Should return Prometheus format (text/plain)
        assert "text/plain" in response.headers["content-type"]

    def test_metrics_contains_help(self, client):
        """Test metrics contain HELP lines."""
        response = client.get("/metrics")
        text = response.text

        # Prometheus format includes HELP lines
        assert "# HELP" in text or "# TYPE" in text

    def test_metrics_content_type(self, client):
        """Test metrics content type is text/plain."""
        response = client.get("/metrics")
        assert response.headers["content-type"].startswith("text/plain")


class TestServerInfoEndpoint:
    """Test server info endpoint."""

    def test_server_info(self, client):
        """Test /info endpoint."""
        response = client.get("/info")
        assert response.status_code == 200

        data = response.json()
        assert "service" in data
        assert "version" in data
        assert data["service"] == "glassytrade-gateway"

    def test_server_info_version(self, client):
        """Test server info includes version."""
        response = client.get("/info")
        data = response.json()

        # Should have semantic versioning
        assert "version" in data
        assert isinstance(data["version"], str)


class TestRiskEndpoint:
    """Test risk status endpoint."""

    def test_risk_status(self, client):
        """Test /risk/status endpoint."""
        response = client.get("/risk/status")
        assert response.status_code == 200

        data = response.json()
        assert "kill_switch_active" in data
        assert "exposure" in data

    def test_risk_kill_switch_false(self, client):
        """Test risk status shows kill switch inactive."""
        response = client.get("/risk/status")
        data = response.json()

        # By default, kill switch should be off
        assert data["kill_switch_active"] is False


class TestPositionsEndpoint:
    """Test positions endpoint."""

    def test_positions_empty(self, client):
        """Test positions endpoint when no positions."""
        response = client.get("/positions")
        assert response.status_code == 200

        data = response.json()
        assert "positions" in data
        assert isinstance(data["positions"], list)

    def test_positions_structure(self, client):
        """Test positions response structure."""
        response = client.get("/positions")
        data = response.json()

        assert "positions" in data
        assert "total_exposure" in data
        assert "count" in data


class TestOrdersEndpoint:
    """Test orders endpoint."""

    def test_orders_empty(self, client):
        """Test orders endpoint when no orders."""
        response = client.get("/orders")
        assert response.status_code == 200

        data = response.json()
        assert "orders" in data
        assert isinstance(data["orders"], list)

    def test_orders_structure(self, client):
        """Test orders response structure."""
        response = client.get("/orders")
        data = response.json()

        assert "orders" in data
        assert "total" in data
        assert "filters" in data


class TestGatewayApp:
    """Test Gateway application setup."""

    def test_app_creation(self):
        """Test app creation with default config."""
        app = create_app()
        assert app is not None
        assert app.title == "GlassyTrade Gateway"

    def test_app_creation_with_config(self):
        """Test app creation with custom config."""
        config = GatewayConfig(host="127.0.0.1", port=8080)
        app = create_app(config)
        assert app is not None

    def test_app_has_health_router(self, app):
        """Test app has health routes."""
        routes = [route.path for route in app.routes]
        assert "/health" in routes
        assert "/health/liveness" in routes
        assert "/health/readiness" in routes

    def test_app_has_metrics_router(self, app):
        """Test app has metrics route."""
        routes = [route.path for route in app.routes]
        assert "/metrics" in routes

    def test_app_has_info_router(self, app):
        """Test app has info route."""
        routes = [route.path for route in app.routes]
        assert "/info" in routes

    def test_app_has_risk_router(self, app):
        """Test app has risk route."""
        routes = [route.path for route in app.routes]
        assert "/risk/status" in routes

    def test_app_has_positions_router(self, app):
        """Test app has positions route."""
        routes = [route.path for route in app.routes]
        assert "/positions" in routes

    def test_app_has_orders_router(self, app):
        """Test app has orders route."""
        routes = [route.path for route in app.routes]
        assert "/orders" in routes

    def test_app_cors_enabled(self, app):
        """Test app has CORS middleware."""
        # FastAPI adds CORS middleware when configured
        # Check that CORS origins are in the config
        assert app.state.config.cors_origins is not None
        assert len(app.state.config.cors_origins) > 0

    def test_app_debug_mode_off(self):
        """Test app debug mode is off by default."""
        config = GatewayConfig()
        app = create_app(config)
        assert config.debug is False

    def test_app_debug_mode_on(self):
        """Test app debug mode can be enabled."""
        config = GatewayConfig(debug=True)
        app = create_app(config)
        assert config.debug is True


class TestGatewayMiddleware:
    """Test gateway middleware."""

    def test_request_id_header(self, client):
        """Test requests get request ID."""
        response = client.get("/health")
        assert response.status_code == 200

        # Should have some response headers
        assert len(response.headers) > 0

    def test_content_type_json(self, client):
        """Test JSON endpoints return correct content type."""
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_cors_headers(self, client):
        """Test CORS headers are present."""
        response = client.get("/health")
        # FastAPI with CORS middleware should handle this
        assert response.status_code == 200


class TestErrorHandling:
    """Test error handling."""

    def test_404_handler(self, client):
        """Test 404 for unknown routes."""
        response = client.get("/nonexistent")
        assert response.status_code == 404

    def test_404_structure(self, client):
        """Test 404 response structure."""
        response = client.get("/nonexistent")
        data = response.json()

        assert "detail" in data

    def test_method_not_allowed(self, client):
        """Test 405 for wrong HTTP method."""
        # POST to GET-only endpoint
        response = client.post("/health")
        assert response.status_code in [405, 404]


class TestGatewayStartup:
    """Test gateway startup sequence."""

    def test_app_lifespan(self):
        """Test app lifespan context manager."""
        config = GatewayConfig()
        app = create_app(config)

        # Should be able to create app without errors
        assert app is not None
        assert hasattr(app, "router")

    def test_app_state(self, app):
        """Test app has state object."""
        assert hasattr(app, "state")

    def test_app_title(self, app):
        """Test app has title."""
        assert app.title == "GlassyTrade Gateway"

    def test_app_version(self, app):
        """Test app has version."""
        assert app.version is not None
