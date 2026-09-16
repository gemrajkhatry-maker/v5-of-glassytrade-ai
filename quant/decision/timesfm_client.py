"""TimesFM + Qwen microservice client & snapshot adapter.

Connects to the TimesFM Prediction Service (default http://localhost:8091)
and manages rolling 32-bar MarketSnapshot windows from DecisionContext.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from quant.contracts.constants import FALLBACK_EQUITY
from quant.decision.context import DecisionContext

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_URL = os.getenv("TIMESFM_SERVICE_URL", "http://localhost:8091")


def _extract_amt_ohlcv(amt: Any) -> tuple:
    """Extract OHLCV values from an amount/profile object."""
    open_p = float(amt.close if hasattr(amt, "close") else amt.poc)
    high_p = float(amt.vah if hasattr(amt, "vah") else open_p)
    low_p = float(amt.val if hasattr(amt, "val") else open_p)
    return open_p, high_p, low_p, open_p, 100.0, 0.0, 0.0, open_p


def _extract_ohlcv(bar: Any, amt: Any) -> tuple:
    """Extract OHLCV values from bar, amount, or defaults."""
    if bar is not None:
        cum_delta = float(getattr(bar, "cum_delta", 0.0) or 0.0)
        vwap = float(getattr(bar, "vwap", bar.close) or bar.close)
        return (
            float(bar.open), float(bar.high), float(bar.low), float(bar.close),
            float(bar.volume), float(bar.delta), cum_delta, vwap,
        )
    elif amt is not None:
        return _extract_amt_ohlcv(amt)
    else:
        return 100.0, 100.0, 100.0, 100.0, 100.0, 0.0, 0.0, 100.0


def _extract_market_state_str(market_state: Any) -> str:
    """Convert market_state enum or value to string."""
    if hasattr(market_state, "value"):
        return market_state.value
    return str(market_state or "BALANCED")


def _extract_data_quality_str(data_quality: Any) -> str:
    """Convert data_quality enum or value to string."""
    if data_quality:
        return str(getattr(data_quality, "value", data_quality))
    return "CANDLE_DISTRIBUTED"


def _resolve_profile_levels(ctx: DecisionContext, amt: Any, close_p: float, high_p: float, low_p: float) -> tuple:
    """Resolve POC, VAH, VAL from context or amount object."""
    poc = float(ctx.poc if ctx.poc is not None else (amt.poc if amt else close_p))
    vah = float(ctx.vah if ctx.vah is not None else (amt.vah if amt else high_p))
    val = float(ctx.val if ctx.val is not None else (amt.val if amt else low_p))
    return poc, vah, val


def _resolve_timestamp(ctx: DecisionContext) -> str:
    """Resolve the snapshot timestamp from context."""
    bar = ctx.bar
    ts = str(ctx.time_str or (bar.time if bar else ""))
    if not ts:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    return ts


def _compute_spread(ctx: DecisionContext) -> float:
    """Compute bid-ask spread from context."""
    if ctx.ask > 0 and ctx.bid > 0:
        return float(round(abs(ctx.ask - ctx.bid), 4))
    return 0.05


def _build_context_fields(ctx: DecisionContext, ts: str, ohlcv: tuple, profile: tuple,
                          market_state_str: str, data_quality_str: str, spread: float) -> dict:
    """Build the complete snapshot dictionary from context and pre-computed values.

    Uses getattr with defaults for safe attribute access.  This is behaviorally
    equivalent to the original ``field or default`` pattern for all non-None values.
    """
    open_p, high_p, low_p, close_p, volume, delta, cum_delta, vwap = ohlcv
    poc, vah, val = profile
    return {
        "symbol": str(getattr(ctx, "symbol", "UNKNOWN") or "UNKNOWN"),
        "timestamp": ts,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": volume,
        "delta": delta,
        "cum_delta": cum_delta,
        "vwap": vwap,
        "poc": poc,
        "vah": vah,
        "val": val,
        "cvd_slope": float(getattr(ctx, "cvd_slope", 0.0)),
        "absorption_side": str(getattr(ctx, "absorption_side", "")),
        "stacked_imbalance_direction": str(getattr(ctx, "stacked_imbalance_direction", "NONE")),
        "stacked_imbalance_magnitude": int(getattr(ctx, "stacked_imbalance_magnitude", 0)),
        "stacked_imbalance_price_low": float(getattr(ctx, "stacked_imbalance_price_low", 0.0)),
        "stacked_imbalance_price_high": float(getattr(ctx, "stacked_imbalance_price_high", 0.0)),
        "triple_a_phase": str(getattr(ctx, "triple_a_phase", "")),
        "triple_a_signal": str(getattr(ctx, "triple_a_signal", "")),
        "time_str": str(getattr(ctx, "time_str", "")),
        "market_state": market_state_str,
        "session_phase": str(getattr(ctx, "session_phase", "REGULAR")),
        "allow_trend": bool(getattr(ctx, "allow_trend", False)),
        "allow_reversion": bool(getattr(ctx, "allow_reversion", False)),
        "risk_halted": bool(getattr(ctx, "risk_halted", False)),
        "consecutive_losses": int(getattr(ctx, "consecutive_losses", 0)),
        "vwap_std": float(getattr(ctx, "vwap_std", 0.0)),
        "vwap_upper_2": float(getattr(ctx, "vwap_upper_2", 0.0)),
        "vwap_lower_2": float(getattr(ctx, "vwap_lower_2", 0.0)),
        "balance_ratio": float(getattr(ctx, "balance_ratio", 0.0)),
        "break_direction": str(getattr(ctx, "break_direction", "")),
        "break_type": str(getattr(ctx, "break_type", "")),
        "leg_lvn": float(getattr(ctx, "leg_lvn", 0.0)),
        "nearest_buy_print_below": float(getattr(ctx, "nearest_buy_print_below", 0.0)),
        "nearest_sell_print_above": float(getattr(ctx, "nearest_sell_print_above", 0.0)),
        "position_entry_price": float(getattr(ctx, "position_entry_price", 0.0)),
        "position_size": float(getattr(ctx, "position_size", 0.0)),
        "position_unrealized_pnl": float(getattr(ctx, "position_unrealized_pnl", 0.0)),
        "position_sl": float(getattr(ctx, "position_sl", 0.0)),
        "position_tp": float(getattr(ctx, "position_tp", 0.0)),
        "position_bars_held": int(getattr(ctx, "position_bars_held", 0)),
        "cooldown_remaining_sec": int(getattr(ctx, "cooldown_remaining_sec", 0)),
        "equity": float(ctx.equity or FALLBACK_EQUITY),
        "risk_per_trade_pct": float(getattr(ctx, "risk_per_trade_pct", 0.01) or 0.01),
        "tick_size": float(getattr(ctx, "tick_size", 0.05) or 0.05),
        "data_quality": data_quality_str,
        "drive_entry_valid": bool(getattr(ctx, "drive_entry_valid", False)),
        "drive_number": int(getattr(ctx, "drive_number", 0)),
        "prior_poc": float(getattr(ctx, "prior_poc", 0.0)),
        "npoc_above": float(getattr(ctx, "npoc_above", 0.0)),
        "npoc_below": float(getattr(ctx, "npoc_below", 0.0)),
        "squeeze_detected": bool(getattr(ctx, "squeeze_detected", False)),
        "squeeze_direction": str(getattr(ctx, "squeeze_direction", "")),
        "squeeze_trapped_level": float(getattr(ctx, "squeeze_trapped_level", 0.0)),
        "pullback_confirmed": bool(getattr(ctx, "pullback_confirmed", False)),
        "spread": spread,
    }


def context_to_snapshot(ctx: DecisionContext) -> dict:
    """Convert a DecisionContext into the microservice's MarketSnapshot schema."""
    amt = ctx.state
    ts = _resolve_timestamp(ctx)
    ohlcv = _extract_ohlcv(ctx.bar, amt)
    profile = _resolve_profile_levels(ctx, amt, ohlcv[3], ohlcv[1], ohlcv[2])
    market_state_str = _extract_market_state_str(ctx.market_state)
    data_quality_str = _extract_data_quality_str(ctx.data_quality)
    spread = _compute_spread(ctx)
    return _build_context_fields(ctx, ts, ohlcv, profile, market_state_str, data_quality_str, spread)


class TimesFMSnapshotBuffer:
    """Maintains a rolling 32-snapshot window per symbol with automatic padding."""

    def __init__(self, target_size: int = 32) -> None:
        self.target_size = target_size
        self._buffers: Dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=self.target_size)
        )

    def add_snapshot(self, snapshot: dict) -> List[dict]:
        """Add a snapshot and return a list of exactly target_size snapshots (padded if needed)."""
        symbol = snapshot.get("symbol", "DEFAULT")
        buf = self._buffers[symbol]
        buf.append(snapshot)

        current_list = list(buf)
        if len(current_list) < self.target_size:
            # Pad by repeating earliest item at the head
            pad_count = self.target_size - len(current_list)
            earliest = current_list[0]
            padded = [dict(earliest) for _ in range(pad_count)] + current_list
            return padded

        return current_list

    def get_window(self, symbol: str) -> Optional[List[dict]]:
        """Get current window for a symbol (padded to target_size), or None if empty."""
        buf = self._buffers.get(symbol)
        if not buf:
            return None
        current_list = list(buf)
        if len(current_list) < self.target_size:
            pad_count = self.target_size - len(current_list)
            return [dict(current_list[0]) for _ in range(pad_count)] + current_list
        return current_list


class TimesFMClient:
    """HTTP client for TimesFM prediction microservice."""

    def __init__(self, base_url: str = DEFAULT_SERVICE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def is_healthy(self, timeout: float = 2.0) -> bool:
        """Ping /health to check microservice availability."""
        try:
            url = f"{self.base_url}/health"
            req = urllib.request.Request(url, headers={"User-Agent": "GlassyTrade-AI"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("status") == "ok"
        except Exception as e:
            logger.debug("TimesFM health check failed (%s): %s", self.base_url, e)
        return False

    def predict(
        self,
        snapshots: List[dict],
        invoke_llm: bool = False,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        """POST snapshots to /predict endpoint."""
        if not snapshots:
            return None
        url = f"{self.base_url}/predict"
        payload = json.dumps({"snapshots": snapshots, "invoke_llm": invoke_llm}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "GlassyTrade-AI"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.warning("TimesFM predict HTTP %d: %s", e.code, e.read().decode("utf-8"))
        except Exception as e:
            logger.warning("TimesFM predict request failed: %s", e)
        return None
