"""Tests for trade_costs — round-trip cost computation."""

import pytest

from quant.execution.trade_costs import TradeCosts, compute_trade_costs


def test_buy_has_no_stt():
    costs = compute_trade_costs(notional=600_000, is_sell=False)
    assert costs.stt == 0.0
    assert costs.slippage > 0
    assert costs.total == pytest.approx(costs.slippage + costs.exchange_fee + costs.brokerage + costs.gst + costs.sebi_charges)


def test_sell_has_stt():
    costs = compute_trade_costs(notional=600_000, is_sell=True)
    assert costs.stt > 0
    assert costs.stt == pytest.approx(600_000 * 0.000625)


def test_slippage_scales_with_bps():
    base = compute_trade_costs(notional=600_000, slippage_bps=15.0, is_sell=False)
    tight = compute_trade_costs(notional=600_000, slippage_bps=10.0, is_sell=False)
    assert base.slippage == pytest.approx(600_000 * 15 / 10000.0)
    assert tight.slippage < base.slippage


def test_breakdown_str():
    costs = compute_trade_costs(notional=600_000, is_sell=True)
    assert "Slippage=" in costs.breakdown_str()
    assert "Total=" in costs.breakdown_str()


def test_round_trip_double_counted_costs():
    """Brokerage/exchange/SEBI/GST apply on both legs (round trip)."""
    costs = compute_trade_costs(notional=600_000, is_sell=False)
    assert costs.brokerage == pytest.approx(40.0)  # 20 * 2 legs
    assert costs.gst == pytest.approx(40.0 * 0.18)
    assert costs.exchange_fee == pytest.approx(600_000 * 0.000495 * 2)
