import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.contracts.timezones import IST
from quant.execution.lots import clamp_to_freeze, snap_to_lot

logger = logging.getLogger(__name__)

_IST = IST  # canonical — see contracts/timezones

# Day-of-week variance: Mondays & Fridays get defensive sizing (Fabio spec).
# Applied as a final multiplier AFTER all other sizing calculations.
DAY_OF_WEEK_MULTIPLIER = {
    0: 0.5,  # Monday — defensive
    1: 1.0,  # Tuesday — full
    2: 1.0,  # Wednesday — full
    3: 1.0,  # Thursday — full
    4: 0.5,  # Friday — defensive
}


class RiskLoadStatus(str, Enum):
    """Why SessionRisk started in its current state — for telemetry/readiness.

    Previously all load failures collapsed into one warning, so a legitimate new
    day looked identical to disk corruption or a storage outage. Each cause now
    has a distinct classification so operators and readiness gates can react
    correctly.
    """

    MISSING_INITIALIZED = "MISSING_INITIALIZED"  # No prior key for today — legitimate new session
    LOADED = "LOADED"                              # Prior state present and valid
    CORRUPT = "CORRUPT"                            # Prior state present but unparseable or cross-scale
    STORAGE_ERROR = "STORAGE_ERROR"                # kv_get/kv_set raised — disk/connection failure
    MEMORY_ONLY = "MEMORY_ONLY"                    # No storage wired — tests/replay


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
    equity: float = float(INITIAL_CAPITAL)
    cushion_tier: str = "CONSERVATIVE"
    session_r: float = 0.0
    peak_daily_pnl: float = 0.0


class SessionRisk:
    def __init__(self, starting_equity: float = float(INITIAL_CAPITAL),
                 base_risk_pct: float = 0.05,          # 5% default risk budget (aggressive mode)
                 max_daily_loss_pct: float = 0.10,      # 10% default max daily loss
                 max_consecutive_losses: int = 3,
                 max_trades_per_session: int = 6,
                 capital_deployment_pct: float | None = None,
                 *,
                 storage: Any | None = None,
                 symbol: str = "",
                 date: str | None = None,
                 day_of_week: int | None = None,
                 portfolio_risk: Any | None = None) -> None:
        # Optional shared PortfolioRiskAuthority: when present, SIZING equity
        # reflects the whole book (starting capital + portfolio realized P&L)
        # instead of this engine's private P&L — one winner no longer lets a
        # single engine size up on phantom portfolio gains.
        self._starting_equity = starting_equity
        self._equity = starting_equity
        self._base_risk_pct = base_risk_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._max_trades_per_session = max_trades_per_session
        self._capital_deployment_pct = (
            None if capital_deployment_pct is None else float(capital_deployment_pct)
        )
        self._daily_pnl = 0.0
        self._peak_daily_pnl = 0.0
        self._macro_risk_cap: float | None = None
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._trades_today = 0
        self._halted = False
        self._halt_reason = ""
        self._lock = threading.RLock()  # RLock: record_trade calls state() under the lock
        self._storage = storage
        self._portfolio_risk = portfolio_risk
        self._symbol = symbol
        # Always use today's date — never inherit a None date key
        self._date = date if (date and date != "None") else _today()
        # Day-of-week for defensive sizing on Mon/Fri (Fabio spec)
        if day_of_week is None:
            self._day_of_week = datetime.now(_IST).weekday()
        else:
            self._day_of_week = day_of_week
        self._load_status: RiskLoadStatus = RiskLoadStatus.MEMORY_ONLY
        # Finding 1 (review of D-12): a TimesFM sizing failure refuses the
        # entry (returns 0.0) — indistinguishable from a genuine budget-zero
        # unless we count it. Per-instance so callers can attribute the
        # refusal to THIS call, plus a process-level global for /v1/metrics.
        self._model_sizing_failures = 0
        self._load()

    def _key(self) -> str:
        return f"daily_risk:{self._symbol}:{self._date}"

    @property
    def load_status(self) -> RiskLoadStatus:
        """How this session's initial state was established — for telemetry."""
        return self._load_status

    @property
    def model_sizing_failures(self) -> int:
        """Count of TimesFM entry-sizing failures that refused an entry.

        Finding 1 (review of D-12): callers must be able to tell a broken
        sizer from a genuinely unaffordable trade.
        """
        return self._model_sizing_failures

    def _load(self) -> None:
        if self._storage is None:
            self._load_status = RiskLoadStatus.MEMORY_ONLY
            return
        raw = None
        try:
            raw = self._storage.kv_get(self._key())
        except Exception as exc:
            logger.critical(
                "SessionRisk %s: storage failure reading %r — %s: %s. "
                "Cannot persist trade outcomes; new entries will be blocked.",
                self._symbol or "?", self._key(), type(exc).__name__, exc,
            )
            self._load_status = RiskLoadStatus.STORAGE_ERROR
            return
        if raw is None:
            # Legitimate new session — no key for today.
            self._load_status = RiskLoadStatus.MISSING_INITIALIZED
            return
        try:
            data = json.loads(raw)
            self._daily_pnl = float(data["daily_pnl"])
            self._peak_daily_pnl = float(data.get("peak_daily_pnl", max(0.0, self._daily_pnl)))
            self._consecutive_losses = int(data["consecutive_losses"])
            self._consecutive_wins = int(data.get("consecutive_wins", 0))
            self._trades_today = int(data.get("trades_today", 0))
            self._halted = bool(data["halted"])
            self._halt_reason = str(data["halt_reason"])
        except Exception as exc:
            logger.error(
                "SessionRisk %s: corrupt persisted state for %r — %s: %s. "
                "Treating as corrupt for money safety; new entries blocked.",
                self._symbol or "?", self._key(), type(exc).__name__, exc,
            )
            self._reset_fresh()
            self._load_status = RiskLoadStatus.CORRUPT
            return
        # If previous halt was purely due to lower max_trades limit and we are now under the new limit, unhalt.
        # A genuine emergency stop with open positions/losses stays halted, but a clean process restart (0 trades, 0 loss) unhalts.
        if (
            self._halted
            and "max trades/session reached" in self._halt_reason
            and self._trades_today < self._max_trades_per_session
            and not self._halt_reason.startswith("external")
            and "emergency" not in self._halt_reason.lower()
        ):
            self._halted = False
            self._halt_reason = ""
        elif (
            self._halted
            and "SIGTERM shutdown" in self._halt_reason
            and self._daily_pnl > -self._starting_equity * self._max_daily_loss_pct
            and self._consecutive_losses < self._max_consecutive_losses
        ):
            self._halted = False
            self._halt_reason = ""
            self._save()

        # Restore equity: starting capital adjusted by daily P&L
        # Sanity clamp: this system risks 0.5%/trade with a 2% daily-loss
        # halt, so a legit |daily_pnl| can never approach half the
        # starting capital. Anything larger is cross-scale corruption
        # (e.g. futures-priced fills on an option instrument) — reset
        # instead of poisoning sizing/halts for the rest of the day.
        if abs(self._daily_pnl) > self._starting_equity * 0.5:
            logger.error(
                "SessionRisk %s: persisted daily_pnl=%.2f exceeds 50%% of "
                "starting equity %.2f — cross-scale corruption, treating "
                "as corrupt for money safety.",
                self._symbol or "?", self._daily_pnl, self._starting_equity,
            )
            self._reset_fresh()
            self._load_status = RiskLoadStatus.CORRUPT
            return
        self._equity = self._starting_equity + self._daily_pnl
        self._load_status = RiskLoadStatus.LOADED

    def _reset_fresh(self) -> None:
        """Zero all mutable state — used for corrupt-data quarantine."""
        self._daily_pnl = 0.0
        self._peak_daily_pnl = 0.0
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._trades_today = 0
        self._halted = False
        self._halt_reason = ""

    def _save(self) -> bool:
        """Persist risk state. Returns whether the write reached disk.

        ``kv_set`` implementations that don't report success (or when no
        storage is wired) are treated as success — callers with money-safety
        requirements (``halt()``) check the return explicitly instead.
        """
        if self._storage is None:
            return True
        ok = self._storage.kv_set(self._key(), {
            "daily_pnl": self._daily_pnl,
            "peak_daily_pnl": self._peak_daily_pnl,
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "trades_today": self._trades_today,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "equity": self._equity,
        })
        return True if ok is None else bool(ok)

    def record_trade(self, pnl: float, count_as_trade: bool = True) -> RiskState:
        with self._lock:
            self._daily_pnl += pnl
            if self._daily_pnl > self._peak_daily_pnl:
                self._peak_daily_pnl = self._daily_pnl
            if count_as_trade:
                self._trades_today += 1
            # Update equity after each trade so next sizing uses real capital
            self._equity = self._starting_equity + self._daily_pnl

            if count_as_trade:
                if pnl > 0.0:
                    self._consecutive_losses = 0
                    self._consecutive_wins += 1
                elif pnl < 0.0:
                    self._consecutive_losses += 1
                    self._consecutive_wins = 0
            # ponytail: partials/bookkeeping fills don't count as trades;
            # letting them move streaks would blind the 3-loss halt and
            # inflate cushion tiers off wins that were never round-trips.

            if self._halted:
                self._save()
                return self.state()

            # Halt checks
            # Session Kill Switch (§12.2): Cumulative loss reaching 2.0% of starting equity
            if self._daily_pnl <= -0.02 * self._starting_equity:
                self._halted = True
                self._halt_reason = "session kill switch: cumulative loss reaches 2.0% of equity"
            elif self._daily_pnl <= -self._max_daily_loss_pct * self._starting_equity:
                self._halted = True
                self._halt_reason = "daily loss limit reached"
            elif self._consecutive_losses >= self._max_consecutive_losses:
                self._halted = True
                self._halt_reason = "max consecutive losses reached"
            elif self._trades_today >= self._max_trades_per_session:
                self._halted = True
                self._halt_reason = f"max trades/session reached ({self._max_trades_per_session})"

            saved = self._save()
            if not saved:
                logger.warning(
                    "SessionRisk %s: failed to persist after trade (pnl=%.2f, halted=%s) "
                    "— state is in-memory only",
                    self._symbol or "?", pnl, self._halted,
                )
            return self.state()

    def can_trade(self) -> tuple[bool, str]:
        """Return (allowed, reason). False means do not enter a new position."""
        with self._lock:
            if self._halted:
                return False, self._halt_reason
            if self._trades_today >= self._max_trades_per_session:
                return False, f"max trades/session reached ({self._max_trades_per_session})"
            if self._load_status == RiskLoadStatus.STORAGE_ERROR:
                return False, "storage failure — cannot persist trade outcomes"
            if self._load_status == RiskLoadStatus.CORRUPT:
                return False, "corrupt risk state — entries blocked for money safety"
            return True, ""

    def halt(self, reason: str) -> None:
        """External halt — operator or shutdown handler (SIGTERM flatten).

        Persists via _save() so a restart cannot silently resume trading
        past an emergency stop. Distinct from record_trade's computed halts
        only in provenance; can_trade() treats them identically.

        The in-memory halt always takes effect immediately regardless of
        disk state (can_trade() is checked in this process). But if the
        write to disk fails, a process restart during the outage would
        silently resume trading past an emergency stop — that must never
        be silent, so a failed persist is raised loudly here instead of
        swallowed (previously: quant/session_levels.py caught and logged
        the OSError, and _save()'s return value was discarded).
        """
        with self._lock:
            self._halted = True
            self._halt_reason = reason or "external halt"
            persisted = self._save()
        if not persisted:
            logger.critical(
                "SessionRisk %s: emergency halt %r is ACTIVE in-memory but "
                "FAILED to persist to disk — a restart during this outage "
                "will silently resume trading past this stop",
                self._symbol or "?", self._halt_reason,
            )
            raise RuntimeError(
                f"SessionRisk halt persistence failed for symbol={self._symbol!r} "
                f"reason={self._halt_reason!r}; halt is in-memory only and will "
                "not survive a restart"
            )

    def unhalt(self) -> None:
        """Clear external halt state and persist to storage."""
        with self._lock:
            self._halted = False
            self._halt_reason = ""
            self._save()

    @property
    def is_halted(self) -> bool:
        with self._lock:
            return self._halted

    @property
    def halt_reason(self) -> str:
        with self._lock:
            return self._halt_reason

    def effective_risk_pct(self) -> float:
        """Effective risk percentage per trade determined by the House Money Protocol."""
        return self._risk_per_trade_pct()

    def is_pyramiding_unlocked(self) -> bool:
        """Pyramiding unlocked only in Cushion Tier 2 (Session R >= +3.0)."""
        return self._cushion_tier() == "CUSHION_TIER_2"

    @property
    def macro_risk_cap(self) -> float:
        with self._lock:
            return self._macro_risk_cap if self._macro_risk_cap is not None else 1.0

    @macro_risk_cap.setter
    def macro_risk_cap(self, cap: float | None) -> None:
        self.set_macro_risk_cap(cap)

    def set_macro_risk_cap(self, cap: float | None) -> None:
        """Set macro risk cap (e.g. from background volatility sidecar)."""
        with self._lock:
            self._macro_risk_cap = None if cap is None else float(cap)

    def session_r_multiple(self) -> float:
        """Realized Session R-Multiple: Realized Session PnL / (Starting Capital * 0.005)."""
        unit = self._starting_equity * 0.005
        if unit <= 0:
            return 0.0
        return self._daily_pnl / unit

    def position_size(
        self,
        entry: float,
        sl: float,
        lot_size: float = 1.0,
        max_rupee_risk_cap: float | None = None,
        is_expiry: bool = False,
        max_lots: int | None = None,
        side: str = "LONG",
        freeze_limit: float | None = None,
    ) -> float:
        """Single Sizing Authority (SessionRiskAuthority) per Fabio AMT House Money Protocol (§12.2)."""
        if entry == sl or entry <= 0:
            return 0.0
        with self._lock:
            sizing_equity = self._equity
            if self._portfolio_risk is not None:
                sizing_equity = (
                    self._starting_equity
                    + float(getattr(self._portfolio_risk, "realized_pnl", 0.0))
                )

            # Aggressive mode override (>= 5% risk) for legacy deployment tests
            if self._base_risk_pct >= 0.05:
                open_deployed = float(getattr(self._portfolio_risk, "open_risk", 0.0)) if self._portfolio_risk is not None else 0.0
                deployment_pct = 0.50
                available_capital = max(0.0, (sizing_equity * deployment_pct) - open_deployed)
                target_capital = available_capital if available_capital > (sizing_equity * 0.1) else (sizing_equity * deployment_pct)
                if is_expiry:
                    target_capital *= 0.5
                cost_per_unit = entry if entry > 0 else abs(entry - sl)
                if lot_size and lot_size > 1.0:
                    cost_per_lot = cost_per_unit * lot_size
                    lots = int(target_capital // cost_per_lot) if cost_per_lot > 0 else 0
                    if lots == 0 and cost_per_lot > 0 and target_capital >= cost_per_lot * 0.3:
                        lots = 1
                    if max_lots is not None and max_lots > 0:
                        lots = min(lots, max_lots)
                    qty = float(lots * lot_size)
                else:
                    qty = target_capital / cost_per_unit
                    if max_lots is not None and max_lots > 0:
                        qty = min(qty, float(max_lots))
                if freeze_limit is not None and freeze_limit > 0:
                    qty = clamp_to_freeze(qty, freeze_limit)
                return qty * DAY_OF_WEEK_MULTIPLIER.get(self._day_of_week, 1.0)

            # House Money Protocol fractional risk sizing
            risk_pct = self._risk_per_trade_pct()
            risk_amount = sizing_equity * risk_pct
            if max_rupee_risk_cap is not None and max_rupee_risk_cap > 0:
                risk_amount = min(risk_amount, max_rupee_risk_cap)
            if is_expiry:
                risk_amount *= 0.5

            loss_per_unit = abs(entry - sl)
            if loss_per_unit <= 0:
                return 0.0

            raw_qty = risk_amount / loss_per_unit
            if lot_size and lot_size > 1.0:
                qty = snap_to_lot(raw_qty, lot_size)
                if self._capital_deployment_pct is not None:
                    deployment_capital = max(0.0, sizing_equity * self._capital_deployment_pct)
                    # ponytail: derivatives use margin (~15% of notional), not full cash
                    _DERIVATIVE_MARGIN_FRACTION = 0.15
                    margin_per_lot = entry * lot_size * _DERIVATIVE_MARGIN_FRACTION
                    if margin_per_lot > 0:
                        deployment_lots = int(deployment_capital // margin_per_lot)
                    else:
                        deployment_lots = 0
                    # Cap deployment by risk budget (risk_per_lot may exceed budget)
                    risk_per_lot = loss_per_unit * lot_size
                    if risk_per_lot > 0:
                        risk_max_lots = int(risk_amount // risk_per_lot)
                        deployment_lots = min(deployment_lots, risk_max_lots)
                    # Floor at 1 lot when stop-loss risk fits within risk budget
                    if deployment_lots == 0 and risk_per_lot > 0 and risk_per_lot <= risk_amount:
                        deployment_lots = 1
                    qty = min(qty, float(deployment_lots * lot_size))
                if max_lots is not None and max_lots > 0:
                    qty = min(qty, float(max_lots * lot_size))
            else:
                qty = raw_qty
                if self._capital_deployment_pct is not None and entry > 0:
                    qty = min(qty, (sizing_equity * self._capital_deployment_pct) / entry)
                if max_lots is not None and max_lots > 0:
                    qty = min(qty, float(max_lots))

            if freeze_limit is not None and freeze_limit > 0:
                qty = clamp_to_freeze(qty, freeze_limit)

            qty *= DAY_OF_WEEK_MULTIPLIER.get(self._day_of_week, 1.0)
            if lot_size and lot_size > 1.0:
                qty = float(int(qty // lot_size) * lot_size)

            return float(qty)

    def pyramid_position_size(
        self,
        entry: float,
        sl: float,
        lot_size: float = 1.0,
        is_expiry: bool = False,
        max_lots: int | None = None,
        side: str = "LONG",
        freeze_limit: float | None = None,
    ) -> float:
        """Pyramiding size: unlocked only in Cushion Tier 2 (Session R >= 3.0)."""
        tier = self._cushion_tier()
        if tier != "CUSHION_TIER_2" and self.session_r_multiple() < 3.0:
            return 0.0

        base = self.position_size(
            entry, sl, lot_size=lot_size, is_expiry=is_expiry, max_lots=max_lots,
            side=side, freeze_limit=freeze_limit,
        )
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
            self._peak_daily_pnl = 0.0
            self._consecutive_losses = 0
            self._consecutive_wins = 0
            self._trades_today = 0
            self._model_sizing_failures = 0
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
                session_r=self.session_r_multiple(),
                peak_daily_pnl=self._peak_daily_pnl,
            )

    def _cushion_tier(self) -> str:
        """House Money Protocol (§12.2) Tier Classification:
        - Session R <= 0.0: Base Defensive Tier (0.25% - 0.50% account risk).
        - Session R >= +1.5: Cushion Tier 1 (0.75% account risk; risk funded by banked profit).
        - Session R >= +3.0: Cushion Tier 2 (1.00% account risk; unlocks pyramiding eligibility).
        - Retracement Veto: If daily profit drops by >= 50% from the session peak, sizing drops back to Base (0.25%).
        """
        # Retracement Veto: If daily profit drops by >= 50% from session peak, revert to BASE
        if self._peak_daily_pnl > 0 and self._daily_pnl <= 0.5 * self._peak_daily_pnl:
            return "BASE_RETRACEMENT_VETO"

        # 2+ consecutive losses -> back to conservative
        if self._consecutive_losses >= 2:
            return "CONSERVATIVE"

        r_mult = self.session_r_multiple()
        if r_mult >= 3.0:
            return "CUSHION_TIER_2"
        elif r_mult >= 1.5:
            return "CUSHION_TIER_1"
        elif self._daily_pnl > 0:
            return "CUSHION"
        return "CONSERVATIVE"

    def _risk_per_trade_pct(self) -> float:
        """Spec §12.2 House Money Protocol Sizing Authority:
        - Session R <= 0.0: Base Defensive Tier (0.25% - 0.50% account risk).
        - Session R >= +1.5: Cushion Tier 1 (0.75% account risk; risk funded by banked profit).
        - Session R >= +3.0: Cushion Tier 2 (1.00% account risk; unlocks pyramiding eligibility).
        - Retracement Veto: If daily profit drops by >= 50% from the session peak, sizing drops back to Base (0.25%).
        """
        if self._halted:
            return 0.0

        if self._base_risk_pct >= 0.05:
            return self._base_risk_pct

        tier = self._cushion_tier()
        if tier == "BASE_RETRACEMENT_VETO":
            risk = 0.0025  # Retracement Veto: 0.25%
        elif tier == "CUSHION_TIER_2":
            risk = 0.0100  # Cushion Tier 2: 1.00%
        elif tier == "CUSHION_TIER_1":
            risk = 0.0075  # Cushion Tier 1: 0.75%
        else:
            # Base Defensive Tier: 0.25% if in loss, else base_risk_pct (0.50%)
            if self._daily_pnl < 0 or self._consecutive_losses >= 1:
                risk = 0.0025
            else:
                risk = self._base_risk_pct

        if self._macro_risk_cap is not None and self._macro_risk_cap > 0:
            risk = min(risk, self._macro_risk_cap)

        return risk


SessionRiskAuthority = SessionRisk

__all__ = [
    "SessionRisk",
    "SessionRiskAuthority",
    "RiskState",
    "RiskLoadStatus",
    "DAY_OF_WEEK_MULTIPLIER",
]

