import json
import threading
from dataclasses import dataclass
from datetime import date as _date_type
from typing import Any


def _today() -> str:
    return _date_type.today().isoformat()


@dataclass(frozen=True)
class RiskState:
    daily_pnl: float
    consecutive_losses: int
    halted: bool
    halt_reason: str
    risk_per_trade_pct: float


class SessionRisk:
    def __init__(self, starting_equity: float = 1_000_000.0,
                 base_risk_pct: float = 0.01,
                 max_daily_loss_pct: float = 0.03,
                 max_consecutive_losses: int = 3,
                 *,
                 storage: Any | None = None,
                 symbol: str = "",
                 date: str | None = None) -> None:
        self._equity = starting_equity
        self._base_risk_pct = base_risk_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._halted = False
        self._halt_reason = ""
        self._lock = threading.RLock()  # RLock: record_trade calls state() under the lock
        self._storage = storage
        self._symbol = symbol
        self._date = date if date is not None else _today()
        self._load()

    def _key(self) -> str:
        return f"daily_risk:{self._symbol}:{self._date}"

    def _load(self) -> None:
        if self._storage is None:
            return
        try:
            raw = self._storage.kv_get(self._key())
            data = json.loads(raw)
            self._daily_pnl = float(data["daily_pnl"])
            self._consecutive_losses = int(data["consecutive_losses"])
            self._halted = bool(data["halted"])
            self._halt_reason = str(data["halt_reason"])
        except Exception:
            pass  # corrupt/absent store must not inherit a phantom halt

    def _save(self) -> None:
        if self._storage is None:
            return
        self._storage.kv_set(self._key(), {
            "daily_pnl": self._daily_pnl,
            "consecutive_losses": self._consecutive_losses,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
        })

    def record_trade(self, pnl: float) -> RiskState:
        with self._lock:
            if self._halted:
                return self.state()
            self._daily_pnl += pnl
            if pnl > 0.0:
                self._consecutive_losses = 0
            else:
                self._consecutive_losses += 1
            if self._daily_pnl <= -self._max_daily_loss_pct * self._equity:
                self._halted = True
                self._halt_reason = "daily loss limit reached"
            elif self._consecutive_losses >= self._max_consecutive_losses:
                self._halted = True
                self._halt_reason = "max consecutive losses reached"
            self._save()
            return self.state()

    def position_size(self, entry: float, sl: float) -> float:
        if entry == sl:
            return 0.0
        risk_amount = self._equity * self._risk_per_trade_pct()
        return risk_amount / abs(entry - sl)

    def state(self) -> RiskState:
        with self._lock:
            return RiskState(
                daily_pnl=self._daily_pnl,
                consecutive_losses=self._consecutive_losses,
                halted=self._halted,
                halt_reason=self._halt_reason,
                risk_per_trade_pct=self._risk_per_trade_pct(),
            )

    def _risk_per_trade_pct(self) -> float:
        floor = self._base_risk_pct * 0.25
        shrunk = self._base_risk_pct * (0.5 ** self._consecutive_losses)
        return max(shrunk, floor)
