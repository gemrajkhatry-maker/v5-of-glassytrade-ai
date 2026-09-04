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
        self.triple = _TripleA(tick)
        self.sd = _SecondDrive(tick)

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
        prev_high = self.day_high
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
        norm = cvd_slope / max(1.0, 0.2 * (sum(self.vols[-6:]) or 1.0))
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
        self.sd.extreme = prev_high
        extra.update(self.sd.update(bar))
        extra.update(self.triple.update(bar))
        snap: dict = {"tick": self.tick, "vah": vah, "val": val, "poc": poc, "cvd_slope": norm, "extra": extra}
        # Top-level mirrors so snap["break_type"]/snap["break_dir"] also read directly
        # (brief's test asserts top-level; engine/setups.py consume extra).
        if "break_type" in extra:
            snap["break_type"] = extra["break_type"]
            snap["break_dir"] = extra["break_dir"]
        return snap


class _TripleA:
    """Absorption -> accumulation -> aggression -> acceptance (LONG or SHORT)."""

    def __init__(self, tick: float) -> None:
        self.tick = tick if tick > 0 else 0.05
        self.reset()

    def reset(self) -> None:
        self.phase = "WAITING"
        self.side = None
        self.level = 0.0
        self.acc = 0

    def update(self, bar: Bar) -> dict:
        out: dict = {}
        body_up = bar.close > bar.open
        if self.phase == "WAITING":
            # absorption: volume spike, delta against the close direction
            if bar.volume > 0 and bar.delta != 0:
                against = (bar.delta < 0 and body_up) or (bar.delta > 0 and not body_up)
                if against and abs(bar.delta) > 0.3 * bar.volume:
                    self.phase = "ABSORBING"
                    # absorption means the close's side won: continuation follows the body
                    self.side = "LONG" if body_up else "SHORT"
                    self.level = bar.low if self.side == "LONG" else bar.high
                    self.acc = 0
            out["triple_phase"] = "ABSORBING" if self.phase != "WAITING" else "WAITING"
            if self.phase != "WAITING":
                out["triple_signal"] = self.side
            return out
        if self.phase == "ABSORBING":
            stepped = (self.side == "LONG" and bar.close > bar.open and bar.delta > 0) or (
                self.side == "SHORT" and bar.close < bar.open and bar.delta < 0)
            self.acc = self.acc + 1 if stepped else 0
            if self.acc >= 2:
                self.phase = "ACCUMULATED"
            out["triple_phase"] = "ABSORBING"
            out["triple_signal"] = self.side
            return out
        if self.phase == "ACCUMULATED":
            strong = bar.volume > 0 and abs(bar.delta) > 0.3 * bar.volume
            broke_up = self.side == "LONG" and strong and bar.close > max(bar.open, self.level)
            broke_dn = self.side == "SHORT" and strong and bar.close < min(bar.open, self.level)
            if broke_up or broke_dn:
                self.phase = "AGGRESSION"
                out["triple_phase"] = "AGGRESSION"
                out["triple_signal"] = self.side
                out["acceptance"] = False
                return out
            out["triple_phase"] = "ABSORBING"
            out["triple_signal"] = self.side
            return out
        # AGGRESSION: acceptance = this bar holds beyond the absorption extreme
        held = bar.close >= self.level if self.side == "LONG" else bar.close <= self.level
        if held:
            out["triple_phase"] = "AGGRESSION"
            out["triple_signal"] = self.side
            out["acceptance"] = True
        else:
            self.reset()
        return out


class _SecondDrive:
    """D1 rejected at extreme -> D2 weaker approach rejected -> tradeable fade."""

    def __init__(self, tick: float) -> None:
        self.tick = tick if tick > 0 else 0.05
        self.extreme: float | None = None
        self.d1_rejected = False
        self.leg_rng = 0.0

    def update(self, bar: Bar) -> dict:
        out: dict = {}
        rng = bar.high - bar.low
        if self.extreme is None:
            return out
        if not self.d1_rejected:
            # rejection of D1: poke the extreme, close back well inside
            poked = bar.high >= self.extreme - self.tick
            back = bar.close < self.extreme - 2 * self.tick
            if poked and back:
                self.d1_rejected = True
                self.leg_rng = rng
            return out
        weaker = rng < self.leg_rng
        poked = bar.high >= self.extreme - 2 * self.tick
        rejected = bar.close < self.extreme - 2 * self.tick
        if weaker and poked and rejected:
            out["is_second_drive"] = True
            out["rejection"] = True
            out["rejection_high"] = True
            out["direction"] = "SHORT"
            self.extreme = None
            self.d1_rejected = False
        return out
