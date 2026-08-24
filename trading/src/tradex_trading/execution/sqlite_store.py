"""SQLite-backed persistent order store and idempotency guard."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from tradex_domain.enums import OrderSide, OrderStatus, OrderType, ProductType, TimeInForce
from tradex_domain.execution import Order
from tradex_domain.instruments import Instrument
from tradex_domain.value_objects import CorrelationId, OrderId, Price, Quantity

# Single source of truth for the column layout — keeps CREATE / INSERT /
# SELECT in lockstep so a schema change can't silently desync row shape.
_COLUMNS = (
    "order_id", "symbol", "exchange", "asset_class", "side", "order_type",
    "quantity", "price", "time_in_force", "status", "filled_quantity",
    "product_type", "tag", "correlation_id", "expiry", "strike", "option_type",
)


def _order_to_row(order: Order) -> tuple:
    """Serialize an Order into a flat tuple for SQLite storage."""
    inst = order.instrument
    return (
        order.order_id.value,
        inst.symbol,
        inst.exchange.value,
        inst.asset_class.value,
        order.side.value,
        order.order_type.value,
        str(order.quantity.value),
        str(order.price.value) if order.price else None,
        order.time_in_force.value,
        order.status.value,
        str(order.filled_quantity.value),
        order.product_type.value,
        order.tag,
        str(order.correlation_id.value) if order.correlation_id else None,
        inst.expiry.isoformat() if inst.expiry else None,
        str(inst.strike) if inst.strike is not None else None,
        inst.option_type,
    )


def _row_to_order(row: tuple) -> Order:
    """Deserialize a SQLite row back into an Order."""
    from datetime import date
    from decimal import Decimal

    from tradex_domain.enums import AssetClass, ExchangeId
    from tradex_domain.instruments import Commodity, Currency, Equity, Future, Index, Option
    from tradex_domain.value_objects import CorrelationId, InstrumentId

    (
        order_id, symbol, exchange, asset_class, side, order_type,
        quantity, price, time_in_force, status, filled_qty,
        product_type, tag, correlation_id, expiry, strike, option_type,
    ) = row

    expiry_date = date.fromisoformat(expiry) if expiry else None
    strike_dec = Decimal(strike) if strike else None

    # Reconstruct instrument — FUTURE/OPTION carry expiry/strike/right, the
    # other asset classes are keyed by (exchange, symbol) only.
    instrument: Instrument
    if asset_class == "FUTURE" and expiry_date is not None:
        instrument = Future.of(exchange, symbol, expiry_date)
    elif (
        asset_class == "OPTION"
        and expiry_date is not None
        and strike_dec is not None
        and option_type
    ):
        instrument = Option.of(exchange, symbol, expiry_date, strike_dec, option_type)
    elif asset_class == "EQUITY":
        instrument = Equity.of(exchange, symbol)
    elif asset_class == "INDEX":
        instrument = Index.of(exchange, symbol)
    elif asset_class == "CURRENCY":
        instrument = Currency.of(exchange, symbol)
    elif asset_class == "COMMODITY":
        instrument = Commodity.of(exchange, symbol)
    else:
        # Unknown / incomplete derivative: generic Instrument carrying the
        # fields we do have, so identity is never silently rewired to equity.
        instrument = Instrument(
            instrument_id=InstrumentId.equity(exchange, symbol),
            symbol=symbol,
            exchange=ExchangeId(exchange),
            asset_class=AssetClass(asset_class),
            expiry=expiry_date,
            strike=strike_dec,
            option_type=option_type,
        )

    return Order(
        order_id=OrderId(value=order_id),
        instrument=instrument,
        side=OrderSide(side),
        order_type=OrderType(order_type),
        quantity=Quantity(value=Decimal(quantity)),
        price=Price(value=Decimal(price)) if price else None,
        time_in_force=TimeInForce(time_in_force),
        status=OrderStatus(status),
        filled_quantity=Quantity(value=Decimal(filled_qty)),
        product_type=ProductType(product_type),
        tag=tag,
        correlation_id=CorrelationId(value=correlation_id) if correlation_id else None,
    )


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection; ``check_same_thread=False`` so the store can be
    shared across the live bus's worker threads (all access is guarded by the
    owning object's lock)."""
    path = str(db_path) if db_path != ":memory:" else ":memory:"
    return sqlite3.connect(path, check_same_thread=False)


class SQLiteOrderStore:
    """Persistent order store using SQLite (thread-safe)."""

    _CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        exchange TEXT NOT NULL,
        asset_class TEXT NOT NULL,
        side TEXT NOT NULL,
        order_type TEXT NOT NULL,
        quantity TEXT NOT NULL,
        price TEXT,
        time_in_force TEXT NOT NULL,
        status TEXT NOT NULL,
        filled_quantity TEXT NOT NULL,
        product_type TEXT NOT NULL,
        tag TEXT,
        correlation_id TEXT,
        expiry TEXT,
        strike TEXT,
        option_type TEXT
    )
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = _connect(db_path)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute(self._CREATE_TABLE)
            self._conn.commit()

    def save_order(self, order: Order) -> None:
        """Insert or update an order."""
        row = _order_to_row(order)
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join("?" for _ in _COLUMNS)
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO orders ({cols}) VALUES ({placeholders})",
                row,
            )
            self._conn.commit()

    def upsert(self, order: Order) -> None:
        """Insert or update an order (alias for ``save_order``)."""
        self.save_order(order)

    def get(self, order_id: OrderId | str) -> Order | None:
        """Return the order with the given id, or None.

        Accepts an ``OrderId`` value object or a plain string.
        """
        key = order_id.value if isinstance(order_id, OrderId) else order_id
        return self.get_order(key)

    def get_order(self, order_id: str) -> Order | None:
        """Return the order with the given id, or None."""
        cols = ", ".join(_COLUMNS)
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT {cols} FROM orders WHERE order_id = ?",
                (order_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_order(row)

    def all_orders(self) -> list[Order]:
        """Return all stored orders."""
        cols = ", ".join(_COLUMNS)
        with self._lock:
            cursor = self._conn.execute(f"SELECT {cols} FROM orders")
            rows = cursor.fetchall()
        return [_row_to_order(row) for row in rows]

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()


class SQLiteIdempotencyGuard:
    """Prevents duplicate order submission using a SQLite-backed set.

    Implements the IdempotencyGuard protocol with reservation + release.
    Thread-safe, and semantically identical to ``MemoryIdempotencyGuard``: an
    already-``reserved`` key raises instead of silently allowing a second
    in-flight submit through.
    """

    _CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS idempotency (
        correlation_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'reserved',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = _connect(db_path)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute(self._CREATE_TABLE)
            self._conn.commit()

    def check_and_reserve(
        self, correlation_id: CorrelationId,
    ) -> object | None:
        """Reserve a correlation id.

        Returns ``None`` when *new*, an ``IdempotencyDuplicate`` when already
        completed, and raises ``RuntimeError`` when already reserved (parity
        with ``MemoryIdempotencyGuard``).
        """
        from tradex_trading.execution.engine import IdempotencyDuplicate

        key = str(correlation_id.value)
        with self._lock:
            cursor = self._conn.execute(
                "SELECT status FROM idempotency WHERE correlation_id = ?",
                (key,),
            )
            row = cursor.fetchone()
            if row is not None:
                if row[0] == "completed":
                    return IdempotencyDuplicate(result=key)
                raise RuntimeError(f"idempotency key is already reserved: {key}")
            self._conn.execute(
                "INSERT INTO idempotency (correlation_id, status) VALUES (?, 'reserved')",
                (key,),
            )
            self._conn.commit()
        return None

    def record_result(self, correlation_id: CorrelationId, result: object) -> None:
        """Mark a reserved correlation id as completed."""
        key = str(correlation_id.value)
        with self._lock:
            self._conn.execute(
                "UPDATE idempotency SET status = 'completed' WHERE correlation_id = ?",
                (key,),
            )
            self._conn.commit()

    def release(self, correlation_id: CorrelationId) -> None:
        """Release a reserved (but not completed) correlation id."""
        key = str(correlation_id.value)
        with self._lock:
            self._conn.execute(
                "DELETE FROM idempotency WHERE correlation_id = ? AND status = 'reserved'",
                (key,),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()


__all__ = ["SQLiteIdempotencyGuard", "SQLiteOrderStore"]
