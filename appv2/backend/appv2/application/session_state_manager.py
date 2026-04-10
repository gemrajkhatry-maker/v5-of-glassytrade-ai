"""Session State Manager — per-symbol persistent state for live trading.

Manages per-symbol state including:
- Candle history (bounded)
- Order book snapshots
- AMT analysis results
- Pending signals
- Executed signal IDs
- Position state
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from appv2.domain.models.ohlc import OHLC
from appv2.domain.models.signal import Signal

logger = logging.getLogger(__name__)

MAX_CANDLES = 2000


@dataclass
class SymbolSessionState:
    """Per-symbol session state — serializable to JSON."""
    symbol: str
    underlying: str
    candles: list[dict] = field(default_factory=list)
    pending_signal: dict | None = None
    executed_signal_ids: list[str] = field(default_factory=list)
    last_tick_time: str = ""
    last_analysis_time: float = 0.0
    position_state: dict = field(default_factory=dict)
    daily_pnl: float = 0.0
    trade_count: int = 0
    last_reset_date: str = ""

    def add_candle(self, candle: OHLC) -> None:
        """Add candle, bounded to MAX_CANDLES."""
        self.candles.append({
            "time": candle.time,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "delta": candle.delta,
        })
        if len(self.candles) > MAX_CANDLES:
            self.candles = self.candles[-MAX_CANDLES:]

    def set_pending_signal(self, signal: Signal) -> None:
        self.pending_signal = {
            "direction": signal.direction.value,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "confidence": signal.confidence,
            "timestamp": signal.timestamp,
        }

    def clear_pending_signal(self) -> None:
        self.pending_signal = None

    def mark_signal_executed(self, signal_id: str) -> None:
        self.executed_signal_ids.append(signal_id)
        # Keep last 100
        if len(self.executed_signal_ids) > 100:
            self.executed_signal_ids = self.executed_signal_ids[-100:]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "candle_count": len(self.candles),
            "last_tick_time": self.last_tick_time,
            "pending_signal": self.pending_signal,
            "executed_count": len(self.executed_signal_ids),
            "daily_pnl": self.daily_pnl,
            "trade_count": self.trade_count,
        }


class SessionStateManager:
    """Manages per-symbol session state with persistence."""

    def __init__(self, storage=None):
        self._storage = storage
        self._sessions: dict[str, SymbolSessionState] = {}

    def get_or_create(
        self,
        symbol: str,
        underlying: str = "",
    ) -> SymbolSessionState:
        """Get or create session state for a symbol."""
        if symbol not in self._sessions:
            self._sessions[symbol] = SymbolSessionState(
                symbol=symbol,
                underlying=underlying or symbol,
            )
        return self._sessions[symbol]

    def get(self, symbol: str) -> SymbolSessionState | None:
        return self._sessions.get(symbol)

    def reset(self, symbol: str = "") -> None:
        """Reset state for symbol (session boundary)."""
        if symbol:
            if symbol in self._sessions:
                state = self._sessions[symbol]
                state.candles.clear()
                state.pending_signal = None
                state.executed_signal_ids.clear()
                state.last_analysis_time = 0.0
        else:
            self._sessions.clear()

    async def persist(self, symbol: str) -> None:
        """Persist state to storage."""
        if self._storage and symbol in self._sessions:
            state = self._sessions[symbol]
            try:
                import json
                key = f"session_{symbol}"
                await self._storage.kv_set(key, json.dumps(state.to_dict()))
            except Exception as e:
                logger.error("Failed to persist state for %s: %s", symbol, e)

    async def restore(self, symbol: str) -> SymbolSessionState | None:
        """Restore state from storage."""
        if not self._storage:
            return None
        try:
            import json
            key = f"session_{symbol}"
            data = await self._storage.kv_get(key)
            if data:
                d = json.loads(data)
                state = SymbolSessionState(
                    symbol=d["symbol"],
                    underlying=d.get("underlying", d["symbol"]),
                    daily_pnl=d.get("daily_pnl", 0),
                    trade_count=d.get("trade_count", 0),
                    last_reset_date=d.get("last_reset_date", ""),
                )
                self._sessions[symbol] = state
                return state
        except Exception as e:
            logger.error("Failed to restore state for %s: %s", symbol, e)
        return None

    def get_all_states(self) -> dict[str, dict]:
        """Get snapshot of all session states."""
        return {sym: state.to_dict() for sym, state in self._sessions.items()}
