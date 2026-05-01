"""Tests for LLM worker module."""

import pytest
from app.application.handlers.llm_worker import LLMWorkerManager, check_staleness


class TestLLMWorkerManager:
    """Tests for LLM worker queue management."""

    def test_init(self):
        """Test worker manager initialization."""
        mgr = LLMWorkerManager()
        assert mgr._llm_queues == {}
        assert mgr._worker_threads == {}

    def test_is_queue_full_empty(self):
        """Test queue full check on empty queue."""
        mgr = LLMWorkerManager()
        assert not mgr.is_queue_full("TEST")

    def test_shutdown_all(self):
        """Test shutdown clears queues."""
        mgr = LLMWorkerManager()
        # Should not raise even with empty queues
        mgr.shutdown_all()


class TestCheckStaleness:
    """Tests for staleness checking."""

    def test_fresh_request(self):
        """Test fresh request is not stale."""
        import time
        enqueue_time = time.time() - 5.0
        assert not check_staleness(enqueue_time, threshold=20.0)

    def test_stale_request(self):
        """Test old request is stale."""
        import time
        enqueue_time = time.time() - 30.0
        assert check_staleness(enqueue_time, threshold=20.0)

    def test_boundary(self):
        """Test boundary condition."""
        import time
        enqueue_time = time.time() - 20.0
        assert check_staleness(enqueue_time, threshold=20.0)
        enqueue_time = time.time() - 19.0
        assert not check_staleness(enqueue_time, threshold=20.0)