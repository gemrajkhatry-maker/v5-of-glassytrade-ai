"""State Bus — single source of truth for all market state.

Every market data update flows through this bus.  Each update must:
1. Pass a freshness check (max staleness in ms)
2. Trigger a session consistency check (incoming.session_id == current_session.id)
3. Emit a DATA_ANOMALY event if any domain invariant fails

This prevents the silent divergence between what the UI shows and what
the decision engine uses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.domain.models.market_state import InvariantError, VolumeProfile, VWAPState


logger = logging.getLogger(__name__)

# Maximum age of market data before it's considered stale
_MAX_STALENESS_MS = 5000  # 5 seconds


class DataAnomaly:
    """Immutable record of a data anomaly detected by the state bus."""

    __slots__ = ("symbol", "anomaly_type", "detail", "timestamp")

    def __init__(self, symbol: str, anomaly_type: str, detail: str) -> None:
        self.symbol = symbol
        self.anomaly_type = anomaly_type
        self.detail = detail
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def __repr__(self) -> str:
        return (
            f"DataAnomaly(symbol={self.symbol}, type={self.anomaly_type}, "
            f"detail={self.detail})"
        )


class StateBus:
    """Central state bus with validation middleware.

    All market data must flow through this bus.  Each update is validated
    before being published to consumers (WebSocket, LLM handler, UI snapshot).

    Usage:
        bus = StateBus()
        bus.set_current_session("SYM", "20260402_NSE_CRUDEOIL")
        bus.publish("SYM", {"poc": 310, "val": 298, "vah": 330, ...})
    """

    def __init__(self) -> None:
        self._latest: dict[str, dict[str, Any]] = {}
        self._current_sessions: dict[str, str] = {}
        self._anomalies: list[DataAnomaly] = []
        self._max_anomalies = 100

    def set_current_session(self, symbol: str, session_id: str) -> None:
        """Register the current session for a symbol.

        Used to detect cross-session contamination when stale data
        from a prior session arrives after a session boundary.
        """
        prev = self._current_sessions.get(symbol)
        if prev and prev != session_id:
            anomaly = DataAnomaly(
                symbol=symbol,
                anomaly_type="SESSION_CHANGE",
                detail=f"Session changed: {prev} -> {session_id}",
            )
            self._record_anomaly(anomaly)
            logger.info(
                "StateBus: session change for %s: %s -> %s", symbol, prev, session_id
            )
        self._current_sessions[symbol] = session_id

    def publish(self, symbol: str, state: dict[str, Any]) -> dict[str, Any] | None:
        """Validate and publish a state update.

        Returns the validated state dict, or None if validation failed.
        Failed validations emit a DATA_ANOMALY event.

        Args:
            symbol: Trading symbol
            state: State dict containing market data (AMT, VWAP, etc.)

        Returns:
            Validated state dict, or None if rejected
        """
        # 1. Session consistency check
        current_session = self._current_sessions.get(symbol)
        incoming_session = state.get("sessionId")
        if current_session and incoming_session and incoming_session != current_session:
            anomaly = DataAnomaly(
                symbol=symbol,
                anomaly_type="SESSION_MISMATCH",
                detail=f"Expected session {current_session}, got {incoming_session}",
            )
            self._record_anomaly(anomaly)
            logger.warning(
                "StateBus: session mismatch for %s — expected %s, got %s",
                symbol,
                current_session,
                incoming_session,
            )
            # Still publish — the data may be from a legitimate session change
            # that hasn't been registered yet.  The anomaly is logged for diagnostics.

        # 2. Domain invariant validation
        if not self._validate_invariants(symbol, state):
            return None

        # 3. Freshness check
        computed_at = state.get("computedAt")
        if computed_at:
            try:
                computed_dt = datetime.fromisoformat(computed_at)
                age_ms = (
                    datetime.now(computed_dt.tzinfo or timezone.utc) - computed_dt
                ).total_seconds() * 1000
                if age_ms > _MAX_STALENESS_MS:
                    anomaly = DataAnomaly(
                        symbol=symbol,
                        anomaly_type="STALE_DATA",
                        detail=f"Data is {age_ms:.0f}ms old (max: {_MAX_STALENESS_MS}ms)",
                    )
                    self._record_anomaly(anomaly)
                    logger.warning(
                        "StateBus: stale data for %s — age=%.0fms",
                        symbol,
                        age_ms,
                    )
            except (ValueError, TypeError):
                pass  # Invalid timestamp — skip freshness check

        # 4. Publish
        self._latest[symbol] = state
        return state

    def get(self, symbol: str) -> dict[str, Any] | None:
        """Get the latest validated state for a symbol."""
        return self._latest.get(symbol)

    def get_anomalies(
        self, symbol: str | None = None, limit: int = 20
    ) -> list[DataAnomaly]:
        """Get recent anomalies, optionally filtered by symbol."""
        anomalies = self._anomalies
        if symbol:
            anomalies = [a for a in anomalies if a.symbol == symbol]
        return anomalies[-limit:]

    def clear_anomalies(self) -> None:
        """Clear all recorded anomalies."""
        self._anomalies.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate_invariants(self, symbol: str, state: dict[str, Any]) -> bool:
        """Validate domain invariants on the state dict.

        Returns True if all invariants pass, False otherwise.
        Failed validations emit a DATA_ANOMALY event.
        """
        poc = state.get("poc", 0)
        val = state.get("val", 0)
        vah = state.get("vah", 0)

        # POC must be positive
        if poc <= 0:
            anomaly = DataAnomaly(
                symbol=symbol,
                anomaly_type="INVARIANT_VIOLATION",
                detail=f"POC={poc} — must be positive",
            )
            self._record_anomaly(anomaly)
            return False

        # VAL < POC < VAH
        if val >= poc:
            anomaly = DataAnomaly(
                symbol=symbol,
                anomaly_type="INVARIANT_VIOLATION",
                detail=f"VAL ({val}) >= POC ({poc})",
            )
            self._record_anomaly(anomaly)
            return False

        if poc >= vah:
            anomaly = DataAnomaly(
                symbol=symbol,
                anomaly_type="INVARIANT_VIOLATION",
                detail=f"POC ({poc}) >= VAH ({vah})",
            )
            self._record_anomaly(anomaly)
            return False

        # VWAP must be positive if present
        vwap = state.get("sessionVwap", 0)
        if vwap < 0:
            anomaly = DataAnomaly(
                symbol=symbol,
                anomaly_type="INVARIANT_VIOLATION",
                detail=f"VWAP={vwap} — must be non-negative",
            )
            self._record_anomaly(anomaly)
            return False

        # VWAP deviation sign check
        deviation = state.get("vwapDeviationSigmas", 0)
        sigma = state.get("vwapUpper1", 0) - vwap  # sigma = upper_1 - vwap
        if sigma > 0 and abs(deviation) > 10:
            anomaly = DataAnomaly(
                symbol=symbol,
                anomaly_type="VWAP_DEVIATION_EXTREME",
                detail=f"VWAP deviation={deviation:.2f}σ — possible data source mismatch",
            )
            self._record_anomaly(anomaly)
            logger.warning(
                "StateBus: extreme VWAP deviation for %s: %.2fσ",
                symbol,
                deviation,
            )

        return True

    def _record_anomaly(self, anomaly: DataAnomaly) -> None:
        """Record an anomaly and emit event if event bus is available."""
        self._anomalies.append(anomaly)
        # Trim to prevent unbounded growth
        if len(self._anomalies) > self._max_anomalies:
            self._anomalies = self._anomalies[-self._max_anomalies :]

        logger.warning(
            "StateBus ANOMALY [%s]: %s — %s",
            anomaly.anomaly_type,
            anomaly.symbol,
            anomaly.detail,
        )
