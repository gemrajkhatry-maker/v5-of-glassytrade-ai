"""Volume profile: POC, value area, and LVN troughs (AMT §5).

Port of quant/amt/profile/volume_profile.py — CME two-row-pairs contiguous
two-sided expansion around the POC (never greedy-by-volume) with the volume
desert gap guard — plus the AMT §5 LVN rule: consecutive bins whose mass is
below ratio × the flanking shelf mass. Stdlib only, no v1 imports.
"""

from __future__ import annotations

import math


class VolumeProfile:
    """Volume-at-price histogram on a fixed tick grid, one instance per session.

    Bins are keyed by their lower grid price: floor(price / tick) × tick.
    POC = max-volume bin, lowest price wins ties. VAH/VAL grow contiguously
    outward from the POC bin until the value-area fraction of total mass is
    reached, comparing two-row pair averages per side; a side whose next pair
    is under 1% of the POC bin (volume desert) is closed. VAH/VAL/poc report
    bin grid keys. LVNs are maximal runs of consecutive bins each below
    min_ratio × the nearest unmarked shelf mass on either side, reported as
    (lo, hi) grid-key ranges of at least min_width bins. Not thread-safe.
    """

    def __init__(self, tick: float, value_area_pct: float = 0.70) -> None:
        if tick <= 0:
            raise ValueError("tick must be positive")
        self._tick = float(tick)
        self._value_area_pct = float(value_area_pct)
        self._bins: dict[int, float] = {}
        self._layer: str | None = None

    def on_price_volume(self, price: float, qty: float) -> None:
        """Accumulate qty traded at price into the histogram."""
        qty = float(qty)
        if qty <= 0:
            return
        idx = math.floor(float(price) / self._tick)
        self._bins[idx] = self._bins.get(idx, 0.0) + qty

    def layer(self, tag: str | None = None) -> str | None:
        """Carried layer tag (session/box/impulse); set with layer(tag)."""
        if tag is not None:
            self._layer = tag
        return self._layer

    def lvns(self, min_ratio: float = 0.3, min_width: int = 1) -> list[tuple[float, float]]:
        """Low-volume nodes as (lo, hi) grid-key ranges.

        A bin is marked when its mass is below min_ratio × the mass of the
        nearest unmarked bin on each side (the shelves flanking the trough);
        marking repeats to a fixpoint so a trough can chain through already
        marked bins. Consecutive marked bins merge into one range. Edge bins
        are never marked.
        """
        keys, vols = self._histogram()
        n = len(vols)
        if n < 3:
            return []
        marked = [False] * n
        changed = True
        while changed:
            changed = False
            for i in range(1, n - 1):
                if marked[i]:
                    continue
                j = i - 1
                while j >= 0 and marked[j]:
                    j -= 1
                k = i + 1
                while k < n and marked[k]:
                    k += 1
                shelf = max(vols[j], vols[k])
                if vols[i] < min_ratio * shelf:
                    marked[i] = True
                    changed = True
        ranges: list[tuple[float, float]] = []
        i = 0
        while i < n:
            if marked[i]:
                j = i
                while j + 1 < n and marked[j + 1]:
                    j += 1
                if j - i + 1 >= min_width:
                    ranges.append((keys[i], keys[j]))
                i = j + 1
            else:
                i += 1
        return ranges

    def _histogram(self) -> tuple[list[float], list[float]]:
        if not self._bins:
            return [], []
        lo = min(self._bins)
        hi = max(self._bins)
        keys = [(lo + i) * self._tick for i in range(hi - lo + 1)]
        vols = [self._bins.get(lo + i, 0.0) for i in range(hi - lo + 1)]
        return keys, vols

    @property
    def poc(self) -> float:
        """Point of Control: grid key of the max-volume bin (0.0 when empty)."""
        keys, vols = self._histogram()
        if not vols:
            return 0.0
        return keys[max(range(len(vols)), key=vols.__getitem__)]

    @property
    def val(self) -> float:
        """Value Area Low: grid key of the bottom VA bin (0.0 when empty)."""
        return self._va_edges()[0]

    @property
    def vah(self) -> float:
        """Value Area High: grid key of the top VA bin (0.0 when empty)."""
        return self._va_edges()[1]

    def _va_edges(self) -> tuple[float, float]:
        keys, vols = self._histogram()
        n = len(vols)
        if n == 0:
            return 0.0, 0.0
        poc_idx = max(range(n), key=vols.__getitem__)
        target = sum(vols) * self._value_area_pct
        up = down = poc_idx
        acc = vols[poc_idx]
        while acc < target:
            up_pair = 0.0
            up_count = 0
            for k in (1, 2):
                if up + k < n:
                    up_pair += vols[up + k]
                    up_count += 1
            down_pair = 0.0
            down_count = 0
            for k in (1, 2):
                if down - k >= 0:
                    down_pair += vols[down - k]
                    down_count += 1
            can_up = up_count > 0
            can_down = down_count > 0
            if not can_up and not can_down:
                break
            poc_vol = vols[poc_idx]
            min_pair = poc_vol * 0.01 if poc_vol > 0 else 0.0
            if can_up and up_pair < min_pair:
                can_up = False
            if can_down and down_pair < min_pair:
                can_down = False
            if not can_up and not can_down:
                break
            up_avg = up_pair / up_count if up_count else 0.0
            down_avg = down_pair / down_count if down_count else 0.0
            if can_up and (not can_down or up_avg >= down_avg):
                for _ in range(up_count):
                    if up + 1 < n:
                        up += 1
                        acc += vols[up]
            elif can_down:
                for _ in range(down_count):
                    if down - 1 >= 0:
                        down -= 1
                        acc += vols[down]
        return keys[down], keys[up]
