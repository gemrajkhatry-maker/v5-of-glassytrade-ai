"""State bus validation for market snapshots before publication."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MAX_STALENESS_MS = 5000


class DataAnomaly:
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
    def __init__(self) -> None:
        self._latest: dict[str, dict[str, Any]] = {}
        self._current_sessions: dict[str, str] = {}
        self._anomalies: list[DataAnomaly] = []
        self._max_anomalies = 100

    def set_current_session(self, symbol: str, session_id: str) -> None:
        previous = self._current_sessions.get(symbol)
        if previous and previous != session_id:
            self._record_anomaly(
                DataAnomaly(
                    symbol=symbol,
                    anomaly_type="SESSION_CHANGE",
                    detail=f"Session changed: {previous} -> {session_id}",
                )
            )
            logger.info(
                "StateBus: session change for %s: %s -> %s",
                symbol,
                previous,
                session_id,
            )
        self._current_sessions[symbol] = session_id

    def publish(self, symbol: str, state: dict[str, Any]) -> dict[str, Any] | None:
        current_session = self._current_sessions.get(symbol)
        incoming_session = state.get("sessionId")
        if current_session and incoming_session and incoming_session != current_session:
            self._record_anomaly(
                DataAnomaly(
                    symbol=symbol,
                    anomaly_type="SESSION_MISMATCH",
                    detail=f"Expected session {current_session}, got {incoming_session}",
                )
            )
            logger.warning(
                "StateBus: session mismatch for %s — expected %s, got %s",
                symbol,
                current_session,
                incoming_session,
            )

        if not self._validate_invariants(symbol, state):
            return None

        computed_at = state.get("computedAt")
        if computed_at:
            try:
                computed_dt = datetime.fromisoformat(computed_at)
                if computed_dt.tzinfo is None:
                    computed_dt = computed_dt.replace(tzinfo=timezone.utc)
                age_ms = (datetime.now(timezone.utc) - computed_dt).total_seconds() * 1000
                if age_ms > _MAX_STALENESS_MS:
                    self._record_anomaly(
                        DataAnomaly(
                            symbol=symbol,
                            anomaly_type="STALE_DATA",
                            detail=(
                                f"Data is {age_ms:.0f}ms old (max: {_MAX_STALENESS_MS}ms)"
                            ),
                        )
                    )
                    logger.warning(
                        "StateBus: stale data for %s — age=%.0fms", symbol, age_ms
                    )
                    return None
            except (ValueError, TypeError):
                pass

        self._latest[symbol] = state
        return state

    def get(self, symbol: str) -> dict[str, Any] | None:
        return self._latest.get(symbol)

    def get_anomalies(self, symbol: str | None = None, limit: int = 20) -> list[DataAnomaly]:
        anomalies = self._anomalies
        if symbol:
            anomalies = [a for a in anomalies if a.symbol == symbol]
        return anomalies[-limit:]

    def clear_anomalies(self) -> None:
        self._anomalies.clear()

    def _validate_invariants(self, symbol: str, state: dict[str, Any]) -> bool:
        poc = state.get("poc", 0)
        val = state.get("val", 0)
        vah = state.get("vah", 0)

        if poc <= 0:
            self._record_anomaly(
                DataAnomaly(
                    symbol=symbol,
                    anomaly_type="INVARIANT_VIOLATION",
                    detail=f"POC={poc} — must be positive",
                )
            )
            return False
        if val >= poc:
            self._record_anomaly(
                DataAnomaly(
                    symbol=symbol,
                    anomaly_type="INVARIANT_VIOLATION",
                    detail=f"VAL ({val}) >= POC ({poc})",
                )
            )
            return False
        if poc >= vah:
            self._record_anomaly(
                DataAnomaly(
                    symbol=symbol,
                    anomaly_type="INVARIANT_VIOLATION",
                    detail=f"POC ({poc}) >= VAH ({vah})",
                )
            )
            return False

        vwap = state.get("sessionVwap", 0)
        if vwap < 0:
            self._record_anomaly(
                DataAnomaly(
                    symbol=symbol,
                    anomaly_type="INVARIANT_VIOLATION",
                    detail=f"VWAP={vwap} — must be non-negative",
                )
            )
            return False

        deviation = state.get("vwapDeviationSigmas", 0)
        vwap_upper_1 = state.get("vwapUpper1", 0)
        sigma = vwap_upper_1 - vwap
        if sigma > 0 and abs(deviation) > 10:
            self._record_anomaly(
                DataAnomaly(
                    symbol=symbol,
                    anomaly_type="VWAP_DEVIATION_EXTREME",
                    detail=f"VWAP deviation={deviation:.2f}σ — possible data mismatch",
                )
            )
            logger.warning(
                "StateBus: extreme VWAP deviation for %s: %.2fσ", symbol, deviation
            )

        return True

    def _record_anomaly(self, anomaly: DataAnomaly) -> None:
        self._anomalies.append(anomaly)
        if len(self._anomalies) > self._max_anomalies:
            self._anomalies = self._anomalies[-self._max_anomalies :]
        logger.warning(
            "StateBus ANOMALY [%s]: %s — %s",
            anomaly.anomaly_type,
            anomaly.symbol,
            anomaly.detail,
        )

