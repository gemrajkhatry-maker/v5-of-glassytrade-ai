"""Tests for Portfolio.recover_position."""

from __future__ import annotations

import pytest
from decimal import Decimal

from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.enums import Side, Source, PositionStatus


class TestRecoverPosition:
    """Test crash recovery of positions from storage."""

    def test_recover_basic_long(self):
        """LONG position with all standard fields should be restored."""
        portfolio = Portfolio.create_default()
        pos_data = {
            "id": "test-pos-001",
            "symbol": "NATURALGAS 23 APR 255 CALL",
            "side": "LONG",
            "entry_price": 19.88,
            "size": 6364,
            "stop_loss": 19.88,
            "take_profit": 20.10,
            "source": "AMT",
            "opened_at": "2026-04-07T14:00:00Z",
        }

        recovered = portfolio.recover_position(pos_data)
        assert recovered is not None
        assert recovered.id == "test-pos-001"
        assert recovered.symbol == "NATURALGAS 23 APR 255 CALL"
        assert recovered.side == Side.LONG
        assert recovered.source == Source.AMT
        assert recovered.entry_price == Decimal("19.88")
        assert recovered.size == Decimal("6364")
        assert recovered.stop_loss == Decimal("19.88")
        assert recovered.take_profit == Decimal("20.10")
        assert recovered.status == PositionStatus.OPEN
        assert recovered.is_open is True

    def test_recover_short(self):
        """SHORT position should have correct side."""
        portfolio = Portfolio.create_default()
        pos_data = {
            "id": "test-pos-002",
            "symbol": "CRUDEOIL 16 APR 10450 PUT",
            "side": "SHORT",
            "entry_price": 700.0,
            "size": 1000,
            "stop_loss": 710.0,
            "take_profit": 670.0,
            "source": "LLM",
            "opened_at": "2026-04-07T10:00:00Z",
        }

        recovered = portfolio.recover_position(pos_data)
        assert recovered is not None
        assert recovered.side == Side.SHORT
        assert recovered.source == Source.LLM

    def test_recover_duplicate_id_ignored(self):
        """Second recovery of same ID should return None."""
        portfolio = Portfolio.create_default()
        pos_data = {
            "id": "dup-pos",
            "symbol": "NATURALGAS 23 APR 250 CALL",
            "side": "LONG",
            "entry_price": 25.0,
            "size": 1000,
            "stop_loss": 24.0,
            "take_profit": 27.0,
        }

        first = portfolio.recover_position(pos_data)
        assert first is not None

        second = portfolio.recover_position(pos_data)
        assert second is None
        assert len(portfolio.positions) == 1

    def test_recover_no_id_returns_none(self):
        """Dict without 'id' should not recover."""
        portfolio = Portfolio.create_default()
        pos_data = {"symbol": "NATURALGAS 23 APR 255 CALL", "side": "LONG"}
        assert portfolio.recover_position(pos_data) is None

    def test_recover_defaults_for_missing_fields(self):
        """Minimal dict should still create a position with defaults."""
        portfolio = Portfolio.create_default()
        pos_data = {"id": "minimal"}

        recovered = portfolio.recover_position(pos_data)
        assert recovered is not None
        assert recovered.id == "minimal"
        assert recovered.side == Side.LONG  # default
        assert recovered.source == Source.AMT  # default
        assert recovered.size == Decimal("0")
        assert recovered.entry_price == Decimal("0")

    def test_recover_multiple_positions(self):
        """Recovering multiple positions should append all."""
        portfolio = Portfolio.create_default()

        data1 = {
            "id": "pos1", "symbol": "CRUDEOIL 16 APR 10450 CALL",
            "side": "LONG", "entry_price": 1060.0, "size": 500,
            "stop_loss": 1050.0, "take_profit": 1080.0,
        }
        data2 = {
            "id": "pos2", "symbol": "NATURALGAS 23 APR 255 CALL",
            "side": "LONG", "entry_price": 21.0, "size": 1750,
            "stop_loss": 20.0, "take_profit": 22.0,
        }

        r1 = portfolio.recover_position(data1)
        r2 = portfolio.recover_position(data2)

        assert r1 is not None
        assert r2 is not None
        assert len(portfolio.positions) == 2
        assert portfolio.positions[0].id == "pos1"
        assert portfolio.positions[1].id == "pos2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
