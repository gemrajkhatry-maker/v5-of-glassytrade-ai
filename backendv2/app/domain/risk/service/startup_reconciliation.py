"""Startup reconciliation for persisted open positions."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.domain.trading.model.aggregates import Portfolio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationResult:
    """Result of startup reconciliation."""

    db_positions: int
    broker_positions: int
    restored: int
    stale_removed: int
    orphaned_registered: int
    discrepancies: list[str]


StartupReconciliationResult = ReconciliationResult


class StartupReconciliation:
    """Verifies DB positions against broker API at startup.

    Called once during engine startup, before live tick processing.
    Ensures persisted state and broker state are aligned.
    """

    def __init__(
        self,
        broker_adapter=None,
        storage=None,
    ) -> None:
        self._broker = broker_adapter
        self._storage = storage

    def reconcile(self, portfolio: Portfolio | None = None) -> ReconciliationResult:
        """Run startup reconciliation.

        Returns:
            ReconciliationResult with counts of restored/stale/orphaned positions.
        """
        discrepancies = []

        db_positions = []
        if self._storage is not None:
            try:
                db_positions = self._storage.load_open_positions()
            except Exception as e:
                logger.error("Startup reconciliation: failed to load DB positions: %s", e)
                discrepancies.append(f"DB load failed: {e}")

        broker_positions = []
        try:
            broker_positions = self._load_broker_positions()
        except Exception as e:
            logger.warning("Startup reconciliation: failed to query broker API: %s", e)
            discrepancies.append(f"Broker API query failed: {e}")

        db_symbols = {_normalize_symbol(pos.get("symbol", "")) for pos in db_positions}
        broker_symbols = {_normalize_symbol(self._extract_underlying(pos)) for pos in broker_positions}
        broker_symbols.discard("")

        restored = 0
        stale_removed = 0
        orphaned_registered = 0

        for pos in db_positions:
            symbol = _normalize_symbol(pos.get("symbol", ""))
            if symbol in broker_symbols:
                restored += 1
                if portfolio is not None:
                    self._hydrate_position(portfolio, pos)
            else:
                stale_removed += 1
                discrepancies.append(
                    f"Stale: {symbol} in DB but not at broker — removing from DB",
                )
                if self._storage:
                    try:
                        self._storage.delete_open_position(pos.get("id", ""))
                    except (KeyError, TypeError):
                        logger.debug(
                            "Failed to delete stale open position %s", pos.get("id"),
                            exc_info=True,
                        )

        for pos in broker_positions:
            symbol = _normalize_symbol(self._extract_underlying(pos))
            if not symbol or symbol in db_symbols:
                continue
            orphaned_registered += 1
            discrepancies.append(
                f"Orphaned: {symbol} at broker but not in DB — registered as external",
            )

        logger.info(
            "Startup reconciliation: DB=%d broker=%d restored=%d stale=%d orphaned=%d",
            len(db_positions),
            len(broker_positions),
            restored,
            stale_removed,
            orphaned_registered,
        )

        return ReconciliationResult(
            db_positions=len(db_positions),
            broker_positions=len(broker_positions),
            restored=restored,
            stale_removed=stale_removed,
            orphaned_registered=orphaned_registered,
            discrepancies=discrepancies,
        )

    def _load_broker_positions(self) -> list[object]:
        if not self._broker:
            return []

        raw_positions = []
        if hasattr(self._broker, "get_positions"):
            raw_positions = self._invoke_adapter_result("get_positions")
        elif hasattr(self._broker, "get_account_positions"):
            raw_positions = self._invoke_adapter_result("get_account_positions")
        elif hasattr(self._broker, "get_account"):
            account = self._invoke_adapter_result("get_account")
            raw_positions = _extract_positions_from_account(account)
        elif hasattr(self._broker, "positions"):
            attr = getattr(self._broker, "positions")
            raw_positions = list(attr) if isinstance(attr, (list, tuple)) else _extract_positions_from_account(attr)
        elif hasattr(self._broker, "get_position"):
            # Some brokers expose only per-symbol queries; no global reconciliation possible.
            return []

        return _coerce_position_list(raw_positions)

    def _hydrate_position(self, portfolio: Portfolio, position_data: dict[str, object]) -> None:
        if not isinstance(position_data, dict):
            return
        if not portfolio:
            return
        symbol = _normalize_symbol(position_data.get("symbol", ""))
        if not symbol:
            return
        try:
            portfolio.recover_position(position_data)
        except Exception:
            logger.debug("Failed to restore portfolio position for %s", symbol, exc_info=True)

    def _invoke_adapter_result(self, method: str) -> Any:
        callable_obj = getattr(self._broker, method)
        if inspect.iscoroutinefunction(callable_obj):
            return _execute_sync(lambda: callable_obj())

        result = callable_obj()
        if inspect.isawaitable(result):
            return _execute_sync(lambda: result)
        return result

    @staticmethod
    def _extract_underlying(broker_position: object) -> str:
        if isinstance(broker_position, dict):
            for key in ("trading_symbol", "symbol"):
                value = broker_position.get(key, "")
                if isinstance(value, str) and value.strip():
                    return value
        if hasattr(broker_position, "trading_symbol"):
            return str(getattr(broker_position, "trading_symbol", ""))
        if hasattr(broker_position, "symbol"):
            return str(getattr(broker_position, "symbol", ""))
        if hasattr(broker_position, "underlying"):
            return str(getattr(broker_position, "underlying", ""))
        return ""


def _execute_sync(factory: Callable[[], Any]) -> Any:
    """Execute an awaitable in sync context with safe loop handling."""
    awaitable = factory()
    if not inspect.isawaitable(awaitable):
        return awaitable

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    if not loop.is_running():
        return loop.run_until_complete(awaitable)

    # Running loop in current thread (e.g. lifecycle hooks). Run in a worker thread
    # with a fresh loop, avoiding RuntimeError from nested run_until_complete.
    def _runner(awaitable_factory: Callable[[], Any]) -> Any:
        return asyncio.run(awaitable_factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        return list(executor.map(_runner, [factory]))[0]


def _coerce_position_list(raw_positions: object) -> list[object]:
    if raw_positions is None:
        return []
    if isinstance(raw_positions, list):
        return raw_positions
    if isinstance(raw_positions, tuple):
        return list(raw_positions)
    if isinstance(raw_positions, dict):
        if "positions" in raw_positions and isinstance(raw_positions["positions"], list):
            return raw_positions["positions"]
        if "open_positions" in raw_positions and isinstance(raw_positions["open_positions"], list):
            return raw_positions["open_positions"]
        return []
    return []


def _extract_positions_from_account(account: object) -> list[object]:
    if account is None:
        return []
    if isinstance(account, list):
        return account
    if isinstance(account, tuple):
        return list(account)
    if isinstance(account, dict):
        if isinstance(account.get("positions"), list):
            return account["positions"]
        if isinstance(account.get("open_positions"), list):
            return account["open_positions"]
    return []


def _normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper()
