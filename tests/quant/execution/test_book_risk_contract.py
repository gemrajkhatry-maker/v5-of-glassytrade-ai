"""Stage 5 contract: HMP sizing default; book-only -2% halt; bar-cycle ranking."""

from __future__ import annotations

from quant.execution.opportunity_auction import (
    OpportunityAuction,
    OpportunityProposal,
    score_opportunity,
)
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.execution.risk import SessionRisk


def test_default_sizing_uses_house_money_not_deployment_fraction():
    risk = SessionRisk(starting_equity=100_000.0, base_risk_pct=0.05)
    # Conservative HMP: 0.25% of 100k = ₹250 / 10pt stop = 25 units.
    qty = risk.position_size(entry=100.0, sl=90.0, lot_size=1.0)
    assert qty == 25.0
    # Must not be the old 50%-deployment branch (~500 units on cash).
    assert qty < 100.0


def test_per_engine_loss_does_not_halt_flat_sibling_when_book_ok():
    book = PortfolioRiskAuthority(starting_equity=100_000.0, max_portfolio_daily_loss_pct=0.02)
    a = SessionRisk(
        starting_equity=100_000.0, base_risk_pct=0.01, portfolio_risk=book, symbol="A",
    )
    b = SessionRisk(
        starting_equity=100_000.0, base_risk_pct=0.01, portfolio_risk=book, symbol="B",
    )
    a.record_trade(-2_000.0)
    can_b, _ = b.can_trade()
    assert can_b is True
    ok, _ = book.can_accept(100.0, symbol="B")
    assert ok is True


def test_bar_cycle_auction_ranks_higher_score_first():
    book = PortfolioRiskAuthority(starting_equity=100_000.0, max_portfolio_risk_pct=0.25)
    auction = OpportunityAuction(book)
    weak = OpportunityProposal(
        symbol="WEAK", side="LONG", score=40.0, requested_risk_rupees=10_000.0,
        signal=object(), quantity=1.0, reason="LVN_SNIPER",
    )
    strong = OpportunityProposal(
        symbol="STRONG", side="LONG", score=95.0, requested_risk_rupees=10_000.0,
        signal=object(), quantity=1.0, reason="TRIPLE_A",
    )
    auction.submit(weak)
    auction.submit(strong)
    grants = auction.settle_bar()
    assert grants and grants[0].symbol == "STRONG"
    assert score_opportunity(setup_key="TRIPLE_A", rr=2.0) > score_opportunity(
        setup_key="VA_FADE", rr=2.0,
    )


def test_auction_propose_settles_when_multiple_pending():
    """Leaving orphans on len>1 starved later submits — always settle."""
    book = PortfolioRiskAuthority(starting_equity=100_000.0, max_portfolio_risk_pct=0.25)
    auction = OpportunityAuction(book)
    weak = OpportunityProposal(
        symbol="WEAK", side="LONG", score=40.0, requested_risk_rupees=5_000.0,
        signal=object(), quantity=1.0, reason="LVN_SNIPER",
    )
    strong = OpportunityProposal(
        symbol="STRONG", side="LONG", score=95.0, requested_risk_rupees=5_000.0,
        signal=object(), quantity=1.0, reason="TRIPLE_A",
    )
    auction.submit(weak)
    ok, why = auction.propose(strong)
    assert ok is True
    assert why == "granted"


def test_score_opportunity_uses_quality_features():
    plain = score_opportunity(setup_key="TRIPLE_A", rr=2.0)
    rich = score_opportunity(
        setup_key="TRIPLE_A",
        rr=2.0,
        absorption_vol_ratio=2.0,
        drive_entry_valid=True,
        cvd_agrees=True,
        lvn_ticks=1.0,
        spread_quality=1.0,
    )
    assert rich > plain


def test_hold_window_ranks_higher_score_before_settle():
    """With hold_sec > 0, a late higher-score submit still wins the grant."""
    import threading

    book = PortfolioRiskAuthority(starting_equity=100_000.0, max_portfolio_risk_pct=0.25)
    auction = OpportunityAuction(book, hold_sec=0.05)
    results: dict[str, tuple[bool, str]] = {}

    def _run(prop: OpportunityProposal) -> None:
        auction.submit(prop)
        results[prop.symbol] = auction.await_grant(prop.symbol)

    weak = OpportunityProposal(
        symbol="WEAK", side="LONG", score=40.0, requested_risk_rupees=20_000.0,
        signal=object(), quantity=1.0, reason="LVN_SNIPER",
    )
    strong = OpportunityProposal(
        symbol="STRONG", side="LONG", score=95.0, requested_risk_rupees=20_000.0,
        signal=object(), quantity=1.0, reason="TRIPLE_A",
    )
    t1 = threading.Thread(target=_run, args=(weak,))
    t1.start()
    # Join the window before settle — higher score must outrank first-come.
    import time
    time.sleep(0.01)
    t2 = threading.Thread(target=_run, args=(strong,))
    t2.start()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert results["STRONG"] == (True, "granted")
    assert results["WEAK"] == (False, "OUTRANKED")


def test_submission_handler_with_auction_approves_good_signal():
    """E2E P0-1: SubmissionHandler + OpportunityAuction reaches oms.submit."""
    from types import SimpleNamespace

    from quant.decision.signal_builder import Signal
    from quant.engine.submission_handler import SubmissionHandler

    book = PortfolioRiskAuthority(starting_equity=100_000.0, max_portfolio_risk_pct=0.25)
    auction = OpportunityAuction(book, hold_sec=0.0)
    submitted: list[tuple] = []

    class _OMS:
        is_live = False
        lot_size = 1.0
        last_fill = None

        def submit(self, signal, quantity):
            submitted.append((signal, quantity))
            return SimpleNamespace(id="p1", open_price=signal.entry, size=quantity)

    class _Risk:
        def position_size(self, *a, **k):
            return 1.0

        def state(self):
            return SimpleNamespace(
                trades_today=0, equity=100_000.0, daily_pnl=0.0,
                halted=False, consecutive_losses=0,
            )

    handler = SubmissionHandler(
        config={
            "symbol": "NIFTY FUT",
            "contract_expiry": None,
            "max_lots": None,
            "execution_model": None,
            "contract": None,
            "execution_enabled": True,
            "tick_size": 0.05,
        },
        deps={
            "risk": _Risk(),
            "oms": _OMS(),
            "get_portfolio_risk": lambda: book,
            "get_opportunity_auction": lambda: auction,
            "get_position_manager": lambda: SimpleNamespace(current_position=None),
            "forecast_fn": None,
        },
        state={
            "get_bar_index": lambda: 10,
            "get_entry_bar_index": lambda: 0,
            "set_entry_bar_index": lambda v: None,
            "get_latch": lambda: {},
            "set_latch": lambda k, v: None,
            "pop_latch": lambda k: None,
            "get_open_trade_risk": lambda: 0.0,
            "set_open_trade_risk": lambda v: None,
            "get_exposure_state": lambda: None,
            "set_exposure_state": lambda v: None,
            "set_entry_time_epoch": lambda v: None,
            "set_last_rejected_bar_index": lambda: None,
        },
        emit=lambda e: None,
        latch_or_signal_block=lambda *a: None,
        notify_advisor_position=lambda *a: None,
    )
    signal = Signal(
        type="LONG", reason="TRIPLE_A", entry=100.0, sl=99.0, tp=103.0,
        rr=3.0, model_label="TRIPLE_A", symbol="NIFTY FUT",
        timestamp="2026-01-15T10:00:00+05:30",
    )
    bar = SimpleNamespace(time="2026-01-15T10:00:00+05:30", close=100.0)
    risk_st = SimpleNamespace(
        trades_today=0, equity=100_000.0, daily_pnl=0.0,
        halted=False, consecutive_losses=0,
    )
    ok = handler.submit(
        signal, bar, {"absorptionVolRatio": 1.5, "cvdAgrees": True},
        risk_st, "TRIPLE_A",
    )
    assert ok is True
    assert len(submitted) == 1
    assert book.open_risk > 0.0
