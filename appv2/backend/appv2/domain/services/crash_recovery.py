"""Crash Recovery — restores trading state from persistent storage on startup.

On restart:
1. Load last saved state from KV store
2. Reconcile positions with broker
3. Resume from last known good state
4. Alert on any unrecoverable discrepancies
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# KV store keys
KV_KEY_TRADES = "amt_trades_open"
KV_KEY_DAILY_PNL = "amt_daily_pnl"
KV_KEY_STATE_SNAPSHOT = "amt_state_snapshot"
KV_KEY_LAST_RECONCILIATION = "amt_last_reconciliation"


@dataclass(frozen=True)
class RecoveryResult:
    success: bool
    trades_restored: int
    state_restored: bool
    broker_mismatch: bool
    discrepancies: list[str]


class CrashRecoveryManager:
    """Manages crash recovery from persistent storage."""

    def __init__(self, storage):
        """
        Args:
            storage: StoragePort implementation with kv_get/kv_set
        """
        self._storage = storage

    async def recover(
        self,
        broker_positions: list[dict],
        broker_balance: float,
    ) -> RecoveryResult:
        """Recover state from last saved snapshot.

        Args:
            broker_positions: Current positions from broker
            broker_balance: Current balance from broker

        Returns:
            RecoveryResult with recovery status
        """
        discrepancies: list[str] = []
        trades_restored = 0
        state_restored = False

        # 1. Load open trades from KV store
        saved_trades = await self._load_open_trades()
        trades_restored = len(saved_trades)

        if saved_trades:
            logger.info("Recovered %d open trades from storage", trades_restored)

        # 2. Reconcile with broker positions
        internal_symbols = set(t.get("symbol", "") for t in saved_trades)
        broker_symbols = set(p.get("symbol", "") for p in broker_positions)

        # Check for internal trades not on broker
        for sym in internal_symbols:
            if sym not in broker_symbols:
                discrepancies.append(
                    f"Trade for {sym} exists internally but not on broker"
                )

        # Check for broker positions not tracked internally
        for sym in broker_symbols:
            if sym not in internal_symbols:
                discrepancies.append(
                    f"Broker has position for {sym} not tracked internally"
                )

        # 3. Load daily P&L
        saved_pnl = await self._load_daily_pnl()
        if saved_pnl is not None:
            logger.info("Recovered daily P&L: ₹%.2f", saved_pnl)

        # 4. Load state snapshot
        snapshot = await self._load_state_snapshot()
        if snapshot:
            state_restored = True
            logger.info("Restored AMT state snapshot from %s", snapshot.get("timestamp", "unknown"))

        # 5. Reconcile balance
        if broker_balance > 0:
            saved_balance = snapshot.get("balance", 0) if snapshot else 0
            if saved_balance > 0:
                balance_diff = abs(broker_balance - saved_balance)
                if balance_diff > saved_balance * 0.01:  # >1% difference
                    discrepancies.append(
                        f"Balance mismatch: saved=₹{saved_balance:.0f}, broker=₹{broker_balance:.0f}"
                    )

        # 6. Save reconciliation timestamp
        await self._save_reconciliation_time()

        success = len(discrepancies) == 0
        if not success:
            logger.warning("Crash recovery completed with %d discrepancies: %s",
                          len(discrepancies), discrepancies)
        else:
            logger.info("Crash recovery successful — %d trades restored", trades_restored)

        return RecoveryResult(
            success=success,
            trades_restored=trades_restored,
            state_restored=state_restored,
            broker_mismatch=len(discrepancies) > 0,
            discrepancies=discrepancies,
        )

    async def save_state(
        self,
        open_trades: list[dict],
        daily_pnl: float,
        snapshot: dict,
    ) -> None:
        """Save current state to KV store for crash recovery."""
        await self._save_open_trades(open_trades)
        await self._save_daily_pnl(daily_pnl)
        await self._save_state_snapshot(snapshot)

    async def _load_open_trades(self) -> list[dict]:
        try:
            data = await self._storage.kv_get(KV_KEY_TRADES)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error("Failed to load trades: %s", e)
        return []

    async def _save_open_trades(self, trades: list[dict]) -> None:
        try:
            await self._storage.kv_set(KV_KEY_TRADES, json.dumps(trades))
        except Exception as e:
            logger.error("Failed to save trades: %s", e)

    async def _load_daily_pnl(self) -> float | None:
        try:
            data = await self._storage.kv_get(KV_KEY_DAILY_PNL)
            if data:
                return float(data)
        except Exception as e:
            logger.error("Failed to load daily P&L: %s", e)
        return None

    async def _save_daily_pnl(self, pnl: float) -> None:
        try:
            await self._storage.kv_set(KV_KEY_DAILY_PNL, str(pnl))
        except Exception as e:
            logger.error("Failed to save daily P&L: %s", e)

    async def _load_state_snapshot(self) -> dict | None:
        try:
            data = await self._storage.kv_get(KV_KEY_STATE_SNAPSHOT)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error("Failed to load state snapshot: %s", e)
        return None

    async def _save_state_snapshot(self, snapshot: dict) -> None:
        try:
            snapshot["timestamp"] = time.time()
            await self._storage.kv_set(
                KV_KEY_STATE_SNAPSHOT, json.dumps(snapshot)
            )
        except Exception as e:
            logger.error("Failed to save state snapshot: %s", e)

    async def _save_reconciliation_time(self) -> None:
        try:
            await self._storage.kv_set(
                KV_KEY_LAST_RECONCILIATION, str(time.time())
            )
        except Exception as e:
            logger.error("Failed to save reconciliation time: %s", e)
