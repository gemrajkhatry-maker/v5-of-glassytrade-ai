"""Tests for llm_decision_processor.py — safety nets, mismatch, persistence."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.handlers.llm_decision_processor import (
    LLMDecisionProcessor,
    update_llm_memory,
)


class MockTick:
    def __init__(self, close=100.0):
        self.close = close


class MockAmtResult:
    def __init__(self, vwap_upper_2=0.0):
        self.vwap_upper_2 = vwap_upper_2


class TestApplySafetyNets:
    """Tests for apply_safety_nets()."""

    def test_buy_only_blocks_short(self):
        """BUY-ONLY mode blocks SHORT direction → FLAT."""
        processor = LLMDecisionProcessor(allow_short=False)
        direction, confidence, rationale = processor.apply_safety_nets(
            "SHORT", 0.7, "bearish", MockTick(), MockAmtResult()
        )
        assert direction == "FLAT"
        assert "BUY-ONLY" in rationale

    def test_buy_only_passes_long(self):
        """BUY-ONLY mode passes LONG direction unchanged."""
        processor = LLMDecisionProcessor(allow_short=False)
        direction, confidence, rationale = processor.apply_safety_nets(
            "LONG", 0.7, "bullish", MockTick(), MockAmtResult()
        )
        assert direction == "LONG"
        assert confidence == 0.7

    def test_allow_short_passes_short(self):
        """When allow_short=True, SHORT passes unchanged."""
        processor = LLMDecisionProcessor(allow_short=True)
        direction, confidence, rationale = processor.apply_safety_nets(
            "SHORT", 0.8, "bearish structure", MockTick(), MockAmtResult()
        )
        assert direction == "SHORT"
        assert confidence == 0.8

    def test_vwap_extreme_downgrades_long_confidence(self):
        """LONG at >+2σ VWAP band has confidence downgraded to 0.3."""
        processor = LLMDecisionProcessor(allow_short=True)
        amt = MockAmtResult(vwap_upper_2=100.0)
        tick = MockTick(close=102.0)  # 102 >= 100 * 1.01
        direction, confidence, rationale = processor.apply_safety_nets(
            "LONG", 0.8, "bullish", tick, amt
        )
        assert direction == "LONG"
        assert confidence == 0.3
        assert "VWAP extreme" in rationale

    def test_vwap_extreme_not_triggered_below_threshold(self):
        """LONG below +2σ threshold is not downgraded."""
        processor = LLMDecisionProcessor(allow_short=True)
        amt = MockAmtResult(vwap_upper_2=100.0)
        tick = MockTick(close=100.5)  # 100.5 < 100 * 1.01
        direction, confidence, rationale = processor.apply_safety_nets(
            "LONG", 0.8, "bullish", tick, amt
        )
        assert confidence == 0.8
        assert "VWAP" not in rationale

    def test_vwap_extreme_not_triggered_for_short(self):
        """VWAP extreme check only applies to LONG."""
        processor = LLMDecisionProcessor(allow_short=True)
        amt = MockAmtResult(vwap_upper_2=100.0)
        tick = MockTick(close=98.0)
        direction, confidence, rationale = processor.apply_safety_nets(
            "SHORT", 0.8, "bearish", tick, amt
        )
        assert confidence == 0.8

    def test_vwap_upper_2_zero_skips_check(self):
        """When vwap_upper_2 is 0, VWAP check is skipped."""
        processor = LLMDecisionProcessor(allow_short=True)
        amt = MockAmtResult(vwap_upper_2=0.0)
        tick = MockTick(close=100.0)
        direction, confidence, rationale = processor.apply_safety_nets(
            "LONG", 0.8, "bullish", tick, amt
        )
        assert confidence == 0.8


class TestCheckDirectionMismatch:
    """Tests for check_direction_mismatch()."""

    def test_matching_directions_no_mismatch(self):
        """When agent and LLM agree, no mismatch."""
        processor = LLMDecisionProcessor()
        agent = MagicMock()
        agent.direction = "LONG"
        result = processor.check_direction_mismatch(
            agent, "LONG", "NIFTY", MagicMock(), MagicMock()
        )
        assert result is False

    def test_opposite_directions_mismatch(self):
        """When agent LONG vs LLM SHORT, mismatch detected."""
        processor = LLMDecisionProcessor()
        agent = MagicMock()
        agent.direction = "LONG"
        worker_queue = MagicMock()
        result = processor.check_direction_mismatch(
            agent, "SHORT", "NIFTY", MagicMock(), worker_queue
        )
        assert result is True
        worker_queue.put_nowait.assert_called_once()

    def test_flat_agent_no_mismatch(self):
        """When agent is FLAT, no mismatch check."""
        processor = LLMDecisionProcessor()
        agent = MagicMock()
        agent.direction = "FLAT"
        result = processor.check_direction_mismatch(
            agent, "LONG", "NIFTY", MagicMock(), MagicMock()
        )
        assert result is False

    def test_flat_llm_with_active_agent_mismatch(self):
        """When LLM is FLAT but agent has active direction, mismatch detected."""
        processor = LLMDecisionProcessor()
        agent = MagicMock()
        agent.direction = "LONG"
        worker_queue = MagicMock()
        result = processor.check_direction_mismatch(
            agent, "FLAT", "NIFTY", MagicMock(), worker_queue
        )
        assert result is True  # Agent wants LONG, LLM says FLAT = mismatch

    def test_mismatch_logs_to_journal(self):
        """Mismatch is logged to journal."""
        journal = MagicMock()
        processor = LLMDecisionProcessor(journal=journal)
        agent = MagicMock()
        agent.direction = "LONG"
        session = MagicMock()
        session.last_amt = MagicMock()
        processor.check_direction_mismatch(
            agent, "SHORT", "NIFTY", session, MagicMock()
        )
        journal.log_rejection.assert_called_once()
        assert journal.log_rejection.call_args[1]["reason"] == "AGENT_DIRECTION_MISMATCH"

    def test_mismatch_handles_journal_error(self):
        """Journal error during mismatch is handled gracefully."""
        journal = MagicMock()
        journal.log_rejection.side_effect = RuntimeError("journal crash")
        processor = LLMDecisionProcessor(journal=journal)
        agent = MagicMock()
        agent.direction = "LONG"
        worker_queue = MagicMock()
        result = processor.check_direction_mismatch(
            agent, "SHORT", "NIFTY", MagicMock(), worker_queue
        )
        assert result is True  # Still returns True despite journal error

    def test_mismatch_handles_queue_error(self):
        """Worker queue error during mismatch is handled gracefully."""
        processor = LLMDecisionProcessor()
        agent = MagicMock()
        agent.direction = "LONG"
        worker_queue = MagicMock()
        worker_queue.put_nowait.side_effect = Exception("queue full")
        result = processor.check_direction_mismatch(
            agent, "SHORT", "NIFTY", MagicMock(), worker_queue
        )
        assert result is True

    def test_none_agent_no_mismatch(self):
        """When agent_decision is None, no mismatch."""
        processor = LLMDecisionProcessor()
        result = processor.check_direction_mismatch(
            None, "LONG", "NIFTY", MagicMock(), MagicMock()
        )
        assert result is False


class TestMarkAiDone:
    """Tests for mark_ai_done()."""

    def test_sets_ai_running_false(self):
        """Sets session._ai_running to False."""
        processor = LLMDecisionProcessor()
        session = MagicMock()
        session._lock = MagicMock()
        session._lock.__enter__ = MagicMock(return_value=None)
        session._lock.__exit__ = MagicMock(return_value=None)
        session._ai_running = True
        session._llm_status = "RUNNING"
        processor.mark_ai_done(session)
        assert session._ai_running is False
        assert session._llm_status == "AVAILABLE"

    def test_handles_lock_error(self):
        """Lock error is handled gracefully."""
        processor = LLMDecisionProcessor()
        session = MagicMock()
        session._lock = MagicMock()
        session._lock.__enter__ = MagicMock(side_effect=RuntimeError("lock error"))
        processor.mark_ai_done(session)  # Should not raise


class TestPersistDecision:
    """Tests for persist_decision()."""

    def test_saves_to_storage(self):
        """Decision is saved to storage with all fields."""
        storage = MagicMock()
        processor = LLMDecisionProcessor()
        tick = MockTick(close=100.0)
        amt = MagicMock()
        amt.value_area_high = 105.0
        amt.value_area_low = 95.0
        amt.poc = 100.0
        tick.delta = 50.0
        tick.volume = 1000.0

        processor.persist_decision(
            storage=storage,
            symbol="NIFTY",
            direction="LONG",
            confidence="High",
            rationale="bullish",
            input_prompt="test prompt",
            raw_output='{"direction":"LONG"}',
            market_state="IMBALANCED",
            aggression="3.5",
            tick=tick,
            amt_result=amt,
            profile_shape="B",
            setup_type=MagicMock(value="TREND_MODEL"),
            strategy_hint="TREND_CONTINUATION",
        )
        storage.save_llm_decision.assert_called_once()
        saved_data = storage.save_llm_decision.call_args[0][0]
        assert saved_data["symbol"] == "NIFTY"
        assert saved_data["direction"] == "LONG"
        assert saved_data["price"] == 100.0
        assert saved_data["vah"] == 105.0
        assert saved_data["val"] == 95.0

    def test_no_storage_returns_early(self):
        """When storage is None, returns without error."""
        processor = LLMDecisionProcessor()
        processor.persist_decision(
            storage=None, symbol="NIFTY", direction="LONG", confidence="High",
            rationale="test", input_prompt="", raw_output="", market_state="",
            aggression="", tick=MockTick(), amt_result=MagicMock(),
            profile_shape="", setup_type="", strategy_hint="",
        )  # Should not raise

    def test_storage_error_handled(self):
        """Storage error is caught and logged."""
        storage = MagicMock()
        storage.save_llm_decision.side_effect = RuntimeError("storage crash")
        processor = LLMDecisionProcessor()
        processor.persist_decision(
            storage=storage, symbol="NIFTY", direction="LONG", confidence="High",
            rationale="test", input_prompt="", raw_output="", market_state="",
            aggression="", tick=MockTick(), amt_result=MagicMock(),
            profile_shape="", setup_type="", strategy_hint="",
        )  # Should not raise


class TestUpdateLlmMemory:
    """Tests for update_llm_memory()."""

    def test_appends_to_memory(self):
        """Appends summary to session memory."""
        session = MagicMock()
        session._llm_memory = []
        update_llm_memory(session, "LONG", "bullish structure confirmed")
        assert len(session._llm_memory) == 1
        assert "LONG: bullish structure confirmed" in session._llm_memory[0]

    def test_creates_memory_list_if_missing(self):
        """Creates _llm_memory list if not present."""
        session = MagicMock(spec=[])  # No _llm_memory attribute
        update_llm_memory(session, "SHORT", "bearish")
        assert hasattr(session, "_llm_memory")
        assert len(session._llm_memory) == 1

    def test_truncates_to_last_5(self):
        """Memory is truncated to last 5 entries."""
        session = MagicMock()
        session._llm_memory = ["entry1", "entry2", "entry3", "entry4", "entry5"]
        update_llm_memory(session, "LONG", "new entry")
        assert len(session._llm_memory) == 5
        assert "new entry" in session._llm_memory[-1]
        assert "entry1" not in session._llm_memory

    def test_truncates_rationale_to_100_chars(self):
        """Rationale is truncated to 100 chars in summary."""
        session = MagicMock()
        session._llm_memory = []
        long_rationale = "x" * 200
        update_llm_memory(session, "LONG", long_rationale)
        assert "xxx..." in session._llm_memory[0]
        assert len(session._llm_memory[0]) < 120
