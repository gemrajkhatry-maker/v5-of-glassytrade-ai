"""Forward test logger — records signals and outcomes for live validation."""

from __future__ import annotations
import csv
import logging
import os
from datetime import datetime, date, timezone
from threading import Lock

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ForwardTestLogger:
    """Logs every signal and trade outcome to daily CSV for performance analysis."""

    def __init__(self, log_dir: str = "live_trading_logs", experiment=None) -> None:
        os.makedirs(log_dir, exist_ok=True)
        self._log_dir = log_dir
        self._lock = Lock()
        self._experiment = experiment

    def _base_fields(self) -> dict:
        if not self._experiment:
            return {}
        return {
            "run_id": self._experiment.run_id,
            "config_fingerprint": self._experiment.config_fingerprint,
            "llm_entry_contract_version": self._experiment.llm_entry_contract_version,
            "probability_feature_schema_version": self._experiment.probability_feature_schema_version,
        }

    def log_signal(
        self,
        *,
        symbol: str,
        direction: str,
        p_long: float,
        p_short: float,
        llm_direction: str,
        llm_confidence: str,
        option_type_flag: float,
        moneyness_pct: float,
        dte_normalized: float,
        source: str,
        attribution: str = "",
    ) -> None:
        """Log an entry signal with probability and metadata."""
        row = {
            "timestamp": _utc_now(),
            "symbol": symbol,
            "direction": direction,
            "p_long": round(p_long, 4),
            "p_short": round(p_short, 4),
            "llm_direction": llm_direction,
            "llm_confidence": llm_confidence,
            "option_type_flag": option_type_flag,
            "moneyness_pct": round(moneyness_pct, 4),
            "dte_normalized": round(dte_normalized, 4),
            "source": source,
            "attribution": attribution,
        }
        row.update(self._base_fields())
        self._write("signals", row)

    def log_exit(
        self,
        *,
        symbol: str,
        position_id: str,
        pnl: float,
        mfe: float,
        mae: float,
        time_in_trade_s: float,
        exit_reason: str,
        attribution: str = "",
    ) -> None:
        """Log a trade exit with outcome metrics."""
        row = {
            "timestamp": _utc_now(),
            "symbol": symbol,
            "position_id": position_id,
            "pnl": round(pnl, 4),
            "mfe": round(mfe, 4),
            "mae": round(mae, 4),
            "time_in_trade_s": round(time_in_trade_s, 1),
            "exit_reason": exit_reason,
            "attribution": attribution,
        }
        row.update(self._base_fields())
        self._write("exits", row)

    def log_partial_exit(
        self,
        *,
        symbol: str,
        position_id: str,
        partial_pct: float,
        size_closed: float,
        size_remaining: float,
        exit_price: float,
        realized_pnl: float,
        exit_reason: str,
        attribution: str = "",
    ) -> None:
        """Log a partial exit."""
        row = {
            "timestamp": _utc_now(),
            "symbol": symbol,
            "position_id": position_id,
            "partial_pct": round(partial_pct, 2),
            "size_closed": round(size_closed, 2),
            "size_remaining": round(size_remaining, 2),
            "exit_price": round(exit_price, 4),
            "realized_pnl": round(realized_pnl, 4),
            "exit_reason": exit_reason,
            "attribution": attribution,
        }
        row.update(self._base_fields())
        self._write("partial_exits", row)

    def _write(self, kind: str, row: dict) -> None:
        """Append a row to the daily CSV file for the given kind."""
        fname = os.path.join(self._log_dir, f"forward_{kind}_{date.today()}.csv")
        with self._lock:
            write_header = not os.path.exists(fname)
            with open(fname, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(row.keys()))
                if write_header:
                    w.writeheader()
                w.writerow(row)
