from __future__ import annotations
from quantv2.engine import Engine


class Coordinator:
    def __init__(self, risk_cap: float = 100000.0) -> None:
        self.risk_cap = risk_cap
        self.engines: dict[str, Engine] = {}
        self._last: dict[str, float] = {}

    def add(self, engine: Engine) -> None:
        self.engines[engine.symbol] = engine

    def _headroom(self, symbol: str) -> float:
        used = sum(e.open_risk for s, e in self.engines.items() if s != symbol)
        return self.risk_cap - used

    def on_tick(self, symbol: str, ts: float, price: float, volume: float = 0.0, delta: float = 0.0):
        eng = self.engines[symbol]
        self._last[symbol] = price
        eng.risk_cap = self._headroom(symbol)
        out = eng.on_tick(ts, price, volume, delta)
        eng.last_decision = out
        return out

    def eod_flatten(self, reason: str = "EOD") -> int:
        n = 0
        for symbol, eng in self.engines.items():
            if eng.position is not None:
                eng.oms.close(eng.position, self._last.get(symbol, eng.position.entry), reason)
                eng.position = None
                eng.trail = {}
                eng.open_risk = 0.0
                n += 1
        return n

    def load_state(self, state: dict) -> None:
        from quantv2.oms import Position
        for symbol, s in state.items():
            eng = self.engines.get(symbol)
            if eng is None:
                continue
            p = s.get("position")
            eng.position = Position(**p) if p else None
            eng.open_risk = float(s.get("open_risk", 0.0))
            eng.trail = dict(s.get("trail", {}))
