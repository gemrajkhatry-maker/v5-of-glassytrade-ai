from __future__ import annotations
from quantv2.types import Bar


class SessionAMT:
    def __init__(self, tick: float = 0.05) -> None:
        self.tick = tick
        self.closes: list[float] = []
        self.vols: list[float] = []
        self.cvd = 0.0
        self.cvd_hist: list[float] = []
        self.day_high = float("-inf")
        self.day_low = float("inf")
        self.touches_high = 0
        self.touches_low = 0
        self.absorption: str | None = None
        self.leg_lvn = 0.0

    def _profile(self):
        if not self.closes:
            return None, None, None
        lo, hi = min(self.closes), max(self.closes)
        if hi - lo < self.tick:
            return self.closes[-1], hi, lo
        n = max(5, min(50, int((hi - lo) / self.tick)))
        w = (hi - lo) / n
        buckets = [0.0] * n
        for c, v in zip(self.closes, self.vols):
            i = min(n - 1, int((c - lo) / w))
            buckets[i] += v or 1.0
        total = sum(buckets)
        order = sorted(range(n), key=lambda i: buckets[i], reverse=True)
        acc, taken = 0.0, set()
        for i in order:
            acc += buckets[i]
            taken.add(i)
            if acc >= 0.70 * total:
                break
        poc_i = order[0]
        return lo + (poc_i + 0.5) * w, lo + (max(taken) + 1) * w, lo + min(taken) * w

    def update(self, bar: Bar) -> dict:
        self.closes.append(bar.close)
        self.vols.append(bar.volume)
        self.cvd += bar.delta
        self.cvd_hist.append(self.cvd)
        self.day_high = max(self.day_high, bar.high)
        self.day_low = min(self.day_low, bar.low)
        if abs(bar.high - self.day_high) <= 2 * self.tick:
            self.touches_high += 1
        if abs(bar.low - self.day_low) <= 2 * self.tick:
            self.touches_low += 1
        if len(self.closes) >= 3 and all(abs(c - self.closes[-1]) <= 2 * self.tick for c in self.closes[-3:]):
            self.absorption = "SELL_ABSORBED" if bar.close >= self.closes[-3] else "BUY_ABSORBED"
            self.leg_lvn = bar.close
        poc, vah, val = self._profile()
        cvd_slope = self.cvd_hist[-1] - self.cvd_hist[-6] if len(self.cvd_hist) >= 6 else 0.0
        norm = cvd_slope / max(1.0, sum(self.vols[-6:]) or 1.0)
        extra: dict = {"absorption": self.absorption, "leg_lvn": self.leg_lvn}
        if vah is not None and bar.close > vah and len(self.closes) > 1 and self.closes[-2] <= vah:
            extra.update({"break_type": "INITIATIVE", "break_dir": "UP"})
        elif val is not None and bar.close < val and len(self.closes) > 1 and self.closes[-2] >= val:
            extra.update({"break_type": "INITIATIVE", "break_dir": "DOWN"})
        if len(self.closes) >= 10:
            recent = max(self.closes[-5:]) - min(self.closes[-5:])
            prior = max(self.closes[-10:-5]) - min(self.closes[-10:-5])
            if prior > 0 and recent < 0.5 * prior:
                extra["squeeze_dir"] = "LONG" if norm >= 0 else "SHORT"
                extra["pullback"] = abs(bar.close - (poc or bar.close)) <= 3 * self.tick
        snap: dict = {"tick": self.tick, "vah": vah, "val": val, "poc": poc, "cvd_slope": norm, "extra": extra}
        # Top-level mirrors so snap["break_type"]/snap["break_dir"] also read directly
        # (brief's test asserts top-level; engine/setups.py consume extra).
        if "break_type" in extra:
            snap["break_type"] = extra["break_type"]
            snap["break_dir"] = extra["break_dir"]
        return snap
