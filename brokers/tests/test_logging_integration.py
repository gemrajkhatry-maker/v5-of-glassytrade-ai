"""
Integration tests for structured logging, correlation IDs, and execution tracing.
"""

import asyncio
import json
import logging
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from brokers.broker.logging import (
    get_logger,
    setup_logging,
    correlation_context,
    get_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    ExecutionTracer,
    JSONFormatter,
)
from brokers.gateway import BrokerGateway
from brokers.broker.types import Exchange


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _clean_correlation():
    """Ensure correlation ID is cleared before and after each test."""
    clear_correlation_id()
    yield
    clear_correlation_id()


@pytest.fixture
def json_log_capture():
    """Capture log output in JSON format and return parsed records."""
    handler = logging.StreamHandler(StringIO())
    handler.setFormatter(JSONFormatter())

    brokers_logger = logging.getLogger("brokers")
    old_level = brokers_logger.level
    old_handlers = brokers_logger.handlers[:]

    brokers_logger.setLevel(logging.DEBUG)
    brokers_logger.addHandler(handler)

    class LogCapture:
        def get_records(self):
            handler.flush()
            output = handler.stream.getvalue()
            records = []
            for line in output.strip().split("\n"):
                if line:
                    records.append(json.loads(line))
            return records

    yield LogCapture()

    brokers_logger.handlers = old_handlers
    brokers_logger.setLevel(old_level)


# =============================================================================
# Correlation ID Tests
# =============================================================================


class TestCorrelationIdInGateway:
    def test_correlation_id_set_during_get_quote(self, json_log_capture):
        """Gateway methods should set a correlation ID for the duration of the call."""
        gw = BrokerGateway.paper()
        with gw:
            gw.get_quote("NIFTY", Exchange.NSE)

        records = json_log_capture.get_records()
        # At least one log record should have a correlation_id in extras
        cid_records = [r for r in records if r.get("cid")]
        assert len(cid_records) > 0, "Expected at least one log record with correlation ID"

    def test_correlation_id_cleared_after_call(self):
        """Correlation ID should be None after gateway call completes."""
        gw = BrokerGateway.paper()
        with gw:
            gw.get_quote("NIFTY", Exchange.NSE)

        assert get_correlation_id() is None

    def test_correlation_id_unique_per_call(self, json_log_capture):
        """Each gateway call should get a unique correlation ID."""
        gw = BrokerGateway.paper()
        with gw:
            gw.get_quote("NIFTY", Exchange.NSE)
            gw.get_quote("TCS", Exchange.NSE)

        records = json_log_capture.get_records()
        cids = [r["cid"] for r in records if r.get("cid")]
        unique_cids = set(cids)
        # Should have at least 2 distinct correlation IDs
        assert len(unique_cids) >= 2, f"Expected ≥2 unique CIDs, got {unique_cids}"

    def test_correlation_context_preserves_outer(self):
        """Nested correlation contexts should restore the outer ID."""
        set_correlation_id("outer-123")
        with correlation_context("inner-456") as inner_cid:
            assert inner_cid == "inner-456"
            assert get_correlation_id() == "inner-456"
        assert get_correlation_id() == "outer-123"


# =============================================================================
# Structured Logging Tests
# =============================================================================


class TestStructuredLogging:
    def test_setup_logging_json(self):
        """setup_logging('json') should configure JSONFormatter on root."""
        setup_logging(level=logging.DEBUG, format_type="json")
        root = logging.getLogger()
        assert any(
            isinstance(h.formatter, JSONFormatter) for h in root.handlers
        ), "Expected at least one handler with JSONFormatter"

    def test_get_logger_namespace(self):
        """get_logger should prefix with 'brokers.'"""
        logger = get_logger("test_module")
        assert logger.name == "brokers.test_module"

    def test_json_formatter_includes_correlation_id(self, json_log_capture):
        """JSON formatted logs should include correlation_id when set."""
        logger = get_logger("test_json")
        with correlation_context("json-test-123"):
            logger.info("test message")

        records = json_log_capture.get_records()
        assert len(records) >= 1
        # The JSONFormatter reads correlation_id from contextvars
        has_cid = any(r.get("correlation_id") == "json-test-123" for r in records)
        assert has_cid, f"Expected correlation_id in records: {records}"


# =============================================================================
# ExecutionTracer Tests
# =============================================================================


class TestExecutionTracer:
    def test_sync_trace(self, json_log_capture):
        """Sync function tracing should log ENTER and EXIT."""
        logger = get_logger("test_tracer")
        tracer = ExecutionTracer(logger)

        @tracer.trace("TestService.sync_op")
        def my_func(x):
            return x * 2

        result = my_func(5)
        assert result == 10

        records = json_log_capture.get_records()
        messages = [r["message"] for r in records]
        assert any("ENTER TestService.sync_op" in m for m in messages)
        assert any("EXIT TestService.sync_op - SUCCESS" in m for m in messages)

    def test_async_trace(self, json_log_capture):
        """Async function tracing should log ENTER and EXIT."""
        logger = get_logger("test_tracer")
        tracer = ExecutionTracer(logger)

        @tracer.trace("TestService.async_op")
        async def my_async_func(x):
            await asyncio.sleep(0)
            return x * 3

        result = asyncio.run(my_async_func(4))
        assert result == 12

        records = json_log_capture.get_records()
        messages = [r["message"] for r in records]
        assert any("ENTER TestService.async_op" in m for m in messages)
        assert any("EXIT TestService.async_op - SUCCESS" in m for m in messages)

    def test_async_trace_error(self, json_log_capture):
        """Async trace should log ERROR on exception."""
        logger = get_logger("test_tracer")
        tracer = ExecutionTracer(logger)

        @tracer.trace("TestService.failing_op")
        async def failing_func():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            asyncio.run(failing_func())

        records = json_log_capture.get_records()
        messages = [r["message"] for r in records]
        assert any("EXIT TestService.failing_op - ERROR" in m for m in messages)

    def test_trace_preserves_function_name(self):
        """@tracer.trace should preserve __name__ via functools.wraps."""
        logger = get_logger("test_tracer")
        tracer = ExecutionTracer(logger)

        @tracer.trace("my_context")
        def named_function():
            pass

        assert named_function.__name__ == "named_function"

        @tracer.trace("my_async_context")
        async def named_async():
            pass

        assert named_async.__name__ == "named_async"


# =============================================================================
# Bare Except Audit
# =============================================================================


class TestNoBareExcepts:
    def test_no_bare_except_in_production_code(self):
        """Production code should not have bare 'except:' blocks."""
        brokers_root = Path(__file__).parent.parent
        bare_except_pattern = re.compile(r"^\s*except\s*:\s*(pass|$)", re.MULTILINE)

        violations = []
        for py_file in brokers_root.rglob("*.py"):
            # Skip test files
            if "/tests/" in str(py_file):
                continue
            content = py_file.read_text()
            matches = bare_except_pattern.findall(content)
            if matches:
                violations.append(str(py_file.relative_to(brokers_root)))

        assert violations == [], f"Found bare except blocks in: {violations}"
