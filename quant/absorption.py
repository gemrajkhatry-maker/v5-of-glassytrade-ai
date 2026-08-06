from dataclasses import dataclass, replace

from quant.bars import Bar

_BAR_BUFFER = 30
_AVG_WINDOW = 20
_RANGE_EPS = 0.5


@dataclass(frozen=True)
class Absorption:
    bar_index: int
    price: float
    volume: float
    side: str            # "BUY" | "SELL"
    strength: float      # 0..1
    bar_age: int         # bars since this absorption (0 = current)


class AbsorptionDetector:
    def __init__(self, volume_mult: float = 1.5, range_ratio: float = 0.5) -> None:
        self._volume_mult = volume_mult
        self._range_ratio = range_ratio
        self._bars: list[Bar] = []
        self._index = 0
        self._current: Absorption | None = None

    def update(self, bar: Bar) -> None:
        window = self._bars[-_AVG_WINDOW:]
        avg_volume = sum(b.volume for b in window) / len(window) if window else 0.0
        avg_range = sum(b.high - b.low for b in window) / len(window) if window else 0.0

        self._bars.append(bar)
        if len(self._bars) > _BAR_BUFFER:
            del self._bars[:-_BAR_BUFFER]
        self._index += 1

        bar_range = bar.high - bar.low
        if avg_range > 0:
            range_ok = bar_range <= self._range_ratio * avg_range
        else:
            range_ok = bar_range <= _RANGE_EPS

        if bar.volume > self._volume_mult * avg_volume and range_ok:
            self._current = Absorption(
                bar_index=self._index - 1,
                price=bar.close,
                volume=bar.volume,
                side=self._side(bar),
                strength=self._strength(bar.volume, avg_volume),
                bar_age=0,
            )
        elif self._current is not None:
            self._current = replace(self._current, bar_age=self._current.bar_age + 1)

    def snapshot(self) -> Absorption | None:
        return self._current

    @staticmethod
    def _side(bar: Bar) -> str:
        if bar.buy_volume >= 0.55 * bar.volume:
            return "BUY"
        if bar.sell_volume >= 0.55 * bar.volume:
            return "SELL"
        mid = (bar.high + bar.low) / 2.0
        return "BUY" if bar.close > mid else "SELL"

    def _strength(self, volume: float, avg_volume: float) -> float:
        return min(1.0, (volume / avg_volume - 1) / 3)
