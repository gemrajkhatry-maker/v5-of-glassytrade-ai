"""
Dhan Broker Tests - Comprehensive test suite for Dhan broker implementation.

This package contains tests for all layers of the Dhan broker:
    - test_domain.py: Domain layer tests (entities, value objects, errors, constants)
    - test_infrastructure.py: Infrastructure layer tests (HTTP, WebSocket, mappers)
    - test_application.py: Application layer tests (config, converters, broker)
    - test_integration.py: Integration tests with mock server responses

Run tests with:
    pytest brokers/broker/dhan/tests/ -v

Run with coverage:
    pytest brokers/broker/dhan/tests/ --cov=brokers.broker.dhan --cov-report=html
"""
