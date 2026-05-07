"""Unit tests for PaperBrokerAdapter.

Covers:
- Order submission and validation
- Immediate fill behavior
- Trade cost computation (slippage, STT, fees, brokerage, GST, SEBI)
- Position execution with cost tracking
- Order cancellation
- Position closing
- Account state
- Edge cases (zero price, zero quantity, invalid orders)
"""

from __future__ import annotations

import pytest

from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter, TradeCosts
from app.runtime.pipeline.events import OrderRequest, OrderStatusEvent


# ---------------------------------------------------------------------------
# 1. TradeCosts
# ---------------------------------------------------------------------------

class TestTradeCosts:
    def test_total_sums_all_components(self):
        costs = TradeCosts(
            notional=100000.0, slippage=15.0, stt=62.5,
            exchange_fee=49.5, brokerage=40.0, gst=7.2, sebi=0.1,
        )
        assert costs.total() == 15.0 + 62.5 + 49.5 + 40.0 + 7.2 + 0.1

    def test_total_ignores_notional(self):
        """Notional is tracked but not included in total costs."""
        costs = TradeCosts(
            notional=1000000.0, slippage=10.0, stt=5.0,
            exchange_fee=3.0, brokerage=20.0, gst=3.6, sebi=0.01,
        )
        assert costs.total() == 10.0 + 5.0 + 3.0 + 20.0 + 3.6 + 0.01


# ---------------------------------------------------------------------------
# 2. PaperBrokerAdapter — order submission
# ---------------------------------------------------------------------------

class TestOrderSubmission:
    def _broker(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_valid_order_is_filled_immediately(self):
        broker = self._broker()
        request = OrderRequest(
            symbol="NIFTY", side="BUY", quantity=1.0,
            price=22000.0, order_type="LIMIT",
            correlation_id="test-1",
        )
        result = broker.submit_order(request)
        assert result.status == "FILLED"
        assert result.filled_quantity == 1.0
        assert result.filled_price == 22000.0
        assert result.remaining_quantity == 0.0

    def test_zero_quantity_rejected(self):
        broker = self._broker()
        request = OrderRequest(
            symbol="NIFTY", side="BUY", quantity=0.0,
            price=22000.0, correlation_id="test-2",
        )
        result = broker.submit_order(request)
        assert result.status == "REJECTED"
        assert "quantity" in result.reject_reason.lower()

    def test_negative_quantity_rejected(self):
        broker = self._broker()
        request = OrderRequest(
            symbol="NIFTY", side="BUY", quantity=-1.0,
            price=22000.0, correlation_id="test-3",
        )
        result = broker.submit_order(request)
        assert result.status == "REJECTED"

    def test_zero_price_rejected(self):
        broker = self._broker()
        request = OrderRequest(
            symbol="NIFTY", side="BUY", quantity=1.0,
            price=0.0, correlation_id="test-4",
        )
        result = broker.submit_order(request)
        assert result.status == "REJECTED"
        assert "price" in result.reject_reason.lower()

    def test_negative_price_rejected(self):
        broker = self._broker()
        request = OrderRequest(
            symbol="NIFTY", side="BUY", quantity=1.0,
            price=-100.0, correlation_id="test-5",
        )
        result = broker.submit_order(request)
        assert result.status == "REJECTED"

    def test_order_id_from_correlation_id(self):
        broker = self._broker()
        request = OrderRequest(
            symbol="NIFTY", side="BUY", quantity=1.0,
            price=22000.0, correlation_id="my-order-123",
        )
        result = broker.submit_order(request)
        assert result.order_id == "my-order-123"

    def test_order_id_from_position_id(self):
        broker = self._broker()
        request = OrderRequest(
            symbol="NIFTY", side="BUY", quantity=1.0,
            price=22000.0, position_id="pos-456",
        )
        result = broker.submit_order(request)
        assert result.order_id == "pos-456"

    def test_order_id_auto_generated(self):
        broker = self._broker()
        request = OrderRequest(
            symbol="NIFTY", side="BUY", quantity=1.0,
            price=22000.0,
        )
        result = broker.submit_order(request)
        assert result.order_id.startswith("paper-")


# ---------------------------------------------------------------------------
# 3. Trade cost computation
# ---------------------------------------------------------------------------

class TestTradeCostComputation:
    def _broker(self, **kwargs) -> PaperBrokerAdapter:
        return PaperBrokerAdapter(**kwargs)

    def test_slippage_based_on_bps(self):
        broker = self._broker(slippage_bps=15.0)
        costs = broker._compute_costs(100.0, 10.0, is_sell=False)
        notional = 1000.0
        expected_slippage = notional * (15.0 / 10000.0)  # 1.5
        assert abs(costs.slippage - expected_slippage) < 0.01

    def test_stt_applied_only_on_sell(self):
        broker = self._broker(stt_pct=0.000625)
        buy_costs = broker._compute_costs(100.0, 10.0, is_sell=False)
        sell_costs = broker._compute_costs(100.0, 10.0, is_sell=True)
        assert buy_costs.stt == 0.0
        assert sell_costs.stt > 0.0
        expected_stt = 1000.0 * 0.000625  # 0.625
        assert abs(sell_costs.stt - expected_stt) < 0.01

    def test_exchange_fee_applies_both_sides(self):
        broker = self._broker(exchange_fee_pct=0.000495)
        buy_costs = broker._compute_costs(100.0, 10.0, is_sell=False)
        sell_costs = broker._compute_costs(100.0, 10.0, is_sell=True)
        assert buy_costs.exchange_fee > 0
        assert sell_costs.exchange_fee > 0
        assert abs(buy_costs.exchange_fee - sell_costs.exchange_fee) < 0.01

    def test_brokerage_fixed_per_order(self):
        broker = self._broker(brokerage_per_order=20.0)
        costs = broker._compute_costs(100.0, 10.0, is_sell=False)
        # Brokerage * 2.0 (entry + exit concept)
        assert costs.brokerage == 40.0

    def test_gst_on_brokerage(self):
        broker = self._broker(brokerage_per_order=20.0, gst_pct=0.18)
        costs = broker._compute_costs(100.0, 10.0, is_sell=False)
        expected_gst = 40.0 * 0.18  # 7.2
        assert abs(costs.gst - expected_gst) < 0.01

    def test_sebi_levy_on_notional(self):
        broker = self._broker(sebi_pct=0.000001)
        costs = broker._compute_costs(100000.0, 1.0, is_sell=False)
        expected_sebi = 100000.0 * 0.000001  # 0.1
        assert abs(costs.sebi - expected_sebi) < 0.01

    def test_cost_model_can_be_disabled(self):
        broker = self._broker(cost_model_enabled=False)
        # When disabled, _compute_costs still works but caller should skip recording
        costs = broker._compute_costs(100.0, 10.0, is_sell=False)
        assert costs.total() > 0  # Computation still works

    def test_total_cost_round_trip_estimate(self):
        """Estimate round-trip cost for a typical NIFTY futures trade."""
        broker = PaperBrokerAdapter()
        price = 22000.0
        size = 1.0
        buy_costs = broker._compute_costs(price, size, is_sell=False)
        sell_costs = broker._compute_costs(price, size, is_sell=True)
        total_round_trip = buy_costs.total() + sell_costs.total()
        # Should be reasonable (not zero, not astronomical)
        assert total_round_trip > 0
        assert total_round_trip < 500.0  # Should be under ₹500 for single lot


# ---------------------------------------------------------------------------
# 4. Position management
# ---------------------------------------------------------------------------

class TestPositionManagement:
    def _broker(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_get_positions_empty(self):
        broker = self._broker()
        assert broker.get_positions() == []

    def test_get_account_empty(self):
        broker = self._broker()
        account = broker.get_account()
        assert account["open_positions"] == 0
        assert account["positions"] == []

    def test_cancel_nonexistent_order(self):
        broker = self._broker()
        assert broker.cancel_order("nonexistent") is False

    def test_close_nonexistent_position(self):
        broker = self._broker()
        assert broker.close_position("nonexistent", 100.0) is False


# ---------------------------------------------------------------------------
# 5. Multiple orders
# ---------------------------------------------------------------------------

class TestMultipleOrders:
    def test_sequential_orders_get_unique_ids(self):
        broker = PaperBrokerAdapter()
        r1 = broker.submit_order(OrderRequest(symbol="A", side="BUY", quantity=1, price=100))
        r2 = broker.submit_order(OrderRequest(symbol="B", side="BUY", quantity=1, price=200))
        r3 = broker.submit_order(OrderRequest(symbol="C", side="BUY", quantity=1, price=300))
        assert r1.order_id != r2.order_id
        assert r2.order_id != r3.order_id

    def test_all_orders_filled(self):
        broker = PaperBrokerAdapter()
        for i in range(10):
            request = OrderRequest(
                symbol="NIFTY", side="BUY", quantity=1.0,
                price=22000.0 + i * 100,
            )
            result = broker.submit_order(request)
            assert result.status == "FILLED"


# ---------------------------------------------------------------------------
# 6. Cost impact on trade economics
# ---------------------------------------------------------------------------

class TestCostImpact:
    def test_larger_notional_higher_costs(self):
        broker = PaperBrokerAdapter()
        small = broker._compute_costs(1000.0, 1.0, is_sell=False)
        large = broker._compute_costs(10000.0, 1.0, is_sell=False)
        assert large.total() > small.total()

    def test_sell_more_expensive_than_buy_due_to_stt(self):
        broker = PaperBrokerAdapter()
        buy = broker._compute_costs(1000.0, 1.0, is_sell=False)
        sell = broker._compute_costs(1000.0, 1.0, is_sell=True)
        assert sell.total() > buy.total()

    def test_slippage_scales_with_notional(self):
        broker = PaperBrokerAdapter(slippage_bps=15.0)
        c1 = broker._compute_costs(1000.0, 1.0, is_sell=False)
        c10 = broker._compute_costs(10000.0, 1.0, is_sell=False)
        # Slippage should scale proportionally
        assert c10.slippage > c1.slippage
