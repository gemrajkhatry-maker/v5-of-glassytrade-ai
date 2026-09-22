"""SessionKernel — single owner of per-symbol AMT rolling state.

``process(bar, *, duplicate)`` advances profile, decision VA, CVD, VWAP, IB,
drive, acceptance, and footprint in one place. Warmth is the count of bars
that fully passed through every tracker — not ``len(seed)``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SessionKernel:
    """Thin owner around AMTAnalyzer session trackers + footprint accumulator."""

    def __init__(
        self,
        analyzer: Any,
        *,
        footprint_accumulator: Any | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._footprint = footprint_accumulator
        self.warm_bars: int = 0

    def reset(self) -> None:
        self._analyzer.reset_session()
        if self._footprint is not None and hasattr(self._footprint, "reset"):
            self._footprint.reset()
        elif self._footprint is not None and hasattr(self._footprint, "clear"):
            self._footprint.clear()
        self.warm_bars = 0

    def allow_duplicate_refeed(self) -> None:
        """Clear dedupe guards so a corrected same-timestamp bar updates all trackers."""
        cvd = getattr(self._analyzer, "_cvd_tracker", None)
        if cvd is not None:
            cvd._last_time = ""
        ar = getattr(self._analyzer, "_ar_engine", None)
        if ar is not None:
            ar._last_time = ""
        vwap = getattr(self._analyzer, "_vwap", None)
        if vwap is not None and hasattr(vwap, "_last_time"):
            vwap._last_time = ""

    def record_warm_bar(self) -> None:
        self.warm_bars += 1

    def export_state(self) -> dict:
        """Order-flow + warmth snapshot for mid-session restart."""
        cvd = getattr(self._analyzer, "_cvd_tracker", None)
        vwap = getattr(self._analyzer, "_vwap", None)
        ib = getattr(self._analyzer, "_ib_tracker", None)
        ar = getattr(self._analyzer, "_ar_engine", None)
        return {
            "warm_bars": self.warm_bars,
            "cvd": cvd.export_state() if cvd is not None and hasattr(cvd, "export_state") else {},
            "vwap_cum_vol": float(getattr(vwap, "_cum_vol", 0.0) or 0.0) if vwap else 0.0,
            "vwap_cum_quote": float(getattr(vwap, "_cum_quote_vol", 0.0) or 0.0) if vwap else 0.0,
            "ib_high": float(getattr(ib, "ib_high", 0.0) or 0.0) if ib else 0.0,
            "ib_low": float(getattr(ib, "ib_low", 0.0) or 0.0) if ib else 0.0,
            "time_above_vah": float(getattr(ar, "_time_above_vah", 0.0) or 0.0) if ar else 0.0,
            "time_below_val": float(getattr(ar, "_time_below_val", 0.0) or 0.0) if ar else 0.0,
        }

    def import_state(self, data: dict | None) -> None:
        if not data:
            return
        self.warm_bars = int(data.get("warm_bars") or 0)
        cvd = getattr(self._analyzer, "_cvd_tracker", None)
        if cvd is not None and hasattr(cvd, "import_state"):
            cvd.import_state(data.get("cvd"))
        vwap = getattr(self._analyzer, "_vwap", None)
        if vwap is not None:
            if hasattr(vwap, "_cum_vol"):
                vwap._cum_vol = float(data.get("vwap_cum_vol") or 0.0)
            if hasattr(vwap, "_cum_quote_vol"):
                vwap._cum_quote_vol = float(data.get("vwap_cum_quote") or 0.0)
        ib = getattr(self._analyzer, "_ib_tracker", None)
        if ib is not None:
            if "ib_high" in data:
                ib._ib_high = float(data.get("ib_high") or 0.0)
            if "ib_low" in data:
                low = float(data.get("ib_low") or 0.0)
                ib._ib_low = low if low > 0.0 else float("inf")
        ar = getattr(self._analyzer, "_ar_engine", None)
        if ar is not None:
            ar._time_above_vah = float(data.get("time_above_vah") or 0.0)
            ar._time_below_val = float(data.get("time_below_val") or 0.0)
