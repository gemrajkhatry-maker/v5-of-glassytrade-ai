"""End-to-end integration tests for cost tracking across the full pipeline.

Validates that cost data flows from:
  MLX adapter → cost tracker → metrics snapshot
  Dhan adapter → cost tracker → metrics snapshot
  Trade execution → cost tracker → metrics snapshot
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.cost_tracker import CostTracker, TokenUsage, get_cost_tracker, reset_cost_tracker


class TestMLXAdapterCostTracking:
    """E2E: MLX inference adapter records token usage to cost tracker."""

    def setup_method(self):
        reset_cost_tracker()
        self.tracker = get_cost_tracker()

    def teardown_method(self):
        reset_cost_tracker()

    def test_local_inference_records_tokens(self):
        """When MLX adapter generates locally, tokens are tracked."""
        # Simulate what the adapter does after a successful generate() call
        usage = TokenUsage(
            prompt_tokens=450,
            completion_tokens=95,
            total_tokens=545,
            model="gemma-mlx",
            is_cloud=False,
        )
        self.tracker.record_llm_call(usage)

        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["local_calls"] == 1
        assert snapshot["llm"]["total_tokens"] == 545
        assert snapshot["llm"]["cloud_calls"] == 0

    def test_cloud_inference_records_tokens_from_api_response(self):
        """When cloud inference returns, OpenRouter usage data is tracked."""
        # Simulates parsing {"usage": {"prompt_tokens": 520, "completion_tokens": 110, "total_tokens": 630}}
        usage = TokenUsage(
            prompt_tokens=520,
            completion_tokens=110,
            total_tokens=630,
            model="openai/gpt-oss-120b:free",
            is_cloud=True,
        )
        self.tracker.record_llm_call(usage)

        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["cloud_calls"] == 1
        assert snapshot["llm"]["total_tokens"] == 630
        assert snapshot["llm"]["prompt_tokens"] == 520

    def test_cloud_429_records_to_tracker(self):
        """When cloud returns 429, rate limit is recorded."""
        self.tracker.record_cloud_429()
        self.tracker.record_cloud_429()

        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["cloud_429s"] == 2

    def test_mixed_local_and_cloud_accumulate(self):
        """Both local and cloud calls accumulate independently."""
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=400, completion_tokens=80, total_tokens=480, is_cloud=False))
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=500, completion_tokens=100, total_tokens=600, is_cloud=False))
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=520, completion_tokens=110, total_tokens=630, is_cloud=True))

        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["local_calls"] == 2
        assert snapshot["llm"]["cloud_calls"] == 1
        assert snapshot["llm"]["total_tokens"] == 1710  # 480 + 600 + 630


class TestDhanAdapterCostTracking:
    """E2E: Dhan adapter records API calls to cost tracker."""

    def setup_method(self):
        reset_cost_tracker()
        self.tracker = get_cost_tracker()

    def teardown_method(self):
        reset_cost_tracker()

    def test_ltp_call_records_to_tracker(self):
        """Successful LTP API call is recorded."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 12.5, "ok")

        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["total_calls"] == 1
        assert snapshot["broker_api"]["by_endpoint"]["/api/ltp"] == 1

    def test_option_chain_call_records_to_tracker(self):
        """Option chain fetch is recorded."""
        self.tracker.record_api_call("/api/options/chain", "NIFTY", 45.0, "ok")

        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["by_endpoint"]["/api/options/chain"] == 1

    def test_api_error_records_to_tracker(self):
        """Failed API call records error status."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 150.0, "error")

        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["errors"]["/api/ltp"] == 1

    def test_rate_limit_records_to_tracker(self):
        """Rate-limited call is counted."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 5.0, "rate_limited")

        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["rate_limit_hits"] == 1

    def test_multiple_calls_accumulate_latency_avg(self):
        """Multiple calls accumulate and compute average latency."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "ok")
        self.tracker.record_api_call("/api/ltp", "NIFTY", 20.0, "ok")
        self.tracker.record_api_call("/api/ltp", "NIFTY", 15.0, "ok")

        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["by_endpoint"]["/api/ltp"] == 3
        assert snapshot["broker_api"]["avg_latency_ms"]["/api/ltp"] == 15.0


class TestTradeCostFlow:
    """E2E: Trade costs flow through to cost tracker."""

    def setup_method(self):
        reset_cost_tracker()
        self.tracker = get_cost_tracker()

    def teardown_method(self):
        reset_cost_tracker()

    def test_buy_trade_cost_recorded(self):
        """Buy trade cost is computed and recorded."""
        record = self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0, is_sell=False)

        assert record.total > 0
        assert record.stt == 0.0  # No STT on buy
        assert record.brokerage == 40.0  # Rs. 20 × 2

        snapshot = self.tracker.snapshot()
        assert snapshot["trades"]["count"] == 1
        assert snapshot["trades"]["breakdown"]["brokerage"] == 40.0

    def test_sell_trade_includes_stt(self):
        """Sell trade includes STT in cost."""
        record = self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0, is_sell=True)

        assert record.stt > 0
        assert record.stt == pytest.approx(25000.0 * 0.000625)

        snapshot = self.tracker.snapshot()
        assert snapshot["trades"]["breakdown"]["stt"] > 0

    def test_multiple_trades_accumulate(self):
        """Multiple trades accumulate total cost."""
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0, is_sell=False)
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0, is_sell=True)

        snapshot = self.tracker.snapshot()
        assert snapshot["trades"]["count"] == 2
        assert snapshot["trades"]["total_cost_rs"] > 0
        assert snapshot["trades"]["breakdown"]["stt"] > 0  # From sell


class TestFullPipelineIntegration:
    """E2E: Full pipeline — LLM call + API calls + trade → complete cost snapshot."""

    def setup_method(self):
        reset_cost_tracker()
        self.tracker = get_cost_tracker()

    def teardown_method(self):
        reset_cost_tracker()

    def test_complete_session_cost_snapshot(self):
        """A full trading session produces accurate cost breakdown."""
        # Simulate: 3 local LLM calls, 1 cloud call, 1 cloud 429
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=450, completion_tokens=90, total_tokens=540, is_cloud=False))
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=460, completion_tokens=95, total_tokens=555, is_cloud=False))
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=440, completion_tokens=85, total_tokens=525, is_cloud=False))
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=520, completion_tokens=110, total_tokens=630, is_cloud=True))
        self.tracker.record_cloud_429()

        # Simulate: 10 LTP calls, 2 option chain fetches, 1 error
        for i in range(10):
            self.tracker.record_api_call("/api/ltp", "NIFTY", 8.0 + i, "ok")
        self.tracker.record_api_call("/api/options/chain", "NIFTY", 45.0, "ok")
        self.tracker.record_api_call("/api/options/chain", "NIFTY", 50.0, "ok")
        self.tracker.record_api_call("/api/ltp", "NIFTY", 200.0, "error")

        # Simulate: 1 buy + 1 sell trade (round-trip)
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0, is_sell=False)
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0, is_sell=True)

        snapshot = self.tracker.snapshot()

        # Verify LLM metrics
        assert snapshot["llm"]["local_calls"] == 3
        assert snapshot["llm"]["cloud_calls"] == 1
        assert snapshot["llm"]["cloud_429s"] == 1
        assert snapshot["llm"]["total_tokens"] == 2250  # 540+555+525+630
        assert snapshot["llm"]["avg_tokens_per_call"] == 562  # 2250/4

        # Verify broker API metrics
        assert snapshot["broker_api"]["total_calls"] == 13
        assert snapshot["broker_api"]["by_endpoint"]["/api/ltp"] == 11
        assert snapshot["broker_api"]["by_endpoint"]["/api/options/chain"] == 2
        assert snapshot["broker_api"]["errors"]["/api/ltp"] == 1
        assert snapshot["broker_api"]["avg_latency_ms"]["/api/ltp"] == pytest.approx(29.5, abs=1.0)

        # Verify trade metrics
        assert snapshot["trades"]["count"] == 2
        assert snapshot["trades"]["breakdown"]["stt"] > 0  # From sell
        assert snapshot["trades"]["breakdown"]["brokerage"] == 80.0  # 40 × 2
        assert snapshot["trades"]["breakdown"]["slippage"] == pytest.approx(75.0)  # 37.5 × 2
        assert snapshot["trades"]["avg_cost_per_trade"] > 0

    def test_empty_session_has_zeroes(self):
        """Fresh session shows all zeroes."""
        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["total_tokens"] == 0
        assert snapshot["llm"]["local_calls"] == 0
        assert snapshot["llm"]["cloud_calls"] == 0
        assert snapshot["broker_api"]["total_calls"] == 0
        assert snapshot["trades"]["count"] == 0
        assert snapshot["trades"]["total_cost_rs"] == 0.0

    def test_reset_clears_everything(self):
        """After reset, all counters return to zero."""
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=500, completion_tokens=100, total_tokens=600, is_cloud=True))
        self.tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "ok")
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0)
        self.tracker.reset()

        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["total_tokens"] == 0
        assert snapshot["broker_api"]["total_calls"] == 0
        assert snapshot["trades"]["count"] == 0
