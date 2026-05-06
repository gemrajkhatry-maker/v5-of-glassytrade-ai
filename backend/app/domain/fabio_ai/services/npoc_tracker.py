"""NPOC Tracker — domain service for tracking naked (unfilled) previous session POCs.

Per Fabio methodology, previous session POCs that haven't been revisited
act as price magnets and potential secondary targets for P3 trailing.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.domain.ports.npoc import INPOC as NPOCPort, NPOCRecord, NPOCResult
from app.core.async_boundary import ensure_sync_adapter_result

logger = logging.getLogger(__name__)


class NPOCTracker(NPOCPort):
    """Tracks naked (unfilled) previous session POCs per Fabio methodology.

    NPOCs are session POCs that price has not revisited. They act as magnets
    and can serve as secondary targets for P3 trailing exits.

    Lifecycle:
        1. At session close: add_session_poc() stores the POC
        2. On every tick: check_and_fill() marks NPOCs as filled when price
           trades within 2 ticks
        3. On signal generation: get_active_npocs() returns nearest NPOCs
           above/below current price for target calculation
    """

    def __init__(self, storage_port) -> None:
        """Initialize with a storage port for persistence.

        Args:
            storage_port: Must implement save_npoc, mark_npoc_filled,
                and get_active_npocs methods (added to SQLiteStorageAdapter).
        """
        self._storage = storage_port
        # In-memory cache: underlying -> list of NPOCRecord
        self._active_npocs: dict[str, list[NPOCRecord]] = {}

    def add_session_poc(self, underlying: str, date: str, poc: float) -> None:
        """Record a session's POC as a new NPOC.

        Called at session close to save the POC for future tracking.
        Persists to storage and adds to in-memory cache.

        Args:
            underlying: The underlying symbol (e.g., "NIFTY", "BANKNIFTY").
            date: Session date in "YYYY-MM-DD" format.
            poc: The session's Point of Control price.
        """
        record = NPOCRecord(
            price=poc,
            session_date=date,
            underlying=underlying,
            is_filled=False,
            filled_at=None,
        )

        if underlying not in self._active_npocs:
            self._active_npocs[underlying] = []

        # Prevent duplicate entries for the same session
        existing_dates = {r.session_date for r in self._active_npocs[underlying]}
        if date in existing_dates:
            logger.debug(
                "NPOC already tracked for %s on %s — skipping duplicate",
                underlying, date,
            )
            return

        self._active_npocs[underlying].append(record)
        ensure_sync_adapter_result(
            "storage.save_npoc",
            self._storage.save_npoc,
            underlying,
            date,
            poc,
        )
        logger.info(
            "NPOC added: %s @ %.2f (session %s)",
            underlying, poc, date,
        )

    def check_and_fill(
        self, underlying: str, current_price: float, tick_size: float
    ) -> list[str]:
        """Check all active NPOCs and mark as filled if price is within 2 ticks.

        An NPOC is considered "filled" when price trades within 2 ticks of the
        NPOC price level. Once filled, it is removed from active tracking.

        Args:
            underlying: The underlying symbol.
            current_price: Current market price.
            tick_size: Minimum price increment for the instrument.

        Returns:
            List of session dates whose NPOCs were just filled.
        """
        if underlying not in self._active_npocs:
            return []

        zone = tick_size * 2
        filled_dates: list[str] = []
        remaining: list[NPOCRecord] = []

        for npoc in self._active_npocs[underlying]:
            if npoc.is_filled:
                continue  # Skip already filled

            if abs(current_price - npoc.price) <= zone:
                # Mark as filled
                filled_dates.append(npoc.session_date)
                ensure_sync_adapter_result(
                    "storage.mark_npoc_filled",
                    self._storage.mark_npoc_filled,
                    underlying,
                    npoc.session_date,
                    datetime.now().isoformat(),
                )
                logger.info(
                    "NPOC filled: %s @ %.2f (session %s) — price %.2f within %.4f zone",
                    underlying, npoc.price, npoc.session_date,
                    current_price, zone,
                )
            else:
                remaining.append(npoc)

        self._active_npocs[underlying] = remaining
        return filled_dates

    def get_active_npocs(
        self, underlying: str, current_price: float, lookback_days: int = 5
    ) -> NPOCResult:
        """Return nearest unfilled NPOCs above and below current price.

        Used for secondary target calculation in P3 trailing. Returns the
        closest NPOC above (resistance magnet) and below (support magnet).

        Args:
            underlying: The underlying symbol.
            current_price: Current market price.
            lookback_days: Maximum number of active NPOCs to consider.

        Returns:
            NPOCResult with nearest_above, nearest_below, and all active NPOCs.
        """
        active = [
            n for n in self._active_npocs.get(underlying, [])
            if not n.is_filled
        ]

        # Sort by recency (most recent first) and limit by lookback
        active.sort(key=lambda x: x.session_date, reverse=True)
        active = active[:lookback_days]

        above = [n for n in active if n.price > current_price]
        below = [n for n in active if n.price < current_price]

        return NPOCResult(
            nearest_above=min(above, key=lambda x: x.price) if above else None,
            nearest_below=max(below, key=lambda x: x.price) if below else None,
            all_active=tuple(active),
        )

    def load_from_storage(self, underlying: str) -> None:
        """Load active NPOCs from persistent storage on startup.

        Recovers unfilled NPOCs from the database after a crash or restart.

        Args:
            underlying: The underlying symbol to load NPOCs for.
        """
        records = ensure_sync_adapter_result(
            "storage.get_active_npocs",
            self._storage.get_active_npocs,
            underlying,
        )
        if records:
            self._active_npocs[underlying] = [
                NPOCRecord(
                    price=r["poc_price"],
                    session_date=r["session_date"],
                    underlying=r["underlying"],
                    is_filled=bool(r["is_filled"]),
                    filled_at=r.get("filled_at"),
                )
                for r in records
            ]
            logger.info(
                "NPOC: loaded %d active records for %s from storage",
                len(self._active_npocs[underlying]), underlying,
            )
        else:
            self._active_npocs.setdefault(underlying, [])
            logger.debug("NPOC: no active records in storage for %s", underlying)

    @property
    def active_npocs(self) -> dict[str, list[NPOCRecord]]:
        """Read-only access to in-memory NPOC cache."""
        return dict(self._active_npocs)
