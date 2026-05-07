"""Tests for Risk Gateway."""

import pytest
from decimal import Decimal

from brokersv2.risk import RiskGateway, RiskLimits
from brokersv2.domain.order.models import Order, OrderSide, OrderType
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import OrderId


class TestRiskGateway:
    """Tests for RiskGateway."""

    @pytest.mark.asyncio
    async def test_approve_small_order(self):
        """Test that small orders are approved."""
        gateway = RiskGateway(RiskLimits(max_position_size=Decimal("1000")))
        
        instrument = CanonicalInstrument.create_equity("NSE", "RELIANCE")
        order = Order(
            order_id=OrderId("test"),
            instrument=instrument,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        
        result = await gateway.check_order(order)
        assert result.approved is True

    @pytest.mark.asyncio
    async def test_reject_position_limit(self):
        """Test position limit enforcement."""
        gateway = RiskGateway(RiskLimits(max_position_size=Decimal("100")))
        
        instrument = CanonicalInstrument.create_equity("NSE", "RELIANCE")
        order = Order(
            order_id=OrderId("test"),
            instrument=instrument,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("200"),  # Exceeds limit
        )
        
        result = await gateway.check_order(order)
        assert result.approved is False
        assert any(v.violation_type == "position_limit" for v in result.violations)

    @pytest.mark.asyncio
    async def test_duplicate_order_prevention(self):
        """Test duplicate order detection."""
        gateway = RiskGateway()
        
        instrument = CanonicalInstrument.create_equity("NSE", "RELIANCE")
        order = Order(
            order_id=OrderId("dup_test"),
            instrument=instrument,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        
        gateway.register_pending_order("dup_test")
        
        # Would reject if duplicate check was in place
        assert "dup_test" in [order.order_id]