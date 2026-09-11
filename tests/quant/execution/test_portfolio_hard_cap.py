"""Hard 50% equity cap on aggregate open notional (Task 4).

The existing 25% open-risk ceiling stays untouched; this is an additional
outer bound: aggregate open notional may never exceed 0.5 * starting equity.
"""

from quant.execution.portfolio_risk import PortfolioRiskAuthority


def _authority() -> PortfolioRiskAuthority:
    # Raise the inner risk ceiling so ONLY the hard 50% notional cap binds.
    return PortfolioRiskAuthority(
        starting_equity=1_000_000.0, max_portfolio_risk_pct=1.0
    )


def test_hard_equity_cap_blocks_second_position():
    pra = _authority()
    # Simulate open notional tracking via realized open-risk API surface:
    # use notional = entry * qty passed as risk proxy at 1:1 for this test.
    ok, _ = pra.can_accept(risk_rupees=400_000.0, symbol="NIFTY 26000 CE")
    assert ok is True
    pra.register_open(risk_rupees=400_000.0, symbol="NIFTY 26000 CE")
    ok2, reason = pra.can_accept(risk_rupees=200_000.0, symbol="BANKNIFTY 58000 CE")
    assert ok2 is False
    assert "50%" in reason or "hard" in reason.lower()


def test_hard_equity_cap_releases_on_close():
    pra = _authority()
    assert pra.register_open(risk_rupees=400_000.0, symbol="NIFTY 26000 CE") is True
    pra.record_close(
        risk_rupees=400_000.0, pnl=0.0, symbol="NIFTY 26000 CE", is_full_close=True
    )
    ok, _ = pra.can_accept(risk_rupees=200_000.0, symbol="BANKNIFTY 58000 CE")
    assert ok is True
