"""Tests for slippage model validation."""

import pytest

from quant.contracts.aggregates import Portfolio, PortfolioConfig
from quant.contracts.enums import Side


class TestSlippageModel:
    """Tests to validate slippage model is correct."""

    def test_long_entry_slippage_adverse(self):
        """LONG entry: should pay more (slippage = adverse selection)."""
        config = PortfolioConfig()
        portfolio = Portfolio(config=config)

        price = portfolio._apply_slippage(100.0, Side.LONG, is_entry=True)

        assert float(price) > 100.0
        assert float(price) == pytest.approx(100.15, rel=0.001)

    def test_short_entry_slippage_adverse(self):
        """SHORT entry: should receive less (slippage = adverse selection)."""
        config = PortfolioConfig()
        portfolio = Portfolio(config=config)

        price = portfolio._apply_slippage(100.0, Side.SHORT, is_entry=True)

        assert float(price) < 100.0
        assert float(price) == pytest.approx(99.85, rel=0.001)

    def test_long_exit_slippage_adverse(self):
        """LONG exit: should receive less (slippage = adverse selection)."""
        config = PortfolioConfig()
        portfolio = Portfolio(config=config)

        price = portfolio._apply_slippage(100.0, Side.LONG, is_entry=False)

        assert float(price) < 100.0
        assert float(price) == pytest.approx(99.85, rel=0.001)

    def test_short_exit_slippage_adverse(self):
        """SHORT exit: should pay more (slippage = adverse selection)."""
        config = PortfolioConfig()
        portfolio = Portfolio(config=config)

        price = portfolio._apply_slippage(100.0, Side.SHORT, is_entry=False)

        assert float(price) > 100.0
        assert float(price) == pytest.approx(100.15, rel=0.001)

    def test_slippage_magnitude(self):
        """Slippage should be configurable percentage."""
        config = PortfolioConfig()
        portfolio = Portfolio(config=config)

        for base_price in [50.0, 100.0, 500.0, 1000.0]:
            long_entry = portfolio._apply_slippage(base_price, Side.LONG, is_entry=True)
            short_entry = portfolio._apply_slippage(
                base_price, Side.SHORT, is_entry=True
            )

            assert float(long_entry) == pytest.approx(base_price * 1.0015, rel=0.001)
            assert float(short_entry) == pytest.approx(base_price * 0.9985, rel=0.001)

    def test_slippage_accumulates(self):
        """Round-trip should accumulate slippage twice."""
        config = PortfolioConfig()
        portfolio = Portfolio(config=config)

        entry_price = portfolio._apply_slippage(100.0, Side.LONG, is_entry=True)
        exit_price = portfolio._apply_slippage(100.0, Side.LONG, is_entry=False)

        total_slippage_pct = (float(entry_price) - float(exit_price)) / 100.0

        assert total_slippage_pct == pytest.approx(0.003, rel=0.1)


class TestCommissionModel:
    """Tests for commission calculation."""

    def test_commission_per_lot(self):
        """Commission should be per lot."""
        config = PortfolioConfig()
        portfolio = Portfolio(config=config)

        comm = portfolio._compute_commission(75, {})

        assert comm > 0

    def test_commission_scales_with_size(self):
        """Commission should scale with position size."""
        config = PortfolioConfig()
        portfolio = Portfolio(config=config)

        small_comm = portfolio._compute_commission(100, {"option_lot_size": 50})
        large_comm = portfolio._compute_commission(1000, {"option_lot_size": 50})

        assert large_comm > small_comm
