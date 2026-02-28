"""Trade Journal — comprehensive JSONL logging of all trade decisions."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone, timedelta
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class JournalEntry:
    timestamp: str = ""
    event_type: str = ""  # SIGNAL_GENERATED | ENTRY_EXECUTED | ENTRY_REJECTED | EXIT | OVERSEER_ACTION
    symbol: str = ""

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

    # Position info
    position_id: str = ""
    side: str = ""
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

    def __init__(self, log_dir: str = "live_trading_logs") -> None:
        os.makedirs(log_dir, exist_ok=True)
        self._log_dir = log_dir
        self._lock = Lock()

    def _now_ist(self) -> str:
        return datetime.now(IST).isoformat()

    def _market_fields(self, amt: dict | None) -> dict:
        """Extract market condition fields from AMT result dict."""
        if not amt:
            return {}
        return {
            "market_state": amt.get("marketState", ""),
            "ltp": amt.get("ltp", 0.0),
            "poc": amt.get("poc", 0.0),
            "vah": amt.get("vah", 0.0),
            "val": amt.get("val", 0.0),
            "delta": amt.get("delta", 0.0),
            "cvd_slope": amt.get("cvdSlope", 0.0),
            "cvd_divergence": amt.get("cvdDivergence", ""),
            "profile_shape": amt.get("profileShape", ""),
        }

    def log_signal(
        self,
        *,
        symbol: str,
        amt: dict | None = None,
        llm_direction: str = "",
        llm_confidence: str = "",
        llm_rationale: str = "",
        agent_direction: str = "",
        agent_regime: str = "",
        probability_long: float = 0.0,
        probability_short: float = 0.0,
    ) -> None:
        """Log when LLM produces a trade signal."""
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="SIGNAL_GENERATED",
            symbol=symbol,
            llm_direction=llm_direction,
            llm_confidence=llm_confidence,
            llm_rationale=llm_rationale,
            agent_direction=agent_direction,
            agent_regime=agent_regime,
            probability_long=probability_long,
            probability_short=probability_short,
            **self._market_fields(amt),
        )
        self._write(entry)

    def log_entry(
        self,
        *,
        symbol: str,
        position_id: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        amt: dict | None = None,
        agent_direction: str = "",
        agent_regime: str = "",
        probability_long: float = 0.0,
        probability_short: float = 0.0,
        llm_direction: str = "",
        llm_rationale: str = "",
    ) -> None:
        """Log when a position is successfully opened."""
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="ENTRY_EXECUTED",
            symbol=symbol,
            position_id=position_id,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            agent_direction=agent_direction,
            agent_regime=agent_regime,
            probability_long=probability_long,
            probability_short=probability_short,
            llm_direction=llm_direction,
            llm_rationale=llm_rationale,
            **self._market_fields(amt),
        )
        self._write(entry)

    def log_rejection(
        self,
        *,
        symbol: str,
        reason: str,
        amt: dict | None = None,
        llm_direction: str = "",
        agent_direction: str = "",
        agent_regime: str = "",
    ) -> None:
        """Log when an entry signal is rejected (risk manager, gate, etc.)."""
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="ENTRY_REJECTED",
            symbol=symbol,
            llm_direction=llm_direction,
            agent_direction=agent_direction,
            agent_regime=agent_regime,
            risk_check_passed=False,
            risk_reject_reason=reason,
            **self._market_fields(amt),
        )
        self._write(entry)

    def log_exit(
        self,
        *,
        symbol: str,
        position_id: str,
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
    ) -> None:
        """Log when a position is closed."""
        pnl_pct = (pnl / entry_price * 100) if entry_price > 0 else 0.0
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="EXIT",
            symbol=symbol,
            position_id=position_id,
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
            **self._market_fields(amt),
        )
        self._write(entry)

    def log_partial_exit(
        self,
        *,
        symbol: str,
        position_id: str,
        side: str,
        entry_price: float,
        exit_price: float,
        partial_pct: float,
        size_closed: float,
        size_remaining: float,
        realized_pnl: float,
        amt: dict | None = None,
    ) -> None:
        """Log a partial position close (e.g. 50% at TP1)."""
        pnl_pct = (realized_pnl / entry_price * 100) if entry_price > 0 else 0.0
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="PARTIAL_EXIT",
            symbol=symbol,
            position_id=position_id,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_reason=f"PARTIAL_{partial_pct:.0%}",
            pnl=round(realized_pnl, 4),
            pnl_pct=round(pnl_pct, 4),
            **self._market_fields(amt),
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
    ) -> None:
        """Log overseer actions (HOLD/TIGHTEN/PARTIAL/FULL_EXIT/ADD)."""
        entry = JournalEntry(
            timestamp=self._now_ist(),
            event_type="OVERSEER_ACTION",
            symbol=symbol,
            position_id=position_id,
            llm_rationale=reason,
            exit_reason=action,
            **self._market_fields(amt),
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
                logger.debug("Failed to write journal entry", exc_info=True)

    def read_entries(self, target_date: str | None = None) -> list[dict]:
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
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries

    def get_completed_trades(self, target_date: str | None = None) -> list[dict]:
        """Return completed trades (entry+exit pairs matched by position_id)."""
        entries = self.read_entries(target_date)
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
                    "llm_rationale": (entry_ev or {}).get("llm_rationale", ""),
                    "position_id": e["position_id"],
                })
        return trades

    def summary(self, target_date: str | None = None) -> dict:
        """Return trade summary for a given date."""
        entries = self.read_entries(target_date)
        exits = [e for e in entries if e.get("event_type") == "EXIT"]
        partials = [e for e in entries if e.get("event_type") == "PARTIAL_EXIT"]
        signals = [e for e in entries if e.get("event_type") == "SIGNAL_GENERATED"]
        rejections = [e for e in entries if e.get("event_type") == "ENTRY_REJECTED"]

        total_pnl = sum(e.get("pnl", 0) for e in exits)
        wins = [e for e in exits if e.get("pnl", 0) > 0]
        losses = [e for e in exits if e.get("pnl", 0) < 0]
        win_rate = len(wins) / len(exits) * 100 if exits else 0.0

        return {
            "date": target_date or date.today().isoformat(),
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
        }
