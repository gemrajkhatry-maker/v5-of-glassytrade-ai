"""Stats endpoint must derive from the paper journal's completed trades."""

from __future__ import annotations

from app.application.services.trade_journal import TradeJournal
from app.application.services.trading_query_service import TradingQueryService


def _seed_journal(tmp_path) -> TradeJournal:
    journal = TradeJournal(log_dir=str(tmp_path))
    journal.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=104.0,
        exit_reason="TP",
        pnl=4.0,
    )
    journal.log_entry(
        symbol="BANKNIFTY",
        position_id="P2",
        side="LONG",
        entry_price=200.0,
        stop_loss=190.0,
        take_profit=220.0,
    )
    journal.log_exit(
        symbol="BANKNIFTY",
        position_id="P2",
        side="LONG",
        entry_price=200.0,
        exit_price=196.0,
        exit_reason="SL",
        pnl=-4.0,
    )
    return journal


def test_stats_derived_from_journal_completed_trades(tmp_path):
    journal = _seed_journal(tmp_path)
    stats = TradingQueryService().build_stats_from_journal(journal, source="AMT")

    assert stats["totalTrades"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["winRate"] == 50.0
    assert stats["netProfit"] == 0.0
    assert stats["avgProfit"] == 0.0
    assert stats["largestWin"] == 4.0
    assert stats["largestLoss"] == -4.0


def test_stats_from_journal_matches_portfolio_semantics(tmp_path):
    journal = _seed_journal(tmp_path)
    stats = TradingQueryService().build_stats_from_journal(journal, source="AMT")

    pnls = [4.0, -4.0]
    assert stats["totalTrades"] == len(pnls)
    assert stats["netProfit"] == sum(pnls)
    assert stats["largestWin"] == max(pnls)
    assert stats["largestLoss"] == min(pnls)
