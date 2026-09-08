"""Certification for independent correlation budgets."""

from quant.execution.portfolio_risk import PortfolioRiskAuthority


def test_same_root_execution_locks_are_independent_but_budget_is_shared():
    risk = PortfolioRiskAuthority(
        starting_equity=100_000,
        max_portfolio_risk_pct=1.0,
        max_root_risk_pct=0.10,
        separate_by="symbol",
    )
    assert risk.register_open(6_000, "NIFTY SEP FUT")
    assert risk.register_open(3_000, "NIFTY 30 SEP 25000 CE")
    assert risk.root_open_risk("NIFTY SEP FUT") == 9_000
    assert not risk.can_accept(2_000, "NIFTY 30 SEP 25100 CE")[0]
    risk.record_close(6_000, 0, symbol="NIFTY SEP FUT", is_full_close=True)
    assert risk.root_open_risk("NIFTY") == 3_000


def test_exchange_budget_is_separate_from_symbol_lock():
    risk = PortfolioRiskAuthority(
        starting_equity=100_000,
        max_portfolio_risk_pct=1.0,
        max_exchange_risk_pct=0.05,
        separate_by="symbol",
    )
    assert risk.register_open(4_000, "NIFTY SEP FUT")
    assert not risk.register_open(2_000, "BANKNIFTY SEP FUT")
    assert risk.register_open(4_000, "CRUDEOIL SEP FUT")
