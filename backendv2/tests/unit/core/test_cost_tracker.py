"""Tests for cost_tracker.py — spending visibility."""
from __future__ import annotations

import pytest

from app.core.cost_tracker import (
    APICallRecord,
    CostTracker,
    TokenUsage,
    TradeCostRecord,
    get_cost_tracker,
    reset_cost_tracker,
)


class TestTokenUsage:
    """Tests for TokenUsage dataclass."""

    def test_default_values(self):
        """TokenUsage has sensible defaults."""
        usage = TokenUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0
        assert usage.model == ""
        assert usage.is_cloud is False

    def test_populated_values(self):
        """TokenUsage stores provided values."""
        usage = TokenUsage(
            prompt_tokens=500,
            completion_tokens=120,
            total_tokens=620,
            model="gpt-oss-120b:free",
            is_cloud=True,
        )
        assert usage.prompt_tokens == 500
        assert usage.completion_tokens == 120
        assert usage.total_tokens == 620
        assert usage.is_cloud is True


class TestCostTrackerLLM:
    """Tests for LLM token tracking."""

    def setup_method(self):
        self.tracker = CostTracker()

    def test_record_local_call(self):
        """Local LLM call is tracked."""
        usage = TokenUsage(prompt_tokens=400, completion_tokens=80, total_tokens=480, model="mlx-local", is_cloud=False)
        self.tracker.record_llm_call(usage)
        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["local_calls"] == 1
        assert snapshot["llm"]["cloud_calls"] == 0
        assert snapshot["llm"]["total_tokens"] == 480

    def test_record_cloud_call(self):
        """Cloud LLM call is tracked separately."""
        usage = TokenUsage(prompt_tokens=500, completion_tokens=100, total_tokens=600, model="gpt-oss:free", is_cloud=True)
        self.tracker.record_llm_call(usage)
        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["cloud_calls"] == 1
        assert snapshot["llm"]["local_calls"] == 0
        assert snapshot["llm"]["total_tokens"] == 600

    def test_multiple_calls_accumulate(self):
        """Multiple calls accumulate token counts."""
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150, is_cloud=False))
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=200, completion_tokens=80, total_tokens=280, is_cloud=False))
        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["local_calls"] == 2
        assert snapshot["llm"]["total_tokens"] == 430
        assert snapshot["llm"]["prompt_tokens"] == 300
        assert snapshot["llm"]["completion_tokens"] == 130

    def test_avg_tokens_per_call(self):
        """Average tokens per call is computed."""
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150, is_cloud=False))
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300, is_cloud=False))
        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["avg_tokens_per_call"] == 225  # (150+300)/2

    def test_cloud_429_tracking(self):
        """Cloud 429 rate limits are counted."""
        self.tracker.record_cloud_429()
        self.tracker.record_cloud_429()
        self.tracker.record_cloud_429()
        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["cloud_429s"] == 3

    def test_token_history_truncated(self):
        """Token history is kept to last 100 entries."""
        for i in range(150):
            self.tracker.record_llm_call(TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150, is_cloud=False))
        assert len(self.tracker._token_history) == 100


class TestCostTrackerBrokerAPI:
    """Tests for broker API tracking."""

    def setup_method(self):
        self.tracker = CostTracker()

    def test_record_api_call(self):
        """API call is recorded by endpoint."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 15.0, "ok")
        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["total_calls"] == 1
        assert snapshot["broker_api"]["by_endpoint"]["/api/ltp"] == 1

    def test_multiple_endpoints_tracked(self):
        """Different endpoints are tracked separately."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "ok")
        self.tracker.record_api_call("/api/ltp", "BANKNIFTY", 12.0, "ok")
        self.tracker.record_api_call("/api/options/chain", "NIFTY", 50.0, "ok")
        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["by_endpoint"]["/api/ltp"] == 2
        assert snapshot["broker_api"]["by_endpoint"]["/api/options/chain"] == 1

    def test_errors_tracked(self):
        """API errors are counted."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "error")
        self.tracker.record_api_call("/api/ltp", "NIFTY", 12.0, "ok")
        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["errors"]["/api/ltp"] == 1

    def test_rate_limit_hits_tracked(self):
        """Rate limit hits are counted."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "rate_limited")
        self.tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "rate_limited")
        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["rate_limit_hits"] == 2

    def test_avg_latency_computed(self):
        """Average latency is computed per endpoint."""
        self.tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "ok")
        self.tracker.record_api_call("/api/ltp", "NIFTY", 20.0, "ok")
        snapshot = self.tracker.snapshot()
        assert snapshot["broker_api"]["avg_latency_ms"]["/api/ltp"] == 15.0

    def test_latency_history_truncated(self):
        """Latency history is kept to last 100 per endpoint."""
        for i in range(150):
            self.tracker.record_api_call("/api/ltp", "NIFTY", float(i), "ok")
        assert len(self.tracker._api_latencies["/api/ltp"]) == 100


class TestCostTrackerTrades:
    """Tests for trade cost tracking."""

    def setup_method(self):
        self.tracker = CostTracker()

    def test_record_trade_cost_buy(self):
        """Buy trade costs are computed correctly."""
        notional = 25000.0  # NIFTY 1000 * 25 qty
        record = self.tracker.record_trade_cost("NIFTY", notional, slippage_bps=15.0, is_sell=False)
        assert record.symbol == "NIFTY"
        assert record.notional == 25000.0
        assert record.brokerage == 40.0  # Rs. 20 * 2
        assert record.stt == 0.0  # No STT on buy
        assert record.gst == pytest.approx(7.2)  # 18% of 40

    def test_record_trade_cost_sell(self):
        """Sell trade includes STT."""
        notional = 25000.0
        record = self.tracker.record_trade_cost("NIFTY", notional, slippage_bps=15.0, is_sell=True)
        assert record.stt > 0  # STT applied
        assert record.stt == pytest.approx(25000.0 * 0.000625)

    def test_slippage_computed(self):
        """Slippage is computed from bps."""
        notional = 25000.0
        record = self.tracker.record_trade_cost("NIFTY", notional, slippage_bps=15.0)
        assert record.slippage == pytest.approx(25000.0 * 15.0 / 10000.0)

    def test_total_cost_accumulation(self):
        """Multiple trades accumulate total costs."""
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0)
        self.tracker.record_trade_cost("NIFTY", 30000.0, slippage_bps=20.0)
        snapshot = self.tracker.snapshot()
        assert snapshot["trades"]["count"] == 2
        assert snapshot["trades"]["total_cost_rs"] > 0

    def test_avg_cost_per_trade(self):
        """Average cost per trade is computed."""
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0)
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0)
        snapshot = self.tracker.snapshot()
        total = snapshot["trades"]["total_cost_rs"]
        avg = snapshot["trades"]["avg_cost_per_trade"]
        assert avg == pytest.approx(total / 2, abs=0.01)

    def test_cost_breakdown_in_snapshot(self):
        """Snapshot includes full cost breakdown."""
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0, is_sell=True)
        snapshot = self.tracker.snapshot()
        breakdown = snapshot["trades"]["breakdown"]
        assert "brokerage" in breakdown
        assert "stt" in breakdown
        assert "exchange_fee" in breakdown
        assert "gst" in breakdown
        assert "sebi" in breakdown
        assert "slippage" in breakdown

    def test_slippage_varies_by_bps(self):
        """Lower bps produces lower slippage for same notional."""
        low_slip = self.tracker.record_trade_cost("GOLD", 25000.0, slippage_bps=8.0)
        high_slip = self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0)
        assert low_slip.slippage < high_slip.slippage


class TestCostTrackerSnapshot:
    """Tests for snapshot() method."""

    def setup_method(self):
        self.tracker = CostTracker()

    def test_snapshot_has_all_sections(self):
        """Snapshot contains llm, broker_api, and trades sections."""
        snapshot = self.tracker.snapshot()
        assert "llm" in snapshot
        assert "broker_api" in snapshot
        assert "trades" in snapshot

    def test_empty_snapshot_has_zeroes(self):
        """Empty tracker returns zeroed metrics."""
        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["total_tokens"] == 0
        assert snapshot["broker_api"]["total_calls"] == 0
        assert snapshot["trades"]["count"] == 0
        assert snapshot["trades"]["total_cost_rs"] == 0.0

    def test_snapshot_with_data(self):
        """Snapshot reflects recorded data accurately."""
        self.tracker.record_llm_call(TokenUsage(prompt_tokens=500, completion_tokens=100, total_tokens=600, is_cloud=True))
        self.tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "ok")
        self.tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0)
        snapshot = self.tracker.snapshot()
        assert snapshot["llm"]["cloud_calls"] == 1
        assert snapshot["llm"]["total_tokens"] == 600
        assert snapshot["broker_api"]["total_calls"] == 1
        assert snapshot["trades"]["count"] == 1


class TestCostTrackerReset:
    """Tests for reset() method."""

    def test_reset_clears_all_counters(self):
        """Reset clears all recorded data."""
        tracker = CostTracker()
        tracker.record_llm_call(TokenUsage(prompt_tokens=500, completion_tokens=100, total_tokens=600, is_cloud=True))
        tracker.record_api_call("/api/ltp", "NIFTY", 10.0, "ok")
        tracker.record_trade_cost("NIFTY", 25000.0, slippage_bps=15.0)
        tracker.reset()
        snapshot = tracker.snapshot()
        assert snapshot["llm"]["total_tokens"] == 0
        assert snapshot["broker_api"]["total_calls"] == 0
        assert snapshot["trades"]["count"] == 0


class TestGlobalSingleton:
    """Tests for get_cost_tracker() singleton."""

    def teardown_method(self):
        reset_cost_tracker()

    def test_returns_same_instance(self):
        """get_cost_tracker returns the same instance."""
        t1 = get_cost_tracker()
        t2 = get_cost_tracker()
        assert t1 is t2

    def test_reset_creates_new_instance(self):
        """After reset, a new instance is returned."""
        t1 = get_cost_tracker()
        reset_cost_tracker()
        t2 = get_cost_tracker()
        assert t1 is not t2
