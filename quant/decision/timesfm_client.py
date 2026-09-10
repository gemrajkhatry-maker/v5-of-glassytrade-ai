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


def context_to_snapshot(ctx: DecisionContext) -> dict:
    """Convert a DecisionContext into the microservice's MarketSnapshot schema."""
    bar = ctx.bar
    amt = ctx.state

    # Timestamps
    ts = str(ctx.time_str or (bar.time if bar else ""))
    if not ts:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    # OHLCV
    if bar is not None:
        open_p = float(bar.open)
        high_p = float(bar.high)
        low_p = float(bar.low)
        close_p = float(bar.close)
        volume = float(bar.volume)
        delta = float(bar.delta)
        cum_delta = float(getattr(bar, "cum_delta", 0.0) or 0.0)
        vwap = float(getattr(bar, "vwap", close_p) or close_p)
    elif amt is not None:
        open_p = float(amt.close if hasattr(amt, "close") else amt.poc)
        high_p = float(amt.vah if hasattr(amt, "vah") else open_p)
        low_p = float(amt.val if hasattr(amt, "val") else open_p)
        close_p = open_p
        volume = 100.0
        delta = 0.0
        cum_delta = 0.0
        vwap = open_p
    else:
        open_p = high_p = low_p = close_p = 100.0
        volume = 100.0
        delta = 0.0
        cum_delta = 0.0
        vwap = 100.0

    poc = float(ctx.poc or (amt.poc if amt else close_p))
    vah = float(ctx.vah or (amt.vah if amt else high_p))
    val = float(ctx.val or (amt.val if amt else low_p))

    market_state_str = ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED")
    data_quality_str = str(getattr(ctx.data_quality, "value", ctx.data_quality) if ctx.data_quality else "CANDLE_DISTRIBUTED")

    spread = float(round(abs(ctx.ask - ctx.bid), 4)) if (ctx.ask > 0 and ctx.bid > 0) else 0.05

    return {
        "symbol": str(ctx.symbol or "UNKNOWN"),
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
        "cvd_slope": float(ctx.cvd_slope or 0.0),
        "absorption_side": str(ctx.absorption_side or ""),
        "stacked_imbalance_direction": str(getattr(ctx, "stacked_imbalance_direction", "") or "NONE"),
        "stacked_imbalance_magnitude": int(getattr(ctx, "stacked_imbalance_magnitude", 0) or 0),
        "stacked_imbalance_price_low": float(getattr(ctx, "stacked_imbalance_price_low", 0.0) or 0.0),
        "stacked_imbalance_price_high": float(getattr(ctx, "stacked_imbalance_price_high", 0.0) or 0.0),
        "triple_a_phase": str(getattr(ctx, "triple_a_phase", "") or ""),
        "triple_a_signal": str(getattr(ctx, "triple_a_signal", "") or ""),
        "time_str": str(ctx.time_str or ""),
        "market_state": market_state_str,
        "session_phase": str(ctx.session_phase or "REGULAR"),
        "allow_trend": bool(ctx.allow_trend),
        "allow_reversion": bool(ctx.allow_reversion),
        "risk_halted": bool(ctx.risk_halted),
        "consecutive_losses": int(ctx.consecutive_losses or 0),
        "vwap_std": float(ctx.vwap_std or 0.0),
        "vwap_upper_2": float(ctx.vwap_upper_2 or 0.0),
        "vwap_lower_2": float(ctx.vwap_lower_2 or 0.0),
        "balance_ratio": float(ctx.balance_ratio or 0.0),
        "break_direction": str(ctx.break_direction or ""),
        "break_type": str(ctx.break_type or ""),
        "leg_lvn": float(ctx.leg_lvn or 0.0),
        "nearest_buy_print_below": float(getattr(ctx, "nearest_buy_print_below", 0.0) or 0.0),
        "nearest_sell_print_above": float(getattr(ctx, "nearest_sell_print_above", 0.0) or 0.0),
        "position_entry_price": float(ctx.position_entry_price or 0.0),
        "position_size": float(ctx.position_size or 0.0),
        "position_unrealized_pnl": float(ctx.position_unrealized_pnl or 0.0),
        "position_sl": float(ctx.position_sl or 0.0),
        "position_tp": float(ctx.position_tp or 0.0),
        "position_bars_held": int(ctx.position_bars_held or 0),
        "cooldown_remaining_sec": int(ctx.cooldown_remaining_sec or 0),
        "equity": float(ctx.equity or FALLBACK_EQUITY),
        "risk_per_trade_pct": float(ctx.risk_per_trade_pct or 0.01),
        "tick_size": float(ctx.tick_size or 0.05),
        "data_quality": data_quality_str,
        "drive_entry_valid": bool(ctx.drive_entry_valid),
        "drive_number": int(ctx.drive_number or 0),
        "prior_poc": float(ctx.prior_poc or 0.0),
        "npoc_above": float(ctx.npoc_above or 0.0),
        "npoc_below": float(ctx.npoc_below or 0.0),
        "squeeze_detected": bool(getattr(ctx, "squeeze_detected", False)),
        "squeeze_direction": str(getattr(ctx, "squeeze_direction", "") or ""),
        "squeeze_trapped_level": float(getattr(ctx, "squeeze_trapped_level", 0.0) or 0.0),
        "pullback_confirmed": bool(getattr(ctx, "pullback_confirmed", False)),
        "spread": spread,
    }


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
