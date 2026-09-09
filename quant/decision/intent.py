"""Model-neutral trade intent contract."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TradeIntent:
    symbol: str
    direction: str
    setup: str
    entry: float
    stop: float
    target: float
    confidence: float | None = None
    forecast_id: str | None = None
    rationale: str = ""
    expires_at: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if self.entry <= 0 or self.stop <= 0 or self.target <= 0:
            raise ValueError("prices must be positive")
        if self.direction == "LONG" and not (self.stop < self.entry < self.target):
            raise ValueError("LONG requires stop < entry < target")
        if self.direction == "SHORT" and not (self.target < self.entry < self.stop):
            raise ValueError("SHORT requires target < entry < stop")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
