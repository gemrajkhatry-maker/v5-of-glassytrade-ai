from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class ExposureStatus(StrEnum):
    NONE = "NONE"
    OPEN = "OPEN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    CLOSE_PENDING = "CLOSE_PENDING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExposureState:
    status: ExposureStatus = ExposureStatus.NONE
    symbol: str = ""
    order_id: str = ""
    requested_qty: float = 0.0
    filled_qty: float = 0.0
    fill_price: float = 0.0

    @classmethod
    def none(cls) -> "ExposureState":
        return cls()

    @property
    def can_open_new_position(self) -> bool:
        return self.status is ExposureStatus.NONE

    def partial_entry(self, *, symbol: str, order_id: str, requested_qty: float,
                      filled_qty: float, fill_price: float) -> "ExposureState":
        if filled_qty <= 0 or filled_qty >= requested_qty:
            raise ValueError("partial_entry requires 0 < filled_qty < requested_qty")
        return replace(
            self,
            status=ExposureStatus.RECONCILIATION_REQUIRED,
            symbol=symbol,
            order_id=order_id,
            requested_qty=float(requested_qty),
            filled_qty=float(filled_qty),
            fill_price=float(fill_price),
        )

    def unknown_entry(self, *, symbol: str, order_id: str,
                      requested_qty: float, filled_qty: float = 0.0,
                      fill_price: float = 0.0) -> "ExposureState":
        return replace(
            self,
            status=ExposureStatus.RECONCILIATION_REQUIRED,
            symbol=symbol,
            order_id=order_id,
            requested_qty=float(requested_qty),
            filled_qty=float(filled_qty),
            fill_price=float(fill_price),
        )

    def reconcile(self, broker_state) -> "ExposureState":
        """Apply a broker snapshot; an unavailable snapshot preserves uncertainty."""
        if self.status is not ExposureStatus.RECONCILIATION_REQUIRED:
            return self
        if broker_state is None:
            return self
        status = str(broker_state.get("status", "")).upper()
        if status == "OPEN":
            return replace(
                self,
                status=ExposureStatus.OPEN,
                filled_qty=float(broker_state.get("filled_qty", self.filled_qty)),
                fill_price=float(broker_state.get("fill_price", self.fill_price)),
            )
        if status == "FLAT":
            return self.reconciled()
        return self

    def reconciled(self) -> "ExposureState":
        """Clear an exposure after an external paper/restart reconciliation."""
        if self.status is not ExposureStatus.RECONCILIATION_REQUIRED:
            raise ValueError("only reconciliation-required exposure can be cleared")
        return type(self).none()
