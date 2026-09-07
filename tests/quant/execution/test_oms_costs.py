"""Production paper OMS factory contracts."""

import pytest

from quant.contracts.contracts import ContractRef
from quant.decision.signal_builder import Signal
from quant.execution.oms_factory import make_paper_oms


def _contract():
    return ContractRef(
        symbol="NIFTY 8 SEP 23850 CALL",
        exchange="NFO",
        expiry="2026-09-08",
        strike=23850,
        option_type="CE",
        lot_size=65,
        tick_size=0.05,
    )


def _cost_profile():
    return {
        "slippage_bps": 10,
        "stt_pct": 0.000625,
        "exchange_fee_pct": 0.000495,
        "brokerage_per_order": 20.0,
        "gst_on_brokerage_pct": 0.18,
        "sebi_charges_pct": 0.000001,
        "fill_mode": "bid_ask",
    }


def _signal(entry=150.0):
    return Signal(
        type="LONG",
        reason="factory-test",
        entry=entry,
        sl=145.0,
        tp=160.0,
        rr=2.0,
        model_label="AMT",
        symbol=_contract().symbol,
        timestamp="2026-09-07T10:00:00+05:30",
    )


def test_factory_refuses_missing_cost_profile():
    with pytest.raises(ValueError, match="cost_profile"):
        make_paper_oms(contract=_contract(), cost_profile=None)


def test_factory_requires_validated_contract():
    with pytest.raises(ValueError, match="ContractRef"):
        make_paper_oms(contract="NIFTY", cost_profile=_cost_profile())


def test_factory_uses_executable_quotes_and_net_cost_pnl():
    oms = make_paper_oms(
        contract=_contract(),
        cost_profile=_cost_profile(),
        quote_provider=lambda: (149.5, 150.5),
    )

    position = oms.submit(_signal(), quantity=65)
    fill = oms.close(position, price=155.0, time="2026-09-07T10:05:00+05:30", reason="TP")

    assert position.open_price == pytest.approx(150.5)
    assert fill.close_price == pytest.approx(149.5)
    gross = (149.5 - 150.5) * 65
    assert fill.pnl < gross
    assert oms.last_fill is not None
    assert oms.last_fill.costs.total > 0


def test_factory_fails_closed_when_bid_ask_is_unavailable():
    oms = make_paper_oms(
        contract=_contract(),
        cost_profile=_cost_profile(),
        quote_provider=lambda: None,
    )

    with pytest.raises(ValueError, match="bid_ask"):
        oms.submit(_signal(), quantity=65)
