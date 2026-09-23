"""OHLCV → range-bar synth seed + H_range (ATR14/ladder) helpers.

Spec §4 / plan Task 8:
- ``H_range`` derives from ATR(14) of seed candles, quantized onto the
  ``{5,10,25,50,100,200}`` price ladder only when the rung fits the tick
  (integer number of ticks ≥ 1). If no rung fits / the ladder would snap to
  0 ticks, fall back to ``max(tick, ATR14)`` without forcing the ladder.
- ``synth_range_bars`` walks each 1m OHLC path in fixed H_range steps and
  conserves total volume: each walked segment's volume share is assigned to
  that segment's close (plan Self-review).

Bars produced here are SEED/synthetic only — they must never count toward
live entry warmup (``live_range_bars``) and must not feed drive/Triple-A.
"""

from __future__ import annotations

from typing import Iterable

from quant.amt.orderflow.compute import _compute_atr
from quant.bars import Bar

# Spec §4 quantize ladder (price units).
_H_RANGE_LADDER: tuple[float, ...] = (5.0, 10.0, 25.0, 50.0, 100.0, 200.0)

_EPS = 1e-12


def _field(c, name: str, default: float = 0.0) -> float:
    if isinstance(c, dict):
        return float(c.get(name, default) or default)
    return float(getattr(c, name, default) or default)


def _time_of(c) -> str:
    if isinstance(c, dict):
        return str(c.get("time", "") or "")
    return str(getattr(c, "time", "") or "")


def quantize_h_range(atr14: float, tick_size: float) -> float:
    """Snap ATR(14) onto the §4 ladder when a rung fits the tick.

    A rung "fits" when it is ≥ ATR, ≥ tick, and divides into a whole
    positive number of ticks. Otherwise return ``max(tick, atr14)`` —
    never a zero/negative H_range (a 0 denominator marks every bar
    "compressed" and fires spurious absorption).
    """
    tick = float(tick_size)
    if tick <= 0:
        tick = 1e-12
    atr = float(atr14)
    if atr <= 0:
        return tick
    for rung in _H_RANGE_LADDER:
        if rung + _EPS < atr:
            continue
        steps = rung / tick
        if steps >= 1.0 and abs(steps - round(steps)) < 1e-9:
            return float(rung)
    # Ladder does not fit (or ATR exceeds every rung) — raw fallback.
    return max(tick, atr)


def h_range_from_ohlcs(ohlcs: Iterable, tick_size: float) -> float:
    """ATR(14) of seed 1m candles → quantized H_range (always > 0)."""
    bars = list(ohlcs or ())
    atr = _compute_atr(bars, period=14) if len(bars) >= 2 else 0.0
    return quantize_h_range(atr, tick_size)


# Alias kept for runtime call sites written against the earlier name.
compute_h_range = h_range_from_ohlcs


def _path_points(o: float, h: float, l: float, c: float) -> list[float]:
    """Deterministic OHLC walk: green opens toward high first, red toward low."""
    if c >= o:
        return [o, h, l, c]
    return [o, l, h, c]


def synth_range_bars(ohlcs: Iterable, h_range: float) -> list[Bar]:
    """Synthesize volume-conserving range bars from OHLCV candles.

    Walks each candle's price path, cutting a closed range bar whenever the
    forming bar's high-low spread reaches ``h_range``. Volume of each 1m
    candle is split across its path proportionally to distance; a segment's
    share lands on that segment's close. A trailing partial form carrying
    volume is emitted as the final bar so total volume is conserved.
    """
    h = float(h_range)
    if h <= 0:
        raise ValueError(f"h_range must be > 0, got {h_range!r}")

    out: list[Bar] = []
    fo = fh = fl = fc = 0.0
    fvol = fbuy = fdelta = 0.0
    ftime = ""
    forming = False

    def start(price: float, t: str) -> None:
        nonlocal fo, fh, fl, fc, ftime, forming
        fo = fh = fl = fc = float(price)
        ftime = t
        forming = True

    def touch(price: float) -> None:
        nonlocal fc, fh, fl
        p = float(price)
        fc = p
        if p > fh:
            fh = p
        if p < fl:
            fl = p

    def emit() -> None:
        nonlocal forming, fvol, fbuy, fdelta
        out.append(
            Bar(
                time=ftime,
                open=fo,
                high=fh,
                low=fl,
                close=fc,
                volume=fvol,
                buy_volume=fbuy,
                sell_volume=max(0.0, fvol - fbuy),
                delta=fdelta,
                vwap=fc,
            )
        )
        forming = False
        fvol = fbuy = fdelta = 0.0

    for c in ohlcs or ():
        o = _field(c, "open")
        hi = _field(c, "high")
        lo = _field(c, "low")
        cl = _field(c, "close")
        vol = _field(c, "volume")
        buy = _field(c, "taker_buy_volume")
        if buy == 0.0:
            buy = _field(c, "buy_volume")
        delta = _field(c, "delta")
        t = _time_of(c)

        pts = _path_points(o, hi, lo, cl)
        legs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total_len = sum(abs(b - a) for a, b in legs)

        if not forming:
            start(pts[0], t)

        if total_len <= _EPS:
            # Flat candle: entire volume lands on the single close print.
            touch(cl)
            fvol += vol
            fbuy += buy
            fdelta += delta
            continue

        assigned_vol = assigned_buy = assigned_delta = 0.0
        for a, b in legs:
            seg_len = abs(b - a)
            if seg_len <= _EPS:
                continue
            seg_vol = vol * (seg_len / total_len)
            seg_buy = buy * (seg_len / total_len)
            seg_delta = delta * (seg_len / total_len)
            cursor = a
            # Forming open may already sit at a (chained legs) — trust state.
            while abs(b - cursor) > _EPS:
                going_up = b > cursor
                if going_up:
                    need = fl + h  # price where high-low first reaches h
                    close_at = need if cursor < need <= b else None
                else:
                    need = fh - h
                    close_at = need if b <= need < cursor else None

                if close_at is None:
                    target = b
                else:
                    target = close_at

                dist = abs(target - cursor)
                touch(target)
                frac = dist / seg_len
                portion_v = seg_vol * frac
                portion_b = seg_buy * frac
                portion_d = seg_delta * frac
                fvol += portion_v
                fbuy += portion_b
                fdelta += portion_d
                assigned_vol += portion_v
                assigned_buy += portion_b
                assigned_delta += portion_d
                cursor = target

                if close_at is not None:
                    emit()
                    start(cursor, t)

        # Fold float dust so each candle's volume/buy/delta conserve exactly.
        fvol += vol - assigned_vol
        fbuy += buy - assigned_buy
        fdelta += delta - assigned_delta

    # Flush trailing partial so volume conserves exactly.
    if forming and fvol > 0.0:
        emit()
    return out
