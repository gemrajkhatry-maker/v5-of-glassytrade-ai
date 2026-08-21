import json
import logging
import threading
from dataclasses import dataclass
from datetime import date as _date_type, datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))


def _today() -> str:
    return datetime.now(_IST).date().isoformat()


@dataclass(frozen=True)
class RiskState:
    daily_pnl: float
    consecutive_losses: int
    halted: bool
    halt_reason: str
    risk_per_trade_pct: float
    trades_today: int = 0
    equity: float = 1_000_000.0
    cushion_tier: str = "CONSERVATIVE"


class SessionRisk:
    def __init__(self, starting_equity: float = 1_000_000.0,
                 base_risk_pct: float = 0.005,          # 0.5% risk per trade (was 1%)
                 max_daily_loss_pct: float = 0.02,       # 2% max daily loss (was 3%)
                 max_consecutive_losses: int = 3,
                 # TODO: Testing Mode — Raised to 50 for active paper testing & validation.
                 # Change back to 6 in production per Fabio Valentini selective trading rule.
                 max_trades_per_session: int = 50,
                 *,
                 storage: Any | None = None,
                 symbol: str = "",
                 date: str | None = None) -> None:
        self._starting_equity = starting_equity
        self._equity = starting_equity
        self._base_risk_pct = base_risk_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._max_trades_per_session = max_trades_per_session
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._trades_today = 0
        self._halted = False
        self._halt_reason = ""
        self._lock = threading.RLock()  # RLock: record_trade calls state() under the lock
        self._storage = storage
        self._symbol = symbol
        # Always use today's date — never inherit a None date key
        self._date = date if (date and date != "None") else _today()
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
            self._consecutive_wins = int(data.get("consecutive_wins", 0))
            self._trades_today = int(data.get("trades_today", 0))
            self._halted = bool(data["halted"])
            self._halt_reason = str(data["halt_reason"])
            # If previous halt was purely due to lower max_trades limit and we are now under the new limit, unhalt
            if self._halted and "max trades/session reached" in self._halt_reason and self._trades_today < self._max_trades_per_session:
                self._halted = False
                self._halt_reason = ""
            # Restore equity: starting capital adjusted by daily P&L
            # Sanity clamp: this system risks 0.5%/trade with a 2% daily-loss
            # halt, so a legit |daily_pnl| can never approach half the
            # starting capital. Anything larger is cross-scale corruption
            # (e.g. futures-priced fills on an option instrument) — reset
            # instead of poisoning sizing/halts for the rest of the day.
            if abs(self._daily_pnl) > self._starting_equity * 0.5:
                logger.error(
                    "SessionRisk %s: persisted daily_pnl=%.2f exceeds 50%% of "
                    "starting equity %.2f — treating as corrupt, resetting",
                    self._symbol or "?", self._daily_pnl, self._starting_equity,
                )
                self._daily_pnl = 0.0
                self._consecutive_losses = 0
                self._consecutive_wins = 0
                self._trades_today = 0
                self._halted = False
                self._halt_reason = ""
                # Persist the reset NOW — otherwise the corrupt value sits in
                # the store until the next trade and any parallel reader
                # (another engine, a restart) re-inherits it.
                self._save()
            self._equity = self._starting_equity + self._daily_pnl
        except Exception:
            pass  # corrupt/absent store must not inherit a phantom halt

    def _save(self) -> None:
        if self._storage is None:
            return
        self._storage.kv_set(self._key(), {
            "daily_pnl": self._daily_pnl,
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "trades_today": self._trades_today,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "equity": self._equity,
        })

    def record_trade(self, pnl: float) -> RiskState:
        with self._lock:
            if self._halted:
                return self.state()
            self._daily_pnl += pnl
            self._trades_today += 1
            # Update equity after each trade so next sizing uses real capital
            self._equity = self._starting_equity + self._daily_pnl

            if pnl > 0.0:
                self._consecutive_losses = 0
                self._consecutive_wins += 1
            else:
                self._consecutive_losses += 1
                self._consecutive_wins = 0

            # Halt checks
            if self._daily_pnl <= -self._max_daily_loss_pct * self._starting_equity:
                self._halted = True
                self._halt_reason = "daily loss limit reached"
            elif self._consecutive_losses >= self._max_consecutive_losses:
                self._halted = True
                self._halt_reason = "max consecutive losses reached"
            elif self._trades_today >= self._max_trades_per_session:
                self._halted = True
                self._halt_reason = f"max trades/session reached ({self._max_trades_per_session})"

            self._save()
            return self.state()

    def can_trade(self) -> tuple[bool, str]:
        """Return (allowed, reason). False means do not enter a new position."""
        with self._lock:
            if self._halted:
                return False, self._halt_reason
            if self._trades_today >= self._max_trades_per_session:
                return False, f"max trades/session reached ({self._max_trades_per_session})"
            return True, ""

    def position_size(
        self,
        entry: float,
        sl: float,
        lot_size: float = 1.0,
        max_rupee_risk_cap: float | None = None,
        is_expiry: bool = False,
        max_lots: int | None = None,
    ) -> float:
        if entry == sl:
            return 0.0
        with self._lock:
            risk_amount = self._equity * self._risk_per_trade_pct()
            if max_rupee_risk_cap is not None and max_rupee_risk_cap > 0:
                risk_amount = min(risk_amount, max_rupee_risk_cap)
            if is_expiry:
                risk_amount *= 0.5
            loss_per_unit = abs(entry - sl)
            if loss_per_unit <= 0:
                return 0.0
            if lot_size and lot_size > 1.0:
                loss_per_lot = loss_per_unit * lot_size
                lots = int(risk_amount // loss_per_lot) if loss_per_lot > 0 else 0
                if max_lots is not None and max_lots > 0:
                    lots = min(lots, max_lots)
                return float(lots * lot_size)
            else:
                qty = risk_amount / loss_per_unit
                if max_lots is not None and max_lots > 0:
                    qty = min(qty, float(max_lots))
                return qty

    def pyramid_position_size(
        self,
        entry: float,
        sl: float,
        lot_size: float = 1.0,
        is_expiry: bool = False,
        max_lots: int | None = None,
    ) -> float:
        base = self.position_size(entry, sl, lot_size=lot_size, is_expiry=is_expiry, max_lots=max_lots)
        if lot_size and lot_size > 1.0:
            lots = int(base // lot_size)
            pyr_lots = max(0, lots // 2)
            return float(pyr_lots * lot_size)
        return base * 0.5

    def rupee_risk_for_quantity(self, entry: float, sl: float, quantity: float) -> float:
        return abs(entry - sl) * quantity

    def reset_session(self, date: str | None = None) -> RiskState:
        with self._lock:
            self._daily_pnl = 0.0
            self._consecutive_losses = 0
            self._consecutive_wins = 0
            self._trades_today = 0
            self._halted = False
            self._halt_reason = ""
            self._equity = self._starting_equity
            if date:
                self._date = date
            self._save()
            return self.state()

    def state(self) -> RiskState:
        with self._lock:
            return RiskState(
                daily_pnl=self._daily_pnl,
                consecutive_losses=self._consecutive_losses,
                halted=self._halted,
                halt_reason=self._halt_reason,
                risk_per_trade_pct=self._risk_per_trade_pct(),
                trades_today=self._trades_today,
                equity=self._equity,
                cushion_tier=self._cushion_tier(),
            )

    def _cushion_tier(self) -> str:
        """Determine current risk tier based on session performance.
        
        Returns: 'CONSERVATIVE' | 'CUSHION' | 'MOMENTUM'
        """
        # 2+ consecutive losses → back to conservative
        if self._consecutive_losses >= 2:
            return "CONSERVATIVE"
        # First 1-2 trades of the day → conservative
        if self._trades_today < 2:
            return "CONSERVATIVE"
        # 2+ consecutive wins → momentum
        if self._consecutive_wins >= 2:
            return "MOMENTUM"
        # Session profit positive → cushion
        if self._daily_pnl > 0:
            return "CUSHION"
        return "CONSERVATIVE"

    def _risk_per_trade_pct(self) -> float:
        """Spec §12.2 Cushioning & House Money Protocol.

        CONSERVATIVE: first 1-2 trades OR 2+ consecutive losses → 0.25% base risk
        CUSHION: session_pnl > 0 after 2+ trades → 0.35% + 40% of session profit
        MOMENTUM: 2+ consecutive wins → 0.40% + 40% of session profit
        """
        tier = self._cushion_tier()
        if tier == "CONSERVATIVE" or self._daily_pnl <= 0:
            return 0.0025

        base = 0.004 if tier == "MOMENTUM" else 0.0035
        # Spec §12.2: Deploy 40% of earned cushion while ring-fencing core capital
        cushion_bonus = (0.40 * self._daily_pnl) / self._equity if self._equity > 0 else 0.0
        return base + cushion_bonus

