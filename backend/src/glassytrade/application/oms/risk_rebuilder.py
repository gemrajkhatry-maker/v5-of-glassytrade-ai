"""Deterministic risk-state rebuild from durable OMS rows."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from glassytrade.domain.execution.types import RiskState


class RiskRebuilder:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def rebuild(self, account_id: str = "oms") -> RiskState:
        reserved_row = self.connection.execute(
            "SELECT COALESCE(SUM(r.amount), 0) FROM risk_reservations r "
            "WHERE r.status NOT IN ('RELEASED', 'PARTIALLY_RELEASED') "
            "AND NOT EXISTS (SELECT 1 FROM fills f WHERE f.intent_id = r.intent_id)"
        ).fetchone()
        committed_row = self.connection.execute(
            "SELECT COALESCE(SUM(r.amount), 0) FROM risk_reservations r "
            "WHERE r.status NOT IN ('RELEASED') "
            "AND EXISTS (SELECT 1 FROM fills f WHERE f.intent_id = r.intent_id)"
        ).fetchone()
        fill_row = self.connection.execute(
            "SELECT COALESCE(SUM(CAST(fees AS REAL)), 0) FROM fills"
        ).fetchone()
        return RiskState(
            account_id=account_id,
            reserved_risk=Decimal(str(reserved_row[0] or 0)),
            committed_risk=Decimal(str(committed_row[0] or 0)),
            realized_pnl=Decimal("-1") * Decimal(str(fill_row[0] or 0)),
            daily_loss=Decimal("0"),
            consecutive_losses=0,
            kill_switch=False,
        )
