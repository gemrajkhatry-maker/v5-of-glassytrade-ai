from dataclasses import dataclass


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
                 max_consecutive_losses: int = 3) -> None:
        self._equity = starting_equity
        self._base_risk_pct = base_risk_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._halted = False
        self._halt_reason = ""

    def record_trade(self, pnl: float) -> RiskState:
        self._daily_pnl += pnl
        if pnl > 0.0:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
        if not self._halted:
            if self._daily_pnl <= -self._max_daily_loss_pct * self._equity:
                self._halted = True
                self._halt_reason = "daily loss limit reached"
            elif self._consecutive_losses >= self._max_consecutive_losses:
                self._halted = True
                self._halt_reason = "max consecutive losses reached"
        return self.state()

    def position_size(self, entry: float, sl: float) -> float:
        if entry == sl:
            return 0.0
        risk_amount = self._equity * self._risk_per_trade_pct()
        return risk_amount / abs(entry - sl)

    def state(self) -> RiskState:
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
