from __future__ import annotations
from quantv2.types import Bar

_EPS = 1e-9


class SecondDrive:
    """Fabio second-drive continuation (fabio_decision_pipeline.md L104/L114).

    D1 probes the level and rejects (wick through, close back at the level —
    "don't take the first drive, you can get tapped in a fake out").
    Entry when the 1m close goes back beyond the rejected probe level:
    LONG above, SHORT below. Drives are counted; ignored once drives >= max_drives
    (drive exhausted: drive_number >= 3, L104).
    """

    def __init__(self, max_drives: int = 3, tick: float = 0.05) -> None:
        self.max_drives = max_drives
        self.tick = tick if tick > 0 else 0.05
        self.tol = 2 * self.tick + _EPS
        self.drives = 0
        self.active = True
        self._armed: str | None = None  # rejected probe side awaiting reclaim: "UP" | "DOWN"

    def on_bar(self, bar: Bar, level: float) -> dict | None:
        if not self.active:
            return None
        if self._armed == "UP":
            if bar.close > level:
                self._armed = None
                return {"drive_number": self.drives, "reclaimed": True, "direction": "LONG"}
            if bar.close < level - self.tol:
                self._armed = None  # rejected probe level lost — no reclaim to wait for
            return None
        if self._armed == "DOWN":
            if bar.close < level:
                self._armed = None
                return {"drive_number": self.drives, "reclaimed": True, "direction": "SHORT"}
            if bar.close > level + self.tol:
                self._armed = None
            return None
        side = self._probe_side(bar, level)
        if side is None:
            return None
        if self.drives >= self.max_drives:
            self.active = False
            return None
        self.drives += 1
        self._armed = side
        return None

    def _probe_side(self, bar: Bar, level: float) -> str | None:
        at_level = abs(bar.close - level) <= self.tol
        up = bar.high > level and at_level
        dn = bar.low < level and at_level
        if up and dn:
            return "UP" if bar.high - level >= level - bar.low else "DOWN"
        return "UP" if up else ("DOWN" if dn else None)
