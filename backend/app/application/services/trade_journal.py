"""Trade Journal — comprehensive JSONL logging of all trade decisions."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone, timedelta
from threading import Lock
from typing import Any
from app.shared.timezones import IST

logger = logging.getLogger(__name__)




@dataclass
class JournalEntry:
    timestamp: str = ""
    event_type: str = ""  # SIGNAL_GENERATED | ENTRY_EXECUTED | ENTRY_REJECTED | EXIT | OVERSEER_ACTION
    symbol: str = ""
    run_id: str = ""
    config_fingerprint: str = ""
    decision_source: str = ""
    attribution: str = ""
    llm_model_family: str = ""
    llm_entry_contract_version: str = ""
    probability_feature_schema_version: str = ""

    # Execution-grade trade thesis
    thesis_market_state: str = ""
    thesis_location_type: str = ""
    thesis_location_level: float = 0.0
    thesis_aggression_trigger: str = ""
    thesis_session_context: str = ""
    thesis_invalidation_level: float = 0.0
    thesis_setup_family: str = ""

    # Market conditions
    market_state: str = ""
    market_structure: str = ""
    structure_confidence: int = 0
    ltp: float = 0.0
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    delta: float = 0.0
    cvd_slope: float = 0.0
    cvd_divergence: str = ""
    profile_shape: str = ""
    session_name: str = ""

    # Model reasoning
    llm_direction: str = ""
    llm_confidence: str = ""
    llm_rationale: str = ""
    probability_long: float = 0.0
    probability_short: float = 0.0
    agent_direction: str = ""
    agent_regime: str = ""
    agent_feature_drivers: list[str] = field(default_factory=list)

    # Position info
    position_id: str = ""
    side: str = ""
    tick_trace_id: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    time_in_trade_s: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0
    tick_count: int = 0

    # Gate checks
    risk_check_passed: bool | None = None
    risk_reject_reason: str = ""


class TradeJournal:
    """Logs every trade decision to daily JSONL files for post-session analysis."""

    def __init__(self, log_dir: str = "live_trading_logs", experiment=None) -> None:
        os.makedirs(log_dir, exist_ok=True)
        self._log_dir = log_dir
        self._lock = Lock()
        self._experiment = experiment

    def _base_fields(self) -> dict[str, Any]:
        if not self._experiment:
            return {}
        return {
            "run_id": self._experiment.run_id,
            "config_fingerprint": self._experiment.config_fingerprint,
            "llm_model_family": self._experiment.llm_model_family,
            "llm_entry_contract_version": self._experiment.llm_entry_contract_version,
            "probability_feature_schema_version": self._experiment.probability_feature_schema_version,
        }

    @staticmethod
    def _safe_div(numerator: float, denominator: float) -> float:
        return numerator / denominator if denominator else 0.0

    def _performance_metrics(self, trades: list[dict]) -> dict[str, float]:
        pnls = [float(t.get("pnl", 0.0)) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        expectancy = self._safe_div(sum(pnls), len(pnls))

        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for pnl in pnls:
            equity += pnl
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        return {
            "expectancy": round(expectancy, 4),
            "profit_factor": round(self._safe_div(gross_profit, gross_loss), 4) if gross_loss else 0.0,
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
            "avg_win": round(self._safe_div(gross_profit, len(wins)), 4),
            "avg_loss": round(self._safe_div(sum(losses), len(losses)), 4),
            "max_drawdown": round(max_drawdown, 4),
        }

    def _bucket_trade_breakdown(self, trades: list[dict], key_name: str) -> dict[str, dict[str, float | int]]:
        buckets: dict[str, dict[str, float | int]] = {}
        for trade in trades:
            key = trade.get(key_name, "") or "UNKNOWN"
            bucket = buckets.setdefault(key, {"trades": 0, "wins": 0, "pnl": 0.0})
            pnl = float(trade.get("pnl", 0.0))
            bucket["trades"] += 1
            bucket["pnl"] += pnl
            if pnl > 0:
                bucket["wins"] += 1
        for bucket in buckets.values():
            trades_count = int(bucket["trades"])
            bucket["win_rate"] = round((bucket["wins"] / trades_count * 100), 1) if trades_count else 0.0
            bucket["pnl"] = round(float(bucket["pnl"]), 4)
        return buckets

    def _daily_trade_breakdown(self, trades: list[dict]) -> dict[str, dict[str, float | int]]:
        buckets: dict[str, dict[str, float | int]] = {}
        for trade in trades:
            exit_time = trade.get("exit_time", "")
            day = exit_time[:10] if exit_time else "UNKNOWN"
            bucket = buckets.setdefault(day, {"trades": 0, "wins": 0, "pnl": 0.0})
            pnl = float(trade.get("pnl", 0.0))
            bucket["trades"] += 1
            bucket["pnl"] += pnl
            if pnl > 0:
                bucket["wins"] += 1
        for bucket in buckets.values():
            trades_count = int(bucket["trades"])
            bucket["win_rate"] = round((bucket["wins"] / trades_count * 100), 1) if trades_count else 0.0
            bucket["pnl"] = round(float(bucket["pnl"]), 4)
        return buckets

    def _feature_driver_breakdown(self, trades: list[dict]) -> dict[str, dict[str, float | int]]:
        buckets: dict[str, dict[str, float | int]] = {}
        for trade in trades:
            drivers = trade.get("agent_feature_drivers") or []
            if not isinstance(drivers, list):
                continue
            pnl = float(trade.get("pnl", 0.0))
            for driver in drivers:
                key = str(driver or "").strip() or "UNKNOWN"
                bucket = buckets.setdefault(key, {"trades": 0, "wins": 0, "pnl": 0.0})
                bucket["trades"] += 1
                bucket["pnl"] += pnl
                if pnl > 0:
                    bucket["wins"] += 1
        for bucket in buckets.values():
            trades_count = int(bucket["trades"])
            bucket["win_rate"] = round((bucket["wins"] / trades_count * 100), 1) if trades_count else 0.0
            bucket["pnl"] = round(float(bucket["pnl"]), 4)
        return buckets

    @staticmethod
    def _has_feature_drivers(trade: dict) -> bool:
        drivers = trade.get("agent_feature_drivers") or []
        return isinstance(drivers, list) and any(str(driver or "").strip() for driver in drivers)

    @staticmethod
    def _has_aggression_driver(trade: dict) -> bool:
        drivers = trade.get("agent_feature_drivers") or []
        if not isinstance(drivers, list):
            return False
        return any(
            str(driver or "").startswith(("orderflow:", "aggression:", "liquidity:"))
            for driver in drivers
        )

    @staticmethod
    def _session_allows_playbook(session_name: str, playbook: str) -> bool:
        session = (session_name or "").upper()
        session = {
            "OPEN": "NSE_PRIMARY",
            "POWER_HOUR": "NSE_POWER_HOUR",
            "MIDDAY": "NSE_MIDDAY",
        }.get(session, session)
        if not playbook:
            return False
        if playbook == "return_to_value":
            return session not in {"NSE_OPENING", "NSE_CLOSE", "PRE_MARKET", "POST_MARKET", "MCX_CLOSE", "MCX_PRE_OPEN", "MCX_PRE_MARKET", "MCX_POST_MARKET"}
        if playbook == "imbalance_continuation":
            return session in {"NSE_PRIMARY", "NSE_POWER_HOUR", "MCX_MORNING", "MCX_AFTERNOON", "MCX_EVENING", "NEW_YORK", "OVERLAP"}
        return False

    def _playbook_session_misuse(self, trades: list[dict]) -> dict[str, Any]:
        misuse: dict[str, dict[str, float | int]] = {}
        misuse_count = 0
        for trade in trades:
            playbook = trade.get("thesis_setup_family", "") or "UNKNOWN"
            session_name = trade.get("session_name", "") or "UNKNOWN"
            if self._session_allows_playbook(session_name, playbook):
                continue
            misuse_count += 1
            key = f"{playbook}@{session_name}"
            bucket = misuse.setdefault(key, {"trades": 0, "pnl": 0.0})
            bucket["trades"] += 1
            bucket["pnl"] += float(trade.get("pnl", 0.0))
        for bucket in misuse.values():
            bucket["pnl"] = round(float(bucket["pnl"]), 4)
        misuse_rate = round(self._safe_div(misuse_count * 100.0, len(trades)), 1) if trades else 0.0
        return {
            "count": misuse_count,
            "rate": misuse_rate,
            "breakdown": misuse,
        }

    @staticmethod
    def _failed_check_names(checks: dict[str, bool]) -> list[str]:
        return [name for name, passed in checks.items() if not passed]

    def _now_ist(self) -> str:
        return datetime.now(IST).isoformat()

    def _market_fields(self, amt: dict | None) -> dict:
        """Extract market condition fields from AMT result dict.

        AMT DTO keys use camelCase (valueAreaHigh, valueAreaLow, etc.)
        while JournalEntry uses short names (vah, val, ltp, delta).
        """
        if not amt:
            return {}
        sig = amt.get("signal") or {}
        return {
            "market_state": amt.get("marketState", ""),
            "ltp": sig.get("price", 0.0),
            "poc": amt.get("poc", 0.0),
            "vah": amt.get("valueAreaHigh", 0.0),
            "val": amt.get("valueAreaLow", 0.0),
            "delta": sig.get("delta", 0.0),
            "cvd_slope": amt.get("cvdSlope", 0.0),
            "cvd_divergence": amt.get("cvdDivergence", ""),
            "profile_shape": amt.get("profileShape", ""),
            "session_name": amt.get("sessionName", sig.get("session_name", "")),
        }

    def _thesis_fields(self, trade_thesis: dict[str, Any] | None) -> dict[str, Any]:
        if not trade_thesis:
            return {}
        return {
            "thesis_market_state": trade_thesis.get("market_state", ""),
            "thesis_location_type": trade_thesis.get("location_type", ""),
            "thesis_location_level": trade_thesis.get("location_level", 0.0),
            "thesis_aggression_trigger": trade_thesis.get("aggression_trigger", ""),
            "thesis_session_context": trade_thesis.get("session_context", ""),
            "thesis_invalidation_level": trade_thesis.get("invalidation_level", 0.0),
            "thesis_setup_family": trade_thesis.get("setup_family", ""),
        }

    def log_signal(
        self,
        *,
        symbol: str,
        tick_trace_id: str = "",
        amt: dict | None = None,
        llm_direction: str = "",
        llm_confidence: str = "",
        llm_rationale: str = "",
        agent_direction: str = "",
        agent_regime: str = "",
        probability_long: float = 0.0,
        probability_short: float = 0.0,
        agent_feature_drivers: list[str] | tuple[str, ...] | None = None,
        decision_source: str = "",
        attribution: str = "",
        trade_thesis: dict[str, Any] | None = None,
    ) -> None:
        """Log when LLM produces a trade signal."""
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="SIGNAL_GENERATED",
            symbol=symbol,
            tick_trace_id=tick_trace_id,
            llm_direction=llm_direction,
            llm_confidence=llm_confidence,
            llm_rationale=llm_rationale,
            agent_direction=agent_direction,
            agent_regime=agent_regime,
            agent_feature_drivers=list(agent_feature_drivers or ()),
            probability_long=probability_long,
            probability_short=probability_short,
            decision_source=decision_source,
            attribution=attribution,
            **self._market_fields(amt),
            **self._thesis_fields(trade_thesis),
            **self._base_fields(),
        )
        self._write(entry)

    def log_entry(
        self,
        *,
        symbol: str,
        position_id: str,
        tick_trace_id: str = "",
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        amt: dict | None = None,
        agent_direction: str = "",
        agent_regime: str = "",
        probability_long: float = 0.0,
        probability_short: float = 0.0,
        agent_feature_drivers: list[str] | tuple[str, ...] | None = None,
        llm_direction: str = "",
        llm_rationale: str = "",
        decision_source: str = "",
        attribution: str = "",
        trade_thesis: dict[str, Any] | None = None,
    ) -> None:
        """Log when a position is successfully opened."""
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="ENTRY_EXECUTED",
            symbol=symbol,
            position_id=position_id,
            tick_trace_id=tick_trace_id,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            agent_direction=agent_direction,
            agent_regime=agent_regime,
            agent_feature_drivers=list(agent_feature_drivers or ()),
            probability_long=probability_long,
            probability_short=probability_short,
            llm_direction=llm_direction,
            llm_rationale=llm_rationale,
            decision_source=decision_source,
            attribution=attribution,
            **self._market_fields(amt),
            **self._thesis_fields(trade_thesis),
            **self._base_fields(),
        )
        self._write(entry)

    def log_rejection(
        self,
        *,
        symbol: str,
        reason: str,
        tick_trace_id: str = "",
        amt: dict | None = None,
        llm_direction: str = "",
        agent_direction: str = "",
        agent_regime: str = "",
        agent_feature_drivers: list[str] | tuple[str, ...] | None = None,
        decision_source: str = "",
        attribution: str = "",
        trade_thesis: dict[str, Any] | None = None,
    ) -> None:
        """Log when an entry signal is rejected (risk manager, gate, etc.)."""
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="ENTRY_REJECTED",
            symbol=symbol,
            tick_trace_id=tick_trace_id,
            llm_direction=llm_direction,
            agent_direction=agent_direction,
            agent_regime=agent_regime,
            agent_feature_drivers=list(agent_feature_drivers or ()),
            decision_source=decision_source,
            attribution=attribution,
            risk_check_passed=False,
            risk_reject_reason=reason,
            **self._market_fields(amt),
            **self._thesis_fields(trade_thesis),
            **self._base_fields(),
        )
        self._write(entry)

    def log_exit(
        self,
        *,
        symbol: str,
        position_id: str,
        tick_trace_id: str = "",
        side: str,
        entry_price: float,
        exit_price: float,
        exit_reason: str,
        pnl: float = 0.0,
        time_in_trade_s: float = 0.0,
        mfe: float = 0.0,
        mae: float = 0.0,
        tick_count: int = 0,
        amt: dict | None = None,
        decision_source: str = "",
        attribution: str = "",
    ) -> None:
        """Log when a position is closed."""
        pnl_pct = (pnl / entry_price * 100) if entry_price > 0 else 0.0
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="EXIT",
            symbol=symbol,
            position_id=position_id,
            tick_trace_id=tick_trace_id,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct, 4),
            time_in_trade_s=round(time_in_trade_s, 1),
            mfe=round(mfe, 4),
            mae=round(mae, 4),
            tick_count=tick_count,
            decision_source=decision_source,
            attribution=attribution,
            **self._market_fields(amt),
            **self._base_fields(),
        )
        self._write(entry)

    def log_partial_exit(
        self,
        *,
        symbol: str,
        position_id: str,
        tick_trace_id: str = "",
        side: str,
        entry_price: float,
        exit_price: float,
        partial_pct: float,
        size_closed: float,
        size_remaining: float,
        realized_pnl: float,
        amt: dict | None = None,
        decision_source: str = "",
        attribution: str = "",
    ) -> None:
        """Log a partial position close (e.g. 50% at TP1)."""
        pnl_pct = (realized_pnl / entry_price * 100) if entry_price > 0 else 0.0
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="PARTIAL_EXIT",
            symbol=symbol,
            position_id=position_id,
            tick_trace_id=tick_trace_id,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=f"PARTIAL_{partial_pct:.0%}",
            pnl=round(realized_pnl, 4),
            pnl_pct=round(pnl_pct, 4),
            decision_source=decision_source,
            attribution=attribution,
            **self._market_fields(amt),
            **self._base_fields(),
        )
        # Store size info in metadata-like fields
        entry.stop_loss = size_closed  # repurpose for CSV compat
        entry.take_profit = size_remaining
        self._write(entry)

    def log_overseer(
        self,
        *,
        symbol: str,
        position_id: str,
        action: str,
        reason: str,
        amt: dict | None = None,
        decision_source: str = "",
        attribution: str = "",
    ) -> None:
        """Log overseer actions (HOLD/TIGHTEN/PARTIAL/FULL_EXIT/ADD)."""
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="OVERSEER_ACTION",
            symbol=symbol,
            position_id=position_id,
            llm_rationale=reason,
            exit_reason=action,
            decision_source=decision_source,
            attribution=attribution,
            **self._market_fields(amt),
            **self._base_fields(),
        )
        self._write(entry)

    def log_break_even_move(
        self,
        *,
        symbol: str,
        position_id: str,
        side: str,
        tick_trace_id: str = "",
        entry_price: float,
        stop_loss: float,
        pnl: float = 0.0,
        time_in_trade_s: float = 0.0,
        amt: dict | None = None,
        reason: str = "",
    ) -> None:
        """Log a breakeven move lifecycle event.

        Args:
            symbol: Trading symbol
            position_id: Position identifier
            side: Position side
            entry_price: Entry price
            stop_loss: Updated breakeven stop level
            pnl: Unrealized or latest realized PnL at move time
            time_in_trade_s: Time in trade when move happened
            amt: AMT snapshot (optional)
            reason: Human-readable rationale
        """
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="BREAK_EVEN_TRIGGERED",
            symbol=symbol,
            position_id=position_id,
            tick_trace_id=tick_trace_id,
            side=side,
            entry_price=entry_price,
            exit_price=stop_loss,
            exit_reason="BREAK_EVEN_TRIGGERED",
            stop_loss=stop_loss,
            take_profit=0.0,
            pnl=round(pnl, 4),
            time_in_trade_s=time_in_trade_s,
            llm_rationale=reason,
            **self._market_fields(amt),
            **self._base_fields(),
        )
        self._write(entry)

    def _write(self, entry: JournalEntry) -> None:
        """Append a journal entry to the daily JSONL file."""
        fname = os.path.join(
            self._log_dir,
            f"journal_{date.today().isoformat()}.jsonl",
        )
        line = json.dumps(asdict(entry), default=str)
        with self._lock:
            try:
                with open(fname, "a") as f:
                    f.write(line + "\n")
            except Exception:
                logger.warning("Failed to write journal entry — audit trail gap", exc_info=True)

    def _iter_target_dates(self, start_date: str | None, end_date: str | None) -> list[str]:
        """Expand an inclusive date range into YYYY-MM-DD strings."""
        if start_date is None and end_date is None:
            return [date.today().isoformat()]

        if start_date is None:
            start_date = end_date
        if end_date is None:
            end_date = start_date

        start_dt = date.fromisoformat(start_date)
        end_dt = date.fromisoformat(end_date)
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt

        days = []
        cur = start_dt
        while cur <= end_dt:
            days.append(cur.isoformat())
            cur += timedelta(days=1)
        return days

    def read_entries(self, target_date: str | None = None, run_id: str | None = None) -> list[dict]:
        """Read all journal entries for a given date (YYYY-MM-DD)."""
        if target_date is None:
            target_date = date.today().isoformat()
        fname = os.path.join(self._log_dir, f"journal_{target_date}.jsonl")
        if not os.path.exists(fname):
            return []
        entries = []
        with open(fname) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        if run_id and entry.get("run_id") != run_id:
                            continue
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        return entries

    def read_entries_range(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        run_id: str | None = None,
    ) -> list[dict]:
        """Read entries across an inclusive date range."""
        entries: list[dict] = []
        for target_date in self._iter_target_dates(start_date, end_date):
            entries.extend(self.read_entries(target_date, run_id=run_id))
        return entries

    def get_completed_trades(self, target_date: str | None = None, run_id: str | None = None) -> list[dict]:
        """Return completed trades (entry+exit pairs matched by position_id)."""
        return self.get_completed_trades_for_entries(
            self.read_entries(target_date, run_id=run_id)
        )

    def summary(self, target_date: str | None = None, run_id: str | None = None) -> dict:
        """Return trade summary for a given date."""
        return self.summary_from_entries(
            self.read_entries(target_date, run_id=run_id),
            run_id=run_id or "",
        )

    def report(self, target_date: str | None = None, run_id: str | None = None) -> dict:
        """Return a richer paper-trading report for one day/run."""
        entries = self.read_entries(target_date, run_id=run_id)
        trades = self.get_completed_trades(target_date, run_id=run_id)
        summary = self.summary(target_date, run_id=run_id)
        return self.report_from_entries(entries, trades, summary)

    def compare_runs(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        run_ids: list[str] | None = None,
    ) -> dict:
        """Compare one or more runs across an inclusive date range."""
        entries = self.read_entries_range(start_date, end_date)
        discovered_run_ids = sorted({
            entry.get("run_id", "")
            for entry in entries
            if entry.get("run_id", "")
        })
        selected_run_ids = run_ids or discovered_run_ids

        runs: dict[str, dict] = {}
        for run_id in selected_run_ids:
            run_entries = [entry for entry in entries if entry.get("run_id") == run_id]
            if not run_entries:
                continue

            trades = self.get_completed_trades_for_entries(run_entries)
            summary = self.summary_from_entries(run_entries, run_id=run_id)
            report = self.report_from_entries(run_entries, trades, summary)
            runs[run_id] = report

        ranking = sorted(
            (
                {
                    "run_id": run_id,
                    "total_pnl": report["summary"]["total_pnl"],
                    "expectancy": report["performance"]["expectancy"],
                    "max_drawdown": report["performance"]["max_drawdown"],
                    "profit_factor": report["performance"]["profit_factor"],
                }
                for run_id, report in runs.items()
            ),
            key=lambda item: (item["total_pnl"], item["expectancy"]),
            reverse=True,
        )

        return {
            "start_date": start_date or end_date or date.today().isoformat(),
            "end_date": end_date or start_date or date.today().isoformat(),
            "run_ids": list(runs.keys()),
            "ranking": ranking,
            "runs": runs,
        }

    def assess_promotion(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        run_ids: list[str] | None = None,
        min_trades: int = 20,
        min_expectancy: float = 0.0,
        min_profit_factor: float = 1.1,
        max_drawdown: float = 10.0,
        min_trading_days: int = 3,
        max_symbol_concentration_pct: float = 70.0,
        require_multi_session: bool = True,
        min_thesis_completion_rate: float = 95.0,
        min_playbook_purity_rate: float = 95.0,
        max_playbook_session_misuse_rate: float = 0.0,
        min_feature_driver_coverage_rate: float = 90.0,
        min_aggression_driver_rate: float = 75.0,
    ) -> dict:
        """Evaluate whether one or more runs meet promotion thresholds."""
        comparison = self.compare_runs(
            start_date=start_date,
            end_date=end_date,
            run_ids=run_ids,
        )

        assessments: list[dict] = []
        for run_id, report in comparison["runs"].items():
            summary = report["summary"]
            perf = report["performance"]
            sessions = report["sessions"]
            symbols = report["symbols"]
            daily = report["days"]

            distinct_sessions = len([name for name in sessions if name and name != "UNKNOWN"])
            positive_days = sum(1 for bucket in daily.values() if float(bucket.get("pnl", 0.0)) > 0)
            symbol_trade_counts = [int(bucket.get("trades", 0)) for bucket in symbols.values()]
            total_symbol_trades = sum(symbol_trade_counts)
            max_symbol_concentration = round(
                self._safe_div(max(symbol_trade_counts) * 100.0, total_symbol_trades),
                2,
            ) if total_symbol_trades else 0.0

            checks = {
                "min_trades": summary["total_exits"] >= min_trades,
                "positive_expectancy": perf["expectancy"] >= min_expectancy,
                "profit_factor": (
                    perf["profit_factor"] >= min_profit_factor
                    or (summary["losses"] == 0 and summary["wins"] > 0)
                ),
                "max_drawdown": perf["max_drawdown"] <= max_drawdown,
                "positive_pnl": summary["total_pnl"] > 0,
                "min_trading_days": len(daily) >= min_trading_days,
                "positive_days": positive_days >= max(1, min_trading_days - 1),
                "symbol_concentration": max_symbol_concentration <= max_symbol_concentration_pct,
                "multi_session": distinct_sessions >= 2 if require_multi_session else True,
                "thesis_completion": report["thesis_completion_rate"] >= min_thesis_completion_rate,
                "playbook_purity": report["playbook_purity_rate"] >= min_playbook_purity_rate,
                "playbook_session_misuse": report["playbook_session_misuse"]["rate"] <= max_playbook_session_misuse_rate,
                "feature_driver_coverage": report["feature_driver_coverage_rate"] >= min_feature_driver_coverage_rate,
                "aggression_driver_rate": report["aggression_driver_rate"] >= min_aggression_driver_rate,
            }
            blockers = self._failed_check_names(checks)
            eligible = not blockers
            assessments.append(
                {
                    "run_id": run_id,
                    "eligible": eligible,
                    "recommendation": "PROMOTE_TO_NEXT_STAGE" if eligible else "KEEP_IN_PAPER",
                    "blockers": blockers,
                    "checks": checks,
                    "stability": {
                        "trading_days": len(daily),
                        "positive_days": positive_days,
                        "distinct_sessions": distinct_sessions,
                        "max_symbol_concentration_pct": max_symbol_concentration,
                        "playbook_session_misuse_rate": report["playbook_session_misuse"]["rate"],
                        "feature_driver_coverage_rate": report["feature_driver_coverage_rate"],
                        "aggression_driver_rate": report["aggression_driver_rate"],
                    },
                    "summary": summary,
                    "performance": perf,
                }
            )

        assessments.sort(
            key=lambda item: (
                item["eligible"],
                item["summary"]["total_pnl"],
                item["performance"]["expectancy"],
            ),
            reverse=True,
        )
        eligible_run_ids = [item["run_id"] for item in assessments if item["eligible"]]
        return {
            "start_date": comparison["start_date"],
            "end_date": comparison["end_date"],
            "thresholds": {
                "min_trades": min_trades,
                "min_expectancy": min_expectancy,
                "min_profit_factor": min_profit_factor,
                "max_drawdown": max_drawdown,
                "min_trading_days": min_trading_days,
                "max_symbol_concentration_pct": max_symbol_concentration_pct,
                "require_multi_session": require_multi_session,
                "min_thesis_completion_rate": min_thesis_completion_rate,
                "min_playbook_purity_rate": min_playbook_purity_rate,
                "max_playbook_session_misuse_rate": max_playbook_session_misuse_rate,
                "min_feature_driver_coverage_rate": min_feature_driver_coverage_rate,
                "min_aggression_driver_rate": min_aggression_driver_rate,
            },
            "recommended_run_id": eligible_run_ids[0] if eligible_run_ids else "",
            "eligible_run_ids": eligible_run_ids,
            "assessments": assessments,
        }

    def get_completed_trades_for_entries(self, entries: list[dict]) -> list[dict]:
        """Return completed trades from an in-memory entry set."""
        entries_by_pid: dict[str, dict] = {}
        trades: list[dict] = []
        for e in entries:
            if e.get("event_type") == "ENTRY_EXECUTED" and e.get("position_id"):
                entries_by_pid[e["position_id"]] = e
            elif e.get("event_type") == "EXIT" and e.get("position_id"):
                entry_ev = entries_by_pid.get(e["position_id"])
                trades.append({
                    "symbol": e.get("symbol", ""),
                    "side": e.get("side") or (entry_ev or {}).get("side", ""),
                    "entry_time": (entry_ev or {}).get("timestamp", ""),
                    "exit_time": e.get("timestamp", ""),
                    "entry_price": (entry_ev or {}).get("entry_price", 0),
                    "exit_price": e.get("exit_price", 0),
                    "stop_loss": (entry_ev or {}).get("stop_loss", 0),
                    "take_profit": (entry_ev or {}).get("take_profit", 0),
                    "pnl": e.get("pnl", 0),
                    "pnl_pct": e.get("pnl_pct", 0),
                    "duration_s": e.get("time_in_trade_s", 0),
                    "exit_reason": e.get("exit_reason", ""),
                    "mfe": e.get("mfe", 0),
                    "mae": e.get("mae", 0),
                    "market_state": (entry_ev or {}).get("market_state", ""),
                    "session_name": (entry_ev or {}).get("session_name", ""),
                    "llm_rationale": (entry_ev or {}).get("llm_rationale", ""),
                    "run_id": e.get("run_id", ""),
                    "attribution": (entry_ev or {}).get("attribution", ""),
                    "thesis_location_type": (entry_ev or {}).get("thesis_location_type", ""),
                    "thesis_aggression_trigger": (entry_ev or {}).get("thesis_aggression_trigger", ""),
                    "thesis_setup_family": (entry_ev or {}).get("thesis_setup_family", ""),
                    "agent_feature_drivers": (entry_ev or {}).get("agent_feature_drivers", []),
                    "position_id": e["position_id"],
                })
        return trades

    def summary_from_entries(self, entries: list[dict], *, run_id: str = "") -> dict:
        """Return summary metrics from a preloaded entry set."""
        exits = [e for e in entries if e.get("event_type") == "EXIT"]
        partials = [e for e in entries if e.get("event_type") == "PARTIAL_EXIT"]
        signals = [e for e in entries if e.get("event_type") == "SIGNAL_GENERATED"]
        rejections = [e for e in entries if e.get("event_type") == "ENTRY_REJECTED"]

        total_pnl = sum(e.get("pnl", 0) for e in exits)
        wins = [e for e in exits if e.get("pnl", 0) > 0]
        losses = [e for e in exits if e.get("pnl", 0) < 0]
        win_rate = len(wins) / len(exits) * 100 if exits else 0.0

        first_ts = entries[0].get("timestamp", "") if entries else ""
        summary_date = first_ts[:10] if first_ts else date.today().isoformat()
        return {
            "date": summary_date,
            "run_id": run_id,
            "total_signals": len(signals),
            "total_entries": len([e for e in entries if e.get("event_type") == "ENTRY_EXECUTED"]),
            "total_rejections": len(rejections),
            "total_exits": len(exits),
            "total_pnl": round(total_pnl, 4),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "avg_time_in_trade_s": round(
                sum(e.get("time_in_trade_s", 0) for e in exits) / len(exits), 1
            ) if exits else 0.0,
            "avg_mfe": round(sum(e.get("mfe", 0) for e in exits) / len(exits), 4) if exits else 0.0,
            "avg_mae": round(sum(e.get("mae", 0) for e in exits) / len(exits), 4) if exits else 0.0,
            "total_partial_exits": len(partials),
            "total_partial_pnl": round(sum(e.get("pnl", 0) for e in partials), 4),
            "entries_with_thesis": len([
                e for e in entries
                if e.get("event_type") == "ENTRY_EXECUTED"
                and e.get("thesis_market_state")
                and e.get("thesis_location_type")
                and e.get("thesis_aggression_trigger")
            ]),
        }

    def report_from_entries(self, entries: list[dict], trades: list[dict], summary: dict) -> dict:
        """Build a report from preloaded entries/trades/summary."""
        entries_by_pid = {
            e["position_id"]: e
            for e in entries
            if e.get("event_type") == "ENTRY_EXECUTED" and e.get("position_id")
        }

        attribution: dict[str, dict[str, float | int]] = {}
        rejection_breakdown: dict[str, int] = {}

        for trade in trades:
            entry_ev = entries_by_pid.get(trade["position_id"], {})
            key = entry_ev.get("attribution", "unknown") or "unknown"
            bucket = attribution.setdefault(key, {"trades": 0, "wins": 0, "pnl": 0.0})
            pnl = float(trade.get("pnl", 0.0))
            bucket["trades"] += 1
            bucket["pnl"] += pnl
            if pnl > 0:
                bucket["wins"] += 1

        for entry in entries:
            if entry.get("event_type") == "ENTRY_REJECTED":
                reason = entry.get("risk_reject_reason", "") or "UNKNOWN"
                rejection_breakdown[reason] = rejection_breakdown.get(reason, 0) + 1

        for bucket in attribution.values():
            trades_count = int(bucket["trades"])
            bucket["win_rate"] = round((bucket["wins"] / trades_count * 100), 1) if trades_count else 0.0
            bucket["pnl"] = round(float(bucket["pnl"]), 4)

        setup_families = self._bucket_trade_breakdown(trades, "thesis_setup_family")
        canonical_playbooks = {"imbalance_continuation", "return_to_value"}
        canonical_trade_count = sum(
            int(bucket.get("trades", 0))
            for name, bucket in setup_families.items()
            if name in canonical_playbooks
        )
        dominant_playbook_pct = round(
            self._safe_div(max((int(bucket.get("trades", 0)) for bucket in setup_families.values()), default=0) * 100.0, len(trades)),
            1,
        ) if trades else 0.0
        playbook_session_misuse = self._playbook_session_misuse(trades)
        explained_trade_count = sum(1 for trade in trades if self._has_feature_drivers(trade))
        aggression_explained_count = sum(1 for trade in trades if self._has_aggression_driver(trade))

        return {
            "summary": summary,
            "performance": self._performance_metrics(trades),
            "thesis_completion_rate": round(
                self._safe_div(summary.get("entries_with_thesis", 0) * 100.0, summary.get("total_entries", 0)),
                1,
            ),
            "playbook_purity_rate": round(self._safe_div(canonical_trade_count * 100.0, len(trades)), 1) if trades else 0.0,
            "dominant_playbook_pct": dominant_playbook_pct,
            "playbook_session_misuse": playbook_session_misuse,
            "feature_driver_coverage_rate": round(self._safe_div(explained_trade_count * 100.0, len(trades)), 1) if trades else 0.0,
            "aggression_driver_rate": round(self._safe_div(aggression_explained_count * 100.0, len(trades)), 1) if trades else 0.0,
            "attribution": attribution,
            "symbols": self._bucket_trade_breakdown(trades, "symbol"),
            "market_states": self._bucket_trade_breakdown(trades, "market_state"),
            "sessions": self._bucket_trade_breakdown(trades, "session_name"),
            "locations": self._bucket_trade_breakdown(trades, "thesis_location_type"),
            "aggression_triggers": self._bucket_trade_breakdown(trades, "thesis_aggression_trigger"),
            "setup_families": setup_families,
            "feature_drivers": self._feature_driver_breakdown(trades),
            "days": self._daily_trade_breakdown(trades),
            "rejections": rejection_breakdown,
        }
