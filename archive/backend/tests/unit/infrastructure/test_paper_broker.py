"""Tests for PaperBroker cost model — realistic NSE costs."""

import pytest

from app.infrastructure.adapters.paper_broker import TradeCosts, compute_trade_costs


class TestComputeTradeCosts:
    """Test the cost model formulas per spec."""

    def test_nifty_atm_round_trip(self):
        """NIFTY ATM option: ₹24000 × 25 lot = ₹6,00,000 notional."""
        notional = 600000.0
        costs = compute_trade_costs(notional=notional, slippage_bps=15.0, is_sell=True)

        # Slippage: 600000 × 15/10000 = 900
        assert costs.slippage == pytest.approx(900.0)

        # STT (sell side): 600000 × 0.000625 = 375
        assert costs.stt == pytest.approx(375.0)

        # Exchange fee: 600000 × 0.000495 × 2 = 594
        assert costs.exchange_fee == pytest.approx(594.0)

        # Brokerage: 20 × 2 = 40
        assert costs.brokerage == pytest.approx(40.0)

        # GST: 40 × 0.18 = 7.2
        assert costs.gst == pytest.approx(7.2)

        # SEBI: 600000 × 0.000001 × 2 = 1.2
        assert costs.sebi_charges == pytest.approx(1.2)

        # Total
        expected_total = 900 + 375 + 594 + 40 + 7.2 + 1.2
        assert costs.total == pytest.approx(expected_total)

    def test_no_stt_on_buy_leg(self):
        """Buy leg should have zero STT."""
        costs_buy = compute_trade_costs(notional=600000, is_sell=False)
        costs_sell = compute_trade_costs(notional=600000, is_sell=True)
        assert costs_buy.stt == 0.0
        assert costs_sell.stt > 0.0

    def test_total_always_positive(self):
        """Total cost must always be positive."""
        for notional in [1000, 10000, 100000, 1000000]:
            costs = compute_trade_costs(notional=notional, is_sell=True)
            assert costs.total > 0

    def test_breakdown_str(self):
        costs = compute_trade_costs(notional=600000, is_sell=True)
        breakdown = costs.breakdown_str()
        assert "Slippage=" in breakdown
        assert "Total=" in breakdown

    def test_mcx_crudeoil(self):
        """MCX CRUDEOIL: 10 bps slippage, futures (no STT on buy)."""
        notional = 500000.0
        costs = compute_trade_costs(notional=notional, slippage_bps=10.0, is_sell=False)
        assert costs.slippage == pytest.approx(500.0)  # 500000 × 10/10000
        assert costs.stt == 0.0  # Buy side, no STT

    def test_higher_slippage_for_otm(self):
        """OTM contracts should have higher slippage than ATM."""
        notional = 300000.0
        atm = compute_trade_costs(notional=notional, slippage_bps=15.0, is_sell=False)
        otm = compute_trade_costs(notional=notional, slippage_bps=40.0, is_sell=False)
        assert otm.slippage > atm.slippage


class TestTradeCostsBreakdown:
    def test_breakdown_format(self):
        costs = TradeCosts(
            slippage=900,
            stt=375,
            exchange_fee=594,
            brokerage=40,
            gst=7.2,
            sebi_charges=1.2,
            total=1917.4,
        )
        s = costs.breakdown_str()
        assert "900" in s
        assert "1917.40" in s
