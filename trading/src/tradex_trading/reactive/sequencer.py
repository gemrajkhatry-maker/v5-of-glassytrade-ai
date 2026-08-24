"""Per-instrument monotonic-time sequencer for market-data messages.

Live WebSocket ticks can be re-published or reordered; a downstream
candle/delta aggregator silently corrupts its state on either. This guard
enforces a strict per-instrument monotonic timestamp for ``Quote`` / ``Candle``
/ ``Depth``, dropping any message that is not strictly newer than the last
accepted one. Commands, fills, and other events are never sequenced (they must
not be reordered or deduped) — route only market data through this.
"""

from __future__ import annotations

from datetime import datetime

from tradex_domain.market import Candle, Depth, Quote

_SEQUENCED_TYPES = (Candle, Quote, Depth)


class MarketDataSequencer:
    """Drops duplicate and out-of-order market-data messages per instrument."""

    def __init__(self) -> None:
        self._last: dict[tuple[str, type], datetime] = {}

    def accept(self, message: object) -> bool:
        """Return True when *message* should be published.

        Non-market-data messages always pass. For ``Quote``/``Candle``/
        ``Depth``, a message whose timestamp is not strictly newer than the
        last accepted message of the same instrument+type is a duplicate or
        reordered frame and is dropped. Untimestamped messages pass (there is
        nothing to sequence).
        """
        if not isinstance(message, _SEQUENCED_TYPES):
            return True
        ts = getattr(message, "timestamp", None)
        if ts is None:
            return True
        instrument = getattr(message, "instrument", None)
        iid = getattr(instrument, "instrument_id", None)
        key = (str(iid), type(message))
        last = self._last.get(key)
        if last is not None and ts <= last:
            return False
        self._last[key] = ts
        return True


__all__ = ["MarketDataSequencer"]
