"""Phase 3a tests — SnapshotBuilder extraction."""
from unittest.mock import MagicMock
from app.application.services.snapshot_builder import SnapshotBuilder
from app.application.services.trading_session import SessionState


class TestSnapshotBuilder:
    def test_build_empty_session(self):
        session = SessionState(symbol="TEST")
        builder = SnapshotBuilder()
        risk = MagicMock()
        risk.is_halted = False
        risk.halt_reason = ""
        risk.daily_state.consecutive_losses = 0
        risk.daily_state.realized_pnl = 0.0
        lifecycle = MagicMock()
        rl = MagicMock()
        rl.get_status.return_value = {}

        result = builder.build(session, risk, lifecycle, rl)
        assert result["_symbol"] == "TEST"
        assert result["tick"] is None
        assert result["data"] is None

    def test_camel_case_ai_none(self):
        builder = SnapshotBuilder()
        assert builder._camel_case_ai(None) is None

    def test_camel_case_ai_conversion(self):
        builder = SnapshotBuilder()
        data = {"direction": "LONG", "rationale": "test", "confidence": "High"}
        result = builder._camel_case_ai(data)
        assert result["direction"] == "LONG"
        assert "inputPrompt" in result
