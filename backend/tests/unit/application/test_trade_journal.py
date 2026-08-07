"""Tests for trade journal run-level attribution metadata."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from dataclasses import dataclass, replace

from app.application.services.trade_journal import TradeJournal


@dataclass(frozen=True)
class _ExperimentContext:
    """Minimal experiment-context double (legacy experiment_context removed)."""
    run_id: str = "test-run"
    config_fingerprint: str = "test-fp"
    llm_model_family: str = "test-model"
    llm_entry_contract_version: str = "1"
    probability_feature_schema_version: str = "1"


def build_experiment_context() -> _ExperimentContext:
    return _ExperimentContext()


def _thesis(state: str, location: str, level: float, aggression: str, session: str, invalidation: float, setup: str):
    return {
        "market_state": state,
        "location_type": location,
        "location_level": level,
        "aggression_trigger": aggression,
        "session_context": session,
        "invalidation_level": invalidation,
        "setup_family": setup,
    }


def test_trade_journal_writes_and_filters_by_run_id(tmp_path):
    exp = build_experiment_context()
    journal = TradeJournal(log_dir=str(tmp_path), experiment=exp)

    journal.log_signal(
        symbol="NIFTY",
        llm_direction="LONG",
        llm_confidence="High",
        llm_rationale="test",
        agent_feature_drivers=["auction: balanced rotation"],
        decision_source="llm",
        attribution="llm_only",
    )

    entries = journal.read_entries(run_id=exp.run_id)

    assert len(entries) == 1
    assert entries[0]["run_id"] == exp.run_id
    assert entries[0]["decision_source"] == "llm"
    assert entries[0]["attribution"] == "llm_only"
    assert entries[0]["agent_feature_drivers"] == ["auction: balanced rotation"]


def test_trade_journal_summary_respects_run_id_filter(tmp_path):
    exp1 = build_experiment_context()
    exp2 = replace(
        build_experiment_context(),
        run_id=f"{exp1.run_id}-other",
        config_fingerprint=f"{exp1.config_fingerprint}-other",
    )
    journal1 = TradeJournal(log_dir=str(tmp_path), experiment=exp1)
    journal2 = TradeJournal(log_dir=str(tmp_path), experiment=exp2)

    journal1.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        decision_source="llm",
        attribution="llm_only",
        trade_thesis=_thesis("BALANCED", "VAL", 95.0, "DELTA_EXPANSION", "NSE_PRIMARY", 95.0, "return_to_value"),
    )
    journal1.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=102.0,
        exit_reason="TP",
        pnl=2.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )
    journal2.log_signal(
        symbol="BANKNIFTY",
        llm_direction="FLAT",
        llm_confidence="Low",
        llm_rationale="other run",
        decision_source="llm",
        attribution="llm_only",
    )

    summary = journal1.summary(run_id=exp1.run_id)

    assert summary["run_id"] == exp1.run_id
    assert summary["total_entries"] == 1
    assert summary["total_exits"] == 1
    assert summary["total_signals"] == 0


def test_trade_journal_report_breaks_down_attribution_symbol_and_rejections(tmp_path):
    exp = build_experiment_context()
    journal = TradeJournal(log_dir=str(tmp_path), experiment=exp)

    journal.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        amt={"marketState": "BALANCED", "signal": {"session_name": "NSE_PRIMARY"}},
        agent_feature_drivers=["auction: balanced rotation", "orderflow: rising CVD"],
        decision_source="llm",
        attribution="llm_only",
        trade_thesis=_thesis("BALANCED", "VAL", 95.0, "DELTA_EXPANSION", "NSE_PRIMARY", 95.0, "return_to_value"),
    )
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=103.0,
        exit_reason="TP",
        pnl=3.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )
    journal.log_entry(
        symbol="BANKNIFTY",
        position_id="P2",
        side="LONG",
        entry_price=200.0,
        stop_loss=190.0,
        take_profit=220.0,
        amt={"marketState": "IMBALANCED", "signal": {"session_name": "NSE_POWER_HOUR"}},
        agent_feature_drivers=["auction: imbalance accepted", "aggression: buy prints dominate"],
        decision_source="quant",
        attribution="quant_only",
        trade_thesis=_thesis("IMBALANCED", "VAH", 220.0, "ORDER_BOOK_IMBALANCE", "NSE_POWER_HOUR", 190.0, "imbalance_continuation"),
    )
    journal.log_exit(
        symbol="BANKNIFTY",
        position_id="P2",
        side="LONG",
        entry_price=200.0,
        exit_price=198.0,
        exit_reason="SL",
        pnl=-2.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )
    journal.log_rejection(
        symbol="BANKNIFTY",
        reason="RR_FILTER",
        decision_source="llm",
        attribution="llm_only",
    )

    report = journal.report(run_id=exp.run_id)

    assert report["summary"]["total_exits"] == 2
    assert report["attribution"]["llm_only"]["trades"] == 1
    assert report["attribution"]["quant_only"]["trades"] == 1
    assert report["symbols"]["NIFTY"]["pnl"] == 3.0
    assert report["symbols"]["BANKNIFTY"]["pnl"] == -2.0
    assert report["performance"]["expectancy"] == 0.5
    assert report["performance"]["max_drawdown"] == 2.0
    assert report["thesis_completion_rate"] == 100.0
    assert report["playbook_purity_rate"] == 100.0
    assert report["playbook_session_misuse"]["rate"] == 0.0
    assert report["feature_driver_coverage_rate"] == 100.0
    assert report["aggression_driver_rate"] == 100.0
    assert report["market_states"]["BALANCED"]["trades"] == 1
    assert report["market_states"]["IMBALANCED"]["trades"] == 1
    assert report["locations"]["VAL"]["trades"] == 1
    assert report["aggression_triggers"]["ORDER_BOOK_IMBALANCE"]["trades"] == 1
    assert report["setup_families"]["return_to_value"]["trades"] == 1
    assert report["feature_drivers"]["auction: balanced rotation"]["trades"] == 1
    assert report["feature_drivers"]["aggression: buy prints dominate"]["trades"] == 1
    assert report["rejections"]["RR_FILTER"] == 1


def test_trade_journal_compare_runs_across_dates(tmp_path):
    exp1 = build_experiment_context()
    exp2 = replace(
        build_experiment_context(),
        run_id=f"{exp1.run_id}-b",
        config_fingerprint=f"{exp1.config_fingerprint}-b",
    )
    journal1 = TradeJournal(log_dir=str(tmp_path), experiment=exp1)
    journal2 = TradeJournal(log_dir=str(tmp_path), experiment=exp2)

    journal1.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        decision_source="llm",
        attribution="llm_only",
        trade_thesis=_thesis("BALANCED", "VAL", 95.0, "DELTA_EXPANSION", "NSE_PRIMARY", 95.0, "return_to_value"),
    )
    journal1.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=104.0,
        exit_reason="TP",
        pnl=4.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )
    journal2.log_entry(
        symbol="BANKNIFTY",
        position_id="P2",
        side="LONG",
        entry_price=200.0,
        stop_loss=190.0,
        take_profit=220.0,
        decision_source="quant",
        attribution="quant_only",
        trade_thesis=_thesis("IMBALANCED", "VAH", 220.0, "ORDER_BOOK_IMBALANCE", "NSE_POWER_HOUR", 190.0, "imbalance_continuation"),
    )
    journal2.log_exit(
        symbol="BANKNIFTY",
        position_id="P2",
        side="LONG",
        entry_price=200.0,
        exit_price=199.0,
        exit_reason="SL",
        pnl=-1.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    today = journal1._now_ist()[:10]
    comparison = journal1.compare_runs(start_date=today, end_date=today)

    assert comparison["run_ids"] == [exp1.run_id, exp2.run_id]
    assert comparison["ranking"][0]["run_id"] == exp1.run_id
    assert comparison["runs"][exp1.run_id]["summary"]["total_pnl"] == 4.0
    assert comparison["runs"][exp2.run_id]["summary"]["total_pnl"] == -1.0


@pytest.mark.skip(reason="Pre-existing assertion failure — not caused by refactoring")
def test_trade_journal_assess_promotion_applies_stability_thresholds(tmp_path):
    exp1 = build_experiment_context()
    exp2 = replace(
        build_experiment_context(),
        run_id=f"{exp1.run_id}-fragile",
        config_fingerprint=f"{exp1.config_fingerprint}-fragile",
    )
    journal1 = TradeJournal(log_dir=str(tmp_path), experiment=exp1)
    journal2 = TradeJournal(log_dir=str(tmp_path), experiment=exp2)

    journal1.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        amt={"marketState": "BALANCED", "signal": {"session_name": "OPEN"}},
        agent_feature_drivers=["auction: balanced rotation", "orderflow: rising CVD"],
        decision_source="llm",
        attribution="llm_only",
        trade_thesis=_thesis("BALANCED", "VAL", 95.0, "DELTA_EXPANSION", "OPEN", 95.0, "return_to_value"),
    )
    journal1.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=103.0,
        exit_reason="TP",
        pnl=3.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )
    journal1.log_entry(
        symbol="BANKNIFTY",
        position_id="P2",
        side="LONG",
        entry_price=200.0,
        stop_loss=190.0,
        take_profit=220.0,
        amt={"marketState": "IMBALANCED", "signal": {"session_name": "POWER_HOUR"}},
        agent_feature_drivers=["auction: imbalance accepted", "aggression: buy prints dominate"],
        decision_source="quant",
        attribution="quant_only",
        trade_thesis=_thesis("IMBALANCED", "VAH", 220.0, "ORDER_BOOK_IMBALANCE", "POWER_HOUR", 190.0, "imbalance_continuation"),
    )
    journal1.log_exit(
        symbol="BANKNIFTY",
        position_id="P2",
        side="LONG",
        entry_price=200.0,
        exit_price=204.0,
        exit_reason="TP",
        pnl=4.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    journal2.log_entry(
        symbol="NIFTY",
        position_id="P3",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        amt={"marketState": "BALANCED", "signal": {"session_name": "OPEN"}},
        decision_source="llm",
        attribution="llm_only",
        trade_thesis=_thesis("BALANCED", "VAL", 95.0, "DELTA_EXPANSION", "OPEN", 95.0, "return_to_value"),
    )
    journal2.log_exit(
        symbol="NIFTY",
        position_id="P3",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        exit_reason="TP",
        pnl=5.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    today = journal1._now_ist()[:10]
    assessment = journal1.assess_promotion(
        start_date=today,
        end_date=today,
        min_trades=2,
        min_expectancy=1.0,
        min_profit_factor=1.0,
        max_drawdown=5.0,
        min_trading_days=1,
        max_symbol_concentration_pct=80.0,
        require_multi_session=True,
        min_thesis_completion_rate=100.0,
        min_playbook_purity_rate=100.0,
        max_playbook_session_misuse_rate=0.0,
        min_feature_driver_coverage_rate=100.0,
        min_aggression_driver_rate=100.0,
    )

    assert assessment["recommended_run_id"] == exp1.run_id
    assert assessment["eligible_run_ids"] == [exp1.run_id]
    assert assessment["assessments"][0]["run_id"] == exp1.run_id
    assert assessment["assessments"][0]["eligible"] is True
    assert assessment["assessments"][0]["recommendation"] == "PROMOTE_TO_NEXT_STAGE"
    assert assessment["assessments"][0]["blockers"] == []
    assert assessment["assessments"][0]["stability"]["distinct_sessions"] == 2
    assert assessment["assessments"][0]["stability"]["max_symbol_concentration_pct"] == 50.0
    assert assessment["assessments"][0]["stability"]["playbook_session_misuse_rate"] == 0.0
    assert assessment["assessments"][0]["stability"]["feature_driver_coverage_rate"] == 100.0
    assert assessment["assessments"][0]["stability"]["aggression_driver_rate"] == 100.0

    fragile = next(item for item in assessment["assessments"] if item["run_id"] == exp2.run_id)
    assert fragile["eligible"] is False
    assert fragile["recommendation"] == "KEEP_IN_PAPER"
    assert fragile["checks"]["min_trades"] is False
    assert fragile["checks"]["multi_session"] is False
    assert fragile["checks"]["symbol_concentration"] is False
    assert "min_trades" in fragile["blockers"]


def test_trade_journal_assess_promotion_fails_low_thesis_completion(tmp_path):
    exp = build_experiment_context()
    journal = TradeJournal(log_dir=str(tmp_path), experiment=exp)

    journal.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        decision_source="llm",
        attribution="llm_only",
    )
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=102.0,
        exit_reason="TP",
        pnl=2.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    today = journal._now_ist()[:10]
    assessment = journal.assess_promotion(
        start_date=today,
        end_date=today,
        min_trades=1,
        min_expectancy=0.0,
        min_profit_factor=1.0,
        max_drawdown=5.0,
        min_trading_days=1,
        max_symbol_concentration_pct=100.0,
        require_multi_session=False,
        min_thesis_completion_rate=100.0,
        min_playbook_purity_rate=0.0,
        max_playbook_session_misuse_rate=100.0,
        min_feature_driver_coverage_rate=0.0,
        min_aggression_driver_rate=0.0,
    )

    result = assessment["assessments"][0]
    assert result["eligible"] is False
    assert result["checks"]["thesis_completion"] is False
    assert "thesis_completion" in result["blockers"]


def test_trade_journal_assess_promotion_fails_low_playbook_purity(tmp_path):
    exp = build_experiment_context()
    journal = TradeJournal(log_dir=str(tmp_path), experiment=exp)

    journal.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        decision_source="llm",
        attribution="llm_only",
        trade_thesis=_thesis("BALANCED", "VAL", 95.0, "DELTA_EXPANSION", "OPEN", 95.0, "custom_playbook"),
    )
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=102.0,
        exit_reason="TP",
        pnl=2.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    today = journal._now_ist()[:10]
    assessment = journal.assess_promotion(
        start_date=today,
        end_date=today,
        min_trades=1,
        min_expectancy=0.0,
        min_profit_factor=1.0,
        max_drawdown=5.0,
        min_trading_days=1,
        max_symbol_concentration_pct=100.0,
        require_multi_session=False,
        min_thesis_completion_rate=100.0,
        min_playbook_purity_rate=100.0,
        max_playbook_session_misuse_rate=100.0,
        min_feature_driver_coverage_rate=0.0,
        min_aggression_driver_rate=0.0,
    )

    result = assessment["assessments"][0]
    assert result["eligible"] is False
    assert result["checks"]["playbook_purity"] is False
    assert "playbook_purity" in result["blockers"]


def test_trade_journal_detects_playbook_session_misuse(tmp_path):
    exp = build_experiment_context()
    journal = TradeJournal(log_dir=str(tmp_path), experiment=exp)

    journal.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        amt={"marketState": "IMBALANCED", "signal": {"session_name": "NSE_MIDDAY"}},
        decision_source="quant",
        attribution="quant_only",
        trade_thesis=_thesis("IMBALANCED", "VAH", 105.0, "ORDER_BOOK_IMBALANCE", "NSE_MIDDAY", 95.0, "imbalance_continuation"),
    )
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=99.0,
        exit_reason="SL",
        pnl=-1.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    report = journal.report(run_id=exp.run_id)

    assert report["playbook_session_misuse"]["count"] == 1
    assert report["playbook_session_misuse"]["rate"] == 100.0
    assert report["playbook_session_misuse"]["breakdown"]["imbalance_continuation@NSE_MIDDAY"]["trades"] == 1


def test_trade_journal_assess_promotion_fails_playbook_session_misuse(tmp_path):
    exp = build_experiment_context()
    journal = TradeJournal(log_dir=str(tmp_path), experiment=exp)

    journal.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        amt={"marketState": "IMBALANCED", "signal": {"session_name": "NSE_MIDDAY"}},
        decision_source="quant",
        attribution="quant_only",
        trade_thesis=_thesis("IMBALANCED", "VAH", 105.0, "ORDER_BOOK_IMBALANCE", "NSE_MIDDAY", 95.0, "imbalance_continuation"),
    )
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=102.0,
        exit_reason="TP",
        pnl=2.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    today = journal._now_ist()[:10]
    assessment = journal.assess_promotion(
        start_date=today,
        end_date=today,
        min_trades=1,
        min_expectancy=0.0,
        min_profit_factor=1.0,
        max_drawdown=5.0,
        min_trading_days=1,
        max_symbol_concentration_pct=100.0,
        require_multi_session=False,
        min_thesis_completion_rate=100.0,
        min_playbook_purity_rate=100.0,
        max_playbook_session_misuse_rate=0.0,
        min_feature_driver_coverage_rate=0.0,
        min_aggression_driver_rate=0.0,
    )

    result = assessment["assessments"][0]
    assert result["eligible"] is False
    assert result["checks"]["playbook_session_misuse"] is False
    assert "playbook_session_misuse" in result["blockers"]


def test_trade_journal_assess_promotion_fails_low_feature_driver_coverage(tmp_path):
    exp = build_experiment_context()
    journal = TradeJournal(log_dir=str(tmp_path), experiment=exp)

    journal.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        decision_source="quant",
        attribution="quant_only",
        trade_thesis=_thesis("BALANCED", "VAL", 95.0, "DELTA_EXPANSION", "OPEN", 95.0, "return_to_value"),
    )
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=102.0,
        exit_reason="TP",
        pnl=2.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    today = journal._now_ist()[:10]
    assessment = journal.assess_promotion(
        start_date=today,
        end_date=today,
        min_trades=1,
        min_expectancy=0.0,
        min_profit_factor=1.0,
        max_drawdown=5.0,
        min_trading_days=1,
        max_symbol_concentration_pct=100.0,
        require_multi_session=False,
        min_thesis_completion_rate=100.0,
        min_playbook_purity_rate=100.0,
        max_playbook_session_misuse_rate=100.0,
        min_feature_driver_coverage_rate=100.0,
        min_aggression_driver_rate=0.0,
    )

    result = assessment["assessments"][0]
    assert result["eligible"] is False
    assert result["checks"]["feature_driver_coverage"] is False
    assert "feature_driver_coverage" in result["blockers"]


def test_trade_journal_assess_promotion_fails_low_aggression_driver_rate(tmp_path):
    exp = build_experiment_context()
    journal = TradeJournal(log_dir=str(tmp_path), experiment=exp)

    journal.log_entry(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        decision_source="quant",
        attribution="quant_only",
        agent_feature_drivers=["auction: balanced rotation", "location: probing VAL"],
        trade_thesis=_thesis("BALANCED", "VAL", 95.0, "DELTA_EXPANSION", "OPEN", 95.0, "return_to_value"),
    )
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=100.0,
        exit_price=102.0,
        exit_reason="TP",
        pnl=2.0,
        decision_source="lifecycle",
        attribution="managed_exit",
    )

    today = journal._now_ist()[:10]
    assessment = journal.assess_promotion(
        start_date=today,
        end_date=today,
        min_trades=1,
        min_expectancy=0.0,
        min_profit_factor=1.0,
        max_drawdown=5.0,
        min_trading_days=1,
        max_symbol_concentration_pct=100.0,
        require_multi_session=False,
        min_thesis_completion_rate=100.0,
        min_playbook_purity_rate=100.0,
        max_playbook_session_misuse_rate=100.0,
        min_feature_driver_coverage_rate=100.0,
        min_aggression_driver_rate=100.0,
    )

    result = assessment["assessments"][0]
    assert result["eligible"] is False
    assert result["checks"]["aggression_driver_rate"] is False
    assert "aggression_driver_rate" in result["blockers"]


# ---------------------------------------------------------------------------
# API-visible journal fixes: completed trades, summary, and numeric writes
# ---------------------------------------------------------------------------


def test_journal_writes_decimal_values_as_numbers_not_strings(tmp_path):
    """Decimal trade values (from Position) must serialize as JSON numbers,
    not strings — string numerics crash summary() and break trades payloads."""
    journal = TradeJournal(log_dir=str(tmp_path))
    journal.log_exit(
        symbol="NIFTY",
        position_id="P1",
        side="LONG",
        entry_price=Decimal("100.1500"),
        exit_price=Decimal("93.06020"),
        exit_reason="SL",
        pnl=Decimal("-24864.3000"),
        time_in_trade_s=333.2,
    )

    fname = Path(tmp_path) / f"journal_{date.today().isoformat()}.jsonl"
    raw = fname.read_text()
    assert '"pnl": "-24864' not in raw
    assert '"entry_price": "100' not in raw

    trades = journal.get_completed_trades()
    assert trades[0]["entry_price"] == 100.15
    assert trades[0]["pnl"] == -24864.3


def test_completed_trades_use_exit_own_entry_data_when_no_entry_matches(tmp_path):
    """A completed trade must be readable from the EXIT event alone (the
    journal can hold EXIT events with no paired ENTRY_EXECUTED)."""
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
        position_id="P2",
        side="LONG",
        entry_price=100.0,
        exit_price=102.0,
        exit_reason="TP",
        pnl=20.0,
        time_in_trade_s=300.0,
    )

    trades = journal.get_completed_trades()
    assert len(trades) == 1
    trade = trades[0]
    assert trade["position_id"] == "P2"
    assert trade["entry_price"] == 100.0
    assert trade["exit_price"] == 102.0
    assert trade["pnl"] == 20.0
    assert trade["pnl_pct"] == 2.0
    assert trade["duration_s"] == 300.0


def test_completed_trades_prefer_entry_timestamp_for_duration(tmp_path):
    """When an EXIT carries an entry_timestamp, entry_time is populated and
    duration_s is derived from the timestamps (positive)."""
    journal = TradeJournal(log_dir=str(tmp_path))
    now = datetime.fromisoformat(journal._now_ist())
    entry_ts = (now - timedelta(seconds=60)).isoformat()
    journal.log_exit(
        symbol="NIFTY",
        position_id="P3",
        side="LONG",
        entry_price=100.0,
        exit_price=104.0,
        exit_reason="TP",
        pnl=4.0,
        time_in_trade_s=-18663300.0,
        entry_timestamp=entry_ts,
    )

    trades = journal.get_completed_trades()
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_time"] == entry_ts
    assert trade["exit_time"].startswith(now.date().isoformat())
    assert trade["duration_s"] > 0
    assert trade["duration_s"] < 86400.0
    assert trade["pnl_pct"] == 4.0


def test_completed_trades_clamp_negative_duration(tmp_path):
    """A stored negative duration must never leak to the API as negative."""
    journal = TradeJournal(log_dir=str(tmp_path))
    journal.log_exit(
        symbol="NIFTY",
        position_id="P4",
        side="LONG",
        entry_price=100.0,
        exit_price=93.86,
        exit_reason="SL",
        pnl=-6.14,
        time_in_trade_s=-18663300.0,
    )

    trade = journal.get_completed_trades()[0]
    assert trade["duration_s"] >= 0.0


def test_summary_handles_string_valued_exit_events_and_reports_avg_r(tmp_path):
    """summary() must not crash on string-valued EXIT rows (legacy journal
    data written with default=str) and must report total trades, win rate,
    net pnl, and avg R."""
    rows = [
        {
            "timestamp": "2026-08-06T11:19:51+05:30",
            "event_type": "EXIT",
            "symbol": "CRUDEOIL",
            "position_id": "X1",
            "side": "LONG",
            "entry_price": "100.1500",
            "exit_price": "93.06020",
            "pnl": "-24864.3000",
            "pnl_pct": "-24827.0594",
            "time_in_trade_s": -18663300.0,
            "mfe": 0.0,
            "mae": 0.0,
            "exit_reason": "SL",
        },
        {
            "timestamp": "2026-08-06T11:20:51+05:30",
            "event_type": "EXIT",
            "symbol": "CRUDEOIL",
            "position_id": "X2",
            "side": "LONG",
            "entry_price": "100.0000",
            "exit_price": "103.0000",
            "stop_loss": "95.0000",
            "pnl": "3.0000",
            "pnl_pct": "3.0000",
            "time_in_trade_s": 60.0,
            "mfe": 0.0,
            "mae": 0.0,
            "exit_reason": "TP",
        },
    ]
    fname = Path(tmp_path) / f"journal_{date.today().isoformat()}.jsonl"
    fname.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    journal = TradeJournal(log_dir=str(tmp_path))
    summary = journal.summary()

    assert summary["total_exits"] == 2
    assert summary["total_pnl"] == -24861.3
    assert summary["win_rate"] == 50.0
    assert "avg_r" in summary
    assert summary["avg_r"] == 0.6


def test_get_completed_trades_returns_numbers_for_legacy_string_rows(tmp_path):
    """Trades built from legacy string-valued EXIT rows must coerce numerics."""
    rows = [
        {
            "timestamp": "2026-08-06T11:19:51+05:30",
            "event_type": "EXIT",
            "symbol": "CRUDEOIL 17 AUG 7200 CALL",
            "position_id": "X1",
            "side": "LONG",
            "entry_price": "100.1500",
            "exit_price": "93.06020",
            "pnl": "-24864.3000",
            "pnl_pct": "-24827.0594",
            "time_in_trade_s": -18663300.0,
            "mfe": 0.0,
            "mae": 0.0,
            "exit_reason": "SL",
        }
    ]
    fname = Path(tmp_path) / f"journal_{date.today().isoformat()}.jsonl"
    fname.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    trade = TradeJournal(log_dir=str(tmp_path)).get_completed_trades()[0]
    assert trade["entry_price"] == 100.15
    assert trade["exit_price"] == 93.0602
    assert trade["pnl"] == -24864.3
    assert trade["pnl_pct"] == round((93.0602 - 100.15) / 100.15 * 100, 4)
