"""Integration tests for Signal Tracking.

Tests that signal tracking is properly integrated with the trading session
and records all decision points correctly.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch
from app.application.services.signal_tracking_service import SignalTrackingService


class TestSignalTrackingIntegration:
    """Test signal tracking integration with trading session."""

    def test_tracks_signal_generation(self):
        """Should track when signals are generated."""
        storage = MagicMock()
        storage.save_position_event = MagicMock()
        tracker = SignalTrackingService(storage=storage)

        # Simulate signal generation
        decision = tracker.track_signal_generated(
            symbol="CRUDEOIL",
            direction="LONG",
            confidence="High",
            aggression_score=3.5,
            drive_number=2,
            market_state="BALANCED",
            price=6100.0,
            poc=6100.0,
            vah=6150.0,
            val=6050.0,
            cvd_slope=0.5,
            agent_direction="LONG",
            agent_probability=0.75,
            agent_regime="TREND",
        )

        assert decision.decision_type == "GENERATED"
        stats = tracker.get_stats("CRUDEOIL")
        assert stats["generated"] == 1

    def test_tracks_gate_blocks(self):
        """Should track when gates block signals."""
        storage = MagicMock()
        storage.save_position_event = MagicMock()
        tracker = SignalTrackingService(storage=storage)

        # Simulate gate blocks
        gates = ["CVD", "PROFILE_SHAPE", "MOMENTUM_FADE", "CONTESTED_ZONE"]
        for gate in gates:
            tracker.track_gate_block(
                symbol="CRUDEOIL",
                gate_name=gate,
                gate_reason=f"{gate}_OPPOSING",
                gate_detail=f"Blocked by {gate}",
                market_state="BALANCED",
            )

        stats = tracker.get_stats("CRUDEOIL")
        assert stats["blocked"] == 4
        assert stats["generated"] == 0

        # Check gate breakdown
        summary = tracker.get_gate_block_summary("CRUDEOIL")
        assert len(summary) == 4

    def test_tracks_waiting_states(self):
        """Should track waiting states."""
        storage = MagicMock()
        tracker = SignalTrackingService(storage=storage)

        tracker.track_waiting(
            symbol="CRUDEOIL",
            reason="Waiting for second drive",
            market_state="BALANCED",
        )

        stats = tracker.get_stats("CRUDEOIL")
        assert stats["waiting"] == 1

    def test_tracks_cooldown_states(self):
        """Should track cooldown states."""
        storage = MagicMock()
        tracker = SignalTrackingService(storage=storage)

        tracker.track_cooldown(symbol="CRUDEOIL", time_remaining=45.0)

        stats = tracker.get_stats("CRUDEOIL")
        assert stats["cooldown"] == 1

    def test_aggregate_stats_across_symbols(self):
        """Should aggregate stats across multiple symbols."""
        storage = MagicMock()
        tracker = SignalTrackingService(storage=storage)

        # CRUDEOIL: 1 generated, 2 blocked
        tracker.track_signal_generated(
            symbol="CRUDEOIL", direction="LONG", confidence="High",
            aggression_score=3.5, drive_number=2, market_state="BALANCED",
            price=6100.0, poc=6100.0, vah=6150.0, val=6050.0, cvd_slope=0.5,
        )
        tracker.track_gate_block(
            symbol="CRUDEOIL", gate_name="CVD", gate_reason="CVD_OPPOSING",
            gate_detail="Blocked", market_state="BALANCED",
        )
        tracker.track_gate_block(
            symbol="CRUDEOIL", gate_name="PROFILE_SHAPE", gate_reason="PROFILE_SHAPE_P",
            gate_detail="Blocked", market_state="BALANCED",
        )

        # GOLD: 2 generated, 1 blocked
        tracker.track_signal_generated(
            symbol="GOLD", direction="SHORT", confidence="Medium",
            aggression_score=2.5, drive_number=2, market_state="IMBALANCED",
            price=61000.0, poc=61000.0, vah=61500.0, val=60500.0, cvd_slope=-1.0,
        )
        tracker.track_signal_generated(
            symbol="GOLD", direction="LONG", confidence="High",
            aggression_score=3.0, drive_number=2, market_state="BALANCED",
            price=61000.0, poc=61000.0, vah=61500.0, val=60500.0, cvd_slope=0.5,
        )
        tracker.track_gate_block(
            symbol="GOLD", gate_name="MOMENTUM_FADE", gate_reason="MOMENTUM_FADE",
            gate_detail="Blocked", market_state="BALANCED",
        )

        # Per-symbol stats
        crude_stats = tracker.get_stats("CRUDEOIL")
        assert crude_stats["generated"] == 1
        assert crude_stats["blocked"] == 2

        gold_stats = tracker.get_stats("GOLD")
        assert gold_stats["generated"] == 2
        assert gold_stats["blocked"] == 1

        # Aggregate stats
        total = tracker.get_stats()
        assert total["generated"] == 3
        assert total["blocked"] == 3
        assert total["generation_rate"] == 50.0
        assert total["block_rate"] == 50.0

    def test_generation_rate_calculation(self):
        """Should correctly calculate generation rate.

        Note: identical consecutive BLOCKED entries (same gate_name + gate_reason)
        are deduped for both the decisions list and the stats count.
        """
        storage = MagicMock()
        tracker = SignalTrackingService(storage=storage)

        # 1 generated, 3 blocked (2 are deduped as identical CVD_OPPOSING), 2 waiting = 4 unique
        tracker.track_signal_generated(
            symbol="CRUDEOIL", direction="LONG", confidence="High",
            aggression_score=3.5, drive_number=2, market_state="BALANCED",
            price=6100.0, poc=6100.0, vah=6150.0, val=6050.0, cvd_slope=0.5,
        )
        for _ in range(3):
            tracker.track_gate_block(
                symbol="CRUDEOIL", gate_name="CVD", gate_reason="CVD_OPPOSING",
                gate_detail="Blocked", market_state="BALANCED",
            )
        for _ in range(2):
            tracker.track_waiting(
                symbol="CRUDEOIL",
                reason="Waiting for setup",
            )

        stats = tracker.get_stats()
        # 1 generated / 4 total unique = 25.0%
        assert abs(stats["generation_rate"] - 25.0) < 0.1
        # 1 blocked / 4 total unique = 25.0%
        assert abs(stats["block_rate"] - 25.0) < 0.1

    def test_persists_to_storage(self):
        """Should persist decisions to storage."""
        storage = MagicMock()
        storage.save_position_event = MagicMock()
        tracker = SignalTrackingService(storage=storage)

        tracker.track_signal_generated(
            symbol="CRUDEOIL", direction="LONG", confidence="High",
            aggression_score=3.5, drive_number=2, market_state="BALANCED",
            price=6100.0, poc=6100.0, vah=6150.0, val=6050.0, cvd_slope=0.5,
        )

        storage.save_position_event.assert_called_once()
        call_args = storage.save_position_event.call_args[0][0]
        assert call_args["event_type"] == "SIGNAL_GENERATED"
        assert call_args["symbol"] == "CRUDEOIL"

    def test_get_recent_decisions(self):
        """Should return recent decisions in chronological order."""
        storage = MagicMock()
        tracker = SignalTrackingService(storage=storage)

        for i in range(10):
            tracker.track_gate_block(
                symbol="CRUDEOIL", gate_name="CVD", gate_reason=f"CVD_OPPOSING_{i}",
                gate_detail=f"Block {i}", market_state="BALANCED",
            )

        recent = tracker.get_recent_decisions("CRUDEOIL", limit=5)
        assert len(recent) == 5
        # Should be the last 5 decisions
        assert recent[-1]["gate_reason"] == "CVD_OPPOSING_9"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])