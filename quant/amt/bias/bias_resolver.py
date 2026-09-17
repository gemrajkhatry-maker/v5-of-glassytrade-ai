"""15-minute bias direction resolver (Fabio's top-down layer 1).

Determines directional bias from 15-min bar structure:
- LONG_BIAS: higher highs + higher lows in recent window
- SHORT_BIAS: lower highs + lower lows in recent window
- NEUTRAL: mixed structure or insufficient data

Fabio's methodology: 15m establishes direction, 5m finds location, 1m triggers entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from quant.bars import Bar


class BiasDirection(Enum):
    LONG_BIAS = "LONG_BIAS"
    SHORT_BIAS = "SHORT_BIAS"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class BiasResult:
    direction: BiasDirection
    confidence: float  # 0.0 to 1.0
    higher_highs: bool
    higher_lows: bool
    lower_highs: bool
    lower_lows: bool


# ponytail: Fabio uses 15m bias — minimum bars to establish structure
_MIN_BIAS_BARS = 3


class BiasResolver:
    """Resolve directional bias from 15-min bar structure."""

    def resolve(self, bars: list[Bar]) -> BiasResult:
        if len(bars) < _MIN_BIAS_BARS:
            return BiasResult(
                direction=BiasDirection.NEUTRAL,
                confidence=0.0,
                higher_highs=False, higher_lows=False,
                lower_highs=False, lower_lows=False,
            )

        highs = [b.high for b in bars]
        lows = [b.low for b in bars]

        hh = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1])
        hl = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i - 1])
        lh = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i - 1])
        ll = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])

        bullish_count = hh + hl
        bearish_count = lh + ll
        total_transitions = (len(bars) - 1) * 2

        if total_transitions == 0:
            return BiasResult(
                direction=BiasDirection.NEUTRAL, confidence=0.0,
                higher_highs=False, higher_lows=False,
                lower_highs=False, lower_lows=False,
            )

        bullish_ratio = bullish_count / total_transitions
        bearish_ratio = bearish_count / total_transitions

        # ponytail: Fabio requires clear structural alignment — 60%+ threshold
        _BIAS_THRESHOLD = 0.60

        if bullish_ratio >= _BIAS_THRESHOLD:
            return BiasResult(
                direction=BiasDirection.LONG_BIAS,
                confidence=min(1.0, bullish_ratio),
                higher_highs=hh > lh,
                higher_lows=hl > ll,
                lower_highs=lh >= hh,
                lower_lows=ll >= hl,
            )
        elif bearish_ratio >= _BIAS_THRESHOLD:
            return BiasResult(
                direction=BiasDirection.SHORT_BIAS,
                confidence=min(1.0, bearish_ratio),
                higher_highs=hh > lh,
                higher_lows=hl > ll,
                lower_highs=lh >= hh,
                lower_lows=ll >= hl,
            )
        else:
            return BiasResult(
                direction=BiasDirection.NEUTRAL,
                confidence=0.0,
                higher_highs=hh > lh, higher_lows=hl > ll,
                lower_highs=lh >= hh, lower_lows=ll >= hl,
            )
