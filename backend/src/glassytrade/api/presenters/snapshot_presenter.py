"""Read-only projection presenters for versioned API output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from glassytrade.api.websocket.protocol import ProjectionEnvelope, validate_ws_message


class SnapshotPresenter:
    def __init__(
        self,
        *,
        projection_id: str,
        release_id: str,
        config_fingerprint: str,
        mode: str,
        projection_version: int = 1,
    ) -> None:
        if mode not in {"shadow", "paper", "live"}:
            raise ValueError("unsupported presentation mode")
        self.projection_id = projection_id
        self.release_id = release_id
        self.config_fingerprint = config_fingerprint
        self.mode = mode
        self.projection_version = projection_version

    def _envelope(
        self,
        *,
        sequence: int,
        payload: Mapping[str, Any],
        scope: Mapping[str, Any],
        message_type: str = "snapshot",
        base_sequence: int | None = None,
    ) -> dict[str, Any]:
        message = ProjectionEnvelope(
            schema_version="1.0",
            projection_version=self.projection_version,
            projection_id=self.projection_id,
            scope=scope,
            sequence=sequence,
            base_sequence=base_sequence,
            as_of=datetime.now(timezone.utc).isoformat(),
            release_id=self.release_id,
            config_fingerprint=self.config_fingerprint,
            mode=self.mode,
            type=message_type,
            payload=payload,
        ).to_dict()
        return validate_ws_message(message)

    def runtime_snapshot(self, *, sequence: int, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._envelope(
            sequence=sequence,
            payload=payload,
            scope={"type": "runtime"},
        )

    def portfolio_snapshot(
        self, *, sequence: int, account_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._envelope(
            sequence=sequence,
            payload=payload,
            scope={"type": "portfolio", "accountId": account_id},
        )

    def delta(
        self,
        *,
        base_sequence: int,
        sequence: int,
        payload: Mapping[str, Any],
        scope: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._envelope(
            sequence=sequence,
            base_sequence=base_sequence,
            payload=payload,
            scope=scope or {"type": "runtime"},
            message_type="delta",
        )
