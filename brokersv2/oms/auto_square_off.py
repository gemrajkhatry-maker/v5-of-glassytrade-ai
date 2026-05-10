"""
Auto Square-Off Scheduler.

NSE regulation: brokers must square off all intraday (MIS/INTRADAY/MARGIN)
positions by 3:20 PM IST.  This scheduler fires a background coroutine that
monitors the clock and places offsetting MARKET orders for all open INTRADAY
positions once the threshold is reached.

Architecture note:
    - Runs as a long-lived background asyncio.Task (started from bootstrap.py).
    - After each square-off cycle it sleeps for 24 hours to avoid re-triggering
      on the same calendar day.
    - Uses IST timezone (Asia/Kolkata) for all time comparisons.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from zoneinfo import ZoneInfo

from brokersv2.core.constants import PositionReconciliation

if TYPE_CHECKING:
    from brokersv2.oms.position_reconciler import PositionBook

IST = ZoneInfo("Asia/Kolkata")
SQUARE_OFF_TIME_IST = time(
    PositionReconciliation.AUTO_SQUARE_OFF_HOUR, 
    PositionReconciliation.AUTO_SQUARE_OFF_MINUTE
)  # 3:20 PM IST

# Persist the last square-off date to this file so that a restart after
# 3:20 PM does not retrigger square-off on already-flat positions.
_DEFAULT_STATE_PATH = Path(
    os.environ.get("ASO_STATE_PATH", "/tmp/brokersv2_aso_state.txt")
)

logger = logging.getLogger(__name__)


def _read_persisted_date(path: Path) -> Optional[date]:
    """Return the date stored in the ASO state file, or None."""
    try:
        text = path.read_text().strip()
        return date.fromisoformat(text)
    except (FileNotFoundError, ValueError):
        return None


def _write_persisted_date(d: date, path: Path) -> None:
    """Write today's date to the ASO state file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(d.isoformat())
    except OSError as exc:
        logger.error("AutoSquareOff: cannot persist state to %s: %s", path, exc)


@dataclass(frozen=True)
class SquareOffEvent:
    """Audit record for a single auto-square-off action."""
    security_id: str
    exchange_segment: str
    side: str           # "SELL" (for long) or "BUY" (for short)
    quantity: int
    product_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(IST))
    status: str = "PENDING"   # PENDING / SENT / FAILED
    broker_order_id: Optional[str] = None
    error: Optional[str] = None


class AutoSquareOffScheduler:
    """
    Background task that triggers auto square-off at 15:20 IST.

    Usage::

        scheduler = AutoSquareOffScheduler()
        task = asyncio.ensure_future(scheduler.run(adapter, position_book))
        # task runs forever; cancel it on app shutdown
    """

    def __init__(
        self,
        check_interval_seconds: float = None,
        state_path: Optional[Path] = None,
    ) -> None:
        self._check_interval = check_interval_seconds or PositionReconciliation.CHECK_INTERVAL
        self._state_path = state_path or _DEFAULT_STATE_PATH
        # Restore persisted state — survives process restarts
        self._last_square_off_date: Optional[date] = _read_persisted_date(self._state_path)
        self._events: List[SquareOffEvent] = []

    async def run(self, adapter, position_book: "PositionBook", mapper=None) -> None:
        """
        Infinite loop: check the clock every ``check_interval_seconds``
        and trigger square-off at 15:20 IST on weekdays.

        Args:
            adapter: IBrokerAdapter — used to place offsetting orders.
            position_book: PositionBook from PositionReconciler.
            mapper: InstrumentMapper — required to resolve security_id →
                    CanonicalInstrument correctly.  If None, heuristic
                    resolution is attempted with a warning.
        """
        logger.info("AutoSquareOffScheduler started (fires at %s IST)", SQUARE_OFF_TIME_IST)

        while True:
            try:
                now_ist = datetime.now(IST)
                today = now_ist.date()

                already_done = (self._last_square_off_date == today)

                if (
                    not already_done
                    and now_ist.weekday() < 5  # Mon–Fri
                    and now_ist.time() >= SQUARE_OFF_TIME_IST
                ):
                    logger.warning(
                        "AutoSquareOff: time is %s >= %s — squaring off all INTRADAY positions",
                        now_ist.strftime("%H:%M:%S"),
                        SQUARE_OFF_TIME_IST,
                    )
                    await self._square_off_all_intraday(adapter, position_book, mapper)
                    self._last_square_off_date = today
                    _write_persisted_date(today, self._state_path)  # survive restarts
                    # Sleep until midnight to avoid spurious re-triggers
                    await asyncio.sleep(86400)
                    continue

            except Exception as exc:
                logger.error("AutoSquareOffScheduler error: %s", exc, exc_info=True)

            await asyncio.sleep(self._check_interval)

    async def _square_off_all_intraday(
        self, adapter, position_book: "PositionBook", mapper=None
    ) -> None:
        """Place offsetting MARKET orders for every open INTRADAY position."""
        intraday_positions = [
            p for p in position_book.all()
            if p.get("productType", "").upper() in ("INTRADAY", "MIS", "MARGIN")
            and int(p.get("netQty", 0)) != 0
        ]

        if not intraday_positions:
            logger.info("AutoSquareOff: no open INTRADAY positions to square off.")
            return

        logger.warning("AutoSquareOff: squaring off %d position(s).", len(intraday_positions))

        tasks = [
            self._square_off_position(adapter, pos, mapper)
            for pos in intraday_positions
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for pos, result in zip(intraday_positions, results):
            if isinstance(result, Exception):
                logger.error(
                    "AutoSquareOff FAILED for %s/%s: %s",
                    pos.get("exchangeSegment"), pos.get("securityId"), result,
                )

    async def _square_off_position(
        self, adapter, position: Dict[str, Any], mapper=None
    ) -> Optional[str]:
        """Place a single offsetting MARKET order and return the broker order ID."""
        from brokersv2.core.types import OrderSide, OrderType, ProductType, SecurityId
        from brokersv2.domain.order.models import Order
        from brokersv2.domain.instrument.models import CanonicalInstrument
        from brokersv2.core.types import OrderId
        import uuid
        from decimal import Decimal

        net_qty = int(position.get("netQty", 0))
        seg = position.get("exchangeSegment", "NSE_EQ")
        sec = str(position.get("securityId", ""))
        product_type_str = position.get("productType", "INTRADAY")

        if net_qty == 0:
            return None

        side = OrderSide.SELL if net_qty > 0 else OrderSide.BUY
        quantity = abs(net_qty)

        # Resolve canonical instrument via mapper (security_id → canonical)
        instrument = None
        if mapper is not None:
            instrument = mapper.security_id_to_canonical(SecurityId(sec))
        if instrument is None:
            # Mapper miss or not provided — log and skip rather than use bad data
            logger.error(
                "AutoSquareOff: cannot resolve security_id=%s in segment=%s — "
                "SKIPPING this position. Register it in the instrument registry.",
                sec, seg,
            )
            return None

        try:
            product_type = ProductType(product_type_str.upper())
        except ValueError:
            product_type = ProductType.INTRADAY

        order = Order(
            order_id=OrderId(str(uuid.uuid4())),
            instrument=instrument,
            side=side,
            quantity=Decimal(str(quantity)),
            order_type=OrderType.MARKET,
            product_type=product_type,
        )

        broker_order_id = await adapter.place_order(order)
        event = SquareOffEvent(
            security_id=sec,
            exchange_segment=seg,
            side=side.value,
            quantity=quantity,
            product_type=product_type.value,
            status="SENT",
            broker_order_id=broker_order_id,
        )
        self._events.append(event)
        logger.info(
            "AutoSquareOff: placed %s MARKET order for %s/%s qty=%d → broker_id=%s",
            side.value, seg, sec, quantity, broker_order_id,
        )
        return broker_order_id

    @property
    def events(self) -> List[SquareOffEvent]:
        """Return audit log of all square-off events."""
        return list(self._events)
