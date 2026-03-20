"""Unit tests for SignalTrackingService.

Tests comprehensive tracking of signal generation decisions.
"""

import pytest
from unittest.mock import MagicMock
from app.application.services.signal_tracking_service import SignalTrackingService


class TestSignalTrackingService:
    """Test suite for SignalTrackingService."""

    def _create_service(self):
        """Create a SignalTrackingService with mock storage."""
        storage = MagicMock()
        storage.save_position_event = MagicMock()
        return SignalTrackingService(storage=storage), storage

    def test_initial_state(self):
        """New service should have empty stats."""
        service = SignalTrackingService()
        stats = service.get_stats()
        assert stats["generated"] == 0
        assert stats["blocked"] == 0
        assert stats["waiting"] == 0
        assert stats["cooldown"] == 0

    def test_track_signal_generated(self):
        """Should track a generated signal."""
        service, _ = self._create_service()
        decision = service.track_signal_generated(
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
        )
        assert decision.decision_type == "GENERATED"
        assert decision.direction == "LONG"
        assert decision.confidence == "High"
        stats = service.get_stats("CRUDEOIL")
        assert stats["generated"] == 1
        assert stats["blocked"] == 0

    def test_track_gate_block(self):
        """Should track a gate block."""
        service, _ = self._create_service()
        decision = service.track_gate_block(
            symbol="CRUDEOIL",
            gate_name="CVD",
            gate_reason="CVD_OPPOSING",
            gate_detail="LONG blocked — CVD slope -6000 (extreme selling)",
            market_state="BALANCED",
            price=6100.0,
            poc=6100.0,
            cvd_slope=-6000.0,
        )
        assert decision.decision_type == "BLOCKED"
        assert decision.gate_name == "CVD"
        assert decision.gate_reason == "CVD_OPPOSING"
        stats = service.get_stats("CRUDEOIL")
        assert stats["generated"] == 0
        assert stats["blocked"] == 1
        assert stats["gate_blocks"]["CVD"] == 1

    def test_track_waiting(self):
        """Should track a waiting state."""
        service, _ = self._create_service()
        decision = service.track_waiting(
            symbol="CRUDEOIL",
            reason="Waiting for second drive",
            market_state="BALANCED",
        )
        assert decision.decision_type == "WAITING"
        stats = service.get_stats("CRUDEOIL")
        assert stats["waiting"] == 1

    def test_track_cooldown(self):
        """Should track a cooldown state."""
        service, _ = self._create_service()
        decision = service.track_cooldown(
            symbol="CRUDEOIL",
            time_remaining=45.0,
        )
        assert decision.decision_type == "COOLDOWN"
        assert "45s" in decision.gate_reason
        stats = service.get_stats("CRUDEOIL")
        assert stats["cooldown"] == 1

    def test_get_stats_aggregate(self):
        """Should aggregate stats across symbols."""
        service, _ = self._create_service()
        service.track_signal_generated(
            symbol="CRUDEOIL", direction="LONG", confidence="High",
            aggression_score=3.5, drive_number=2, market_state="BALANCED",
            price=6100.0, poc=6100.0, vah=6150.0, val=6050.0, cvd_slope=0.5,
        )
        service.track_gate_block(
            symbol="CRUDEOIL", gate_name="CVD", gate_reason="CVD_OPPOSING",
            gate_detail="Blocked", market_state="BALANCED",
        )
        service.track_signal_generated(
            symbol="GOLD", direction="SHORT", confidence="Medium",
            aggression_score=2.5, drive_number=2, market_state="IMBALANCED",
            price=61000.0, poc=61000.0, vah=61500.0, val=60500.0, cvd_slope=-1.0,
        )

        # Per-symbol stats
        crude_stats = service.get_stats("CRUDEOIL")
        assert crude_stats["generated"] == 1
        assert crude_stats["blocked"] == 1

        gold_stats = service.get_stats("GOLD")
        assert gold_stats["generated"] == 1
        assert gold_stats["blocked"] == 0

        # Aggregate stats
        total_stats = service.get_stats()
        assert total_stats["generated"] == 2
        assert total_stats["blocked"] == 1

    def test_get_stats_rates(self):
        """Should calculate generation and block rates."""
        service, _ = self._create_service()
        service.track_signal_generated(
            symbol="CRUDEOIL", direction="LONG", confidence="High",
            aggression_score=3.5, drive_number=2, market_state="BALANCED",
            price=6100.0, poc=6100.0, vah=6150.0, val=6050.0, cvd_slope=0.5,
        )
        service.track_gate_block(
            symbol="CRUDEOIL", gate_name="CVD", gate_reason="CVD_OPPOSING",
            gate_detail="Blocked", market_state="BALANCED",
        )
        service.track_gate_block(
            symbol="CRUDEOIL", gate_name="PROFILE_SHAPE", gate_reason="PROFILE_SHAPE_P",
            gate_detail="Blocked", market_state="BALANCED",
        )

        stats = service.get_stats()
        # 1 generated, 2 blocked = 33% generation rate, 67% block rate
        assert stats["generation_rate"] == pytest.approx(33.3, abs=0.1)
        assert stats["block_rate"] == pytest.approx(66.7, abs=0.1)

    def test_get_gate_block_summary(self):
        """Should summarize gate blocks by gate name."""
        service, _ = self._create_service()
        service.track_gate_block(
            symbol="CRUDEOIL", gate_name="CVD", gate_reason="CVD_OPPOSING",
            gate_detail="Blocked", market_state="BALANCED",
        )
        service.track_gate_block(
            symbol="CRUDEOIL", gate_name="CVD", gate_reason="CVD_OPPOSING",
            gate_detail="Blocked again", market_state="BALANCED",
        )
        service.track_gate_block(
            symbol="CRUDEOIL", gate_name="PROFILE_SHAPE", gate_reason="PROFILE_SHAPE_P",
            gate_detail="Blocked", market_state="BALANCED",
        )

        summary = service.get_gate_block_summary("CRUDEOIL")
        assert summary["CVD"] == 2
        assert summary["PROFILE_SHAPE"] == 1

    def test_get_recent_decisions(self):
        """Should return recent decisions in order."""
        service, _ = self._create_service()
        for i in range(5):
            service.track_gate_block(
                symbol="CRUDEOIL", gate_name="CVD", gate_reason="CVD_OPPOSING",
                gate_detail=f"Block {i}", market_state="BALANCED",
            )
        service.track_signal_generated(
            symbol="CRUDEOIL", direction="LONG", confidence="High",
            aggression_score=3.5, drive_number=2, market_state="BALANCED",
            price=6100.0, poc=6100.0, vah=6150.0, val=6050.0, cvd_slope=0.5,
        )

        recent = service.get_recent_decisions("CRUDEOIL", limit=3)
        assert len(recent) == 3
        # Should be the last 3 decisions
        assert recent[-1]["type"] == "GENERATED"

    def test_clear(self):
        """Should clear tracking data."""
        service, _ = self._create_service()
        service.track_signal_generated(
            symbol="CRUDEOIL", direction="LONG", confidence="High",
            aggression_score=3.5, drive_number=2, market_state="BALANCED",
            price=6100.0, poc=6100.0, vah=6150.0, val=6050.0, cvd_slope=0.5,
        )
        assert service.get_stats("CRUDEOIL")["generated"] == 1

        service.clear("CRUDEOIL")
        assert service.get_stats("CRUDEOIL")["generated"] == 0

    def test_empty_stats(self):
        """Should return empty stats for unknown symbol."""
        service = SignalTrackingService()
        stats = service.get_stats("UNKNOWN")
        assert stats["generated"] == 0
        assert stats["blocked"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])