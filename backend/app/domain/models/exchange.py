"""Exchange enumeration with normalization utility.

Centralizes exchange name normalization (e.g., NFO -> NSE mapping)
to eliminate duplicated logic across service_graph.py, session_event_router.py,
and llm_entry_handler.py.
"""

from __future__ import annotations

from enum import Enum


class Exchange(Enum):
    """Supported trading exchanges."""

    MCX = "MCX"
    NSE = "NSE"

    @classmethod
    def normalize(cls, name: str | object) -> "Exchange":
        """Normalize an exchange name to a canonical Exchange enum value.

        Handles common aliases:
            NFO -> NSE  (NSE F&O segment uses NSE strategy)

        Args:
            name: Exchange name string or object with __str__.

        Returns:
            The canonical Exchange enum value.

        Raises:
            ValueError: If the exchange name is not recognized.
        """
        normalized = str(name).upper().strip()
        if normalized == "NFO":
            normalized = "NSE"
        try:
            return cls[normalized]
        except KeyError:
            raise ValueError(
                f"Unknown exchange: {name!r}. "
                f"Supported: {[e.value for e in cls]}"
            ) from None

    @property
    def strategy_name(self) -> str:
        """Return the strategy class name for this exchange."""
        return f"{self.value}ExchangeStrategy"
