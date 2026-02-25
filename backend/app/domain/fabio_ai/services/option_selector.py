"""Option Selector — NSE options selection domain service.

Pure domain logic for translating LONG/SHORT signals on the underlying
(NIFTY/BANKNIFTY) into specific option contracts.  Handles strike
selection, expiry picking, liquidity/theta validation, and lot sizing
per the Fabio AMT methodology.

No broker API calls — the broker adapter supplies the option chain data
and this service selects the right contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OptionSelection:
    """Fully resolved option contract ready for order placement."""

    underlying: str          # "NIFTY" or "BANKNIFTY"
    strike: int              # e.g. 24800
    option_type: str         # "CE" or "PE"
    expiry: str              # ISO date string (YYYY-MM-DD)
    premium: float           # current premium
    delta: float             # option delta
    theta: float             # daily theta decay
    iv: float                # implied volatility
    bid_ask_spread: float    # spread in rupees
    oi: int                  # open interest
    lot_size: int            # NIFTY=25, BANKNIFTY=15
    num_lots: int            # calculated from risk sizing


@dataclass(frozen=True)
class ThetaCheck:
    """Result of theta-viability analysis for a potential trade."""

    daily_theta: float
    expected_hold_minutes: int
    holding_cost: float      # theta x time x lots x lot_size
    expected_profit: float
    theta_ratio: float       # holding_cost / expected_profit
    viable: bool             # theta_ratio < max_theta_ratio


@dataclass
class OptionSelectorConfig:
    """Tuneable knobs for the option selection pipeline."""

    min_days_to_expiry: int = 3
    max_spread_pct: float = 0.02        # 2% of premium
    min_oi: int = 1_000_000             # 10 lakh for NIFTY
    min_volume: int = 50_000
    max_theta_ratio: float = 0.20       # theta cost < 20% of expected profit
    nifty_lot_size: int = 25
    banknifty_lot_size: int = 15
    nifty_strike_interval: int = 50
    banknifty_strike_interval: int = 100


# MCX lot sizes and strike intervals
MCX_LOT_SIZES: dict[str, int] = {
    "CRUDEOIL": 100,
    "CRUDEOILM": 10,     # Mini crude
    "NATURALGAS": 1250,
    "GOLD": 100,          # grams
    "GOLDM": 10,          # Mini gold
    "GOLDPETAL": 1,
    "SILVER": 30,         # kg
    "SILVERM": 5,         # Mini silver
    "COPPER": 2500,       # kg
}
MCX_STRIKE_INTERVALS: dict[str, int] = {
    "CRUDEOIL": 50,
    "CRUDEOILM": 50,
    "NATURALGAS": 5,
    "GOLD": 100,
    "GOLDM": 100,
    "GOLDPETAL": 50,
    "SILVER": 500,
    "SILVERM": 500,
    "COPPER": 5,
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class OptionSelector:
    """Translates directional signals into concrete NSE option contracts."""

    def __init__(self, config: OptionSelectorConfig | None = None) -> None:
        self.cfg = config or OptionSelectorConfig()

    # -- helpers -------------------------------------------------------------

    def _strike_interval(self, underlying: str) -> int:
        """Return the exchange-mandated strike interval for *underlying*."""
        key = underlying.upper()
        if key in MCX_STRIKE_INTERVALS:
            return MCX_STRIKE_INTERVALS[key]
        if key == "BANKNIFTY":
            return self.cfg.banknifty_strike_interval
        return self.cfg.nifty_strike_interval

    def _lot_size_for(self, underlying: str) -> int:
        """Return the standard lot size for *underlying*."""
        key = underlying.upper()
        if key in MCX_LOT_SIZES:
            return MCX_LOT_SIZES[key]
        if key == "BANKNIFTY":
            return self.cfg.banknifty_lot_size
        return self.cfg.nifty_lot_size

    @staticmethod
    def _round_to_strike(price: float, interval: int) -> int:
        """Round *price* to the nearest strike on the given *interval*."""
        return int(round(price / interval) * interval)

    # -- public API ----------------------------------------------------------

    def select_strike(
        self,
        underlying: str,
        spot_price: float,
        direction: str,
    ) -> int:
        """Pick ATM or 1-strike OTM based on signal direction.

        LONG signal -> buy CE (1 strike OTM above spot).
        SHORT signal -> buy PE (1 strike OTM below spot).
        """
        interval = self._strike_interval(underlying)
        atm = self._round_to_strike(spot_price, interval)

        if direction.upper() == "LONG":
            # CE: one strike OTM (above spot)
            return atm + interval
        # PE: one strike OTM (below spot)
        return atm - interval

    def build_symbol(
        self,
        underlying: str,
        strike: int,
        option_type: str,
        expiry: str,
    ) -> str:
        """Build a human-readable Dhan-style symbol string.

        Example: build_symbol("NIFTY", 23400, "CE", "2026-03-20")
                 → "NIFTY 20 MAR 23400 CE"
        """
        _MONTHS = {
            1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
            7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
        }
        d = date.fromisoformat(expiry)
        day = d.day
        mon = _MONTHS[d.month]
        return f"{underlying.upper()} {day} {mon} {strike} {option_type.upper()}"

    def validate_option(
        self,
        option: OptionSelection,
    ) -> tuple[bool, str]:
        """Run liquidity and time-to-expiry checks on *option*.

        Returns ``(passed, reason)`` where *reason* is empty on success.
        """
        # Bid-ask spread check
        if option.premium > 0:
            spread_pct = option.bid_ask_spread / option.premium
            if spread_pct > self.cfg.max_spread_pct:
                return (
                    False,
                    f"Bid-ask spread {spread_pct:.2%} exceeds "
                    f"max {self.cfg.max_spread_pct:.2%}",
                )

        # Open interest check
        if option.oi < self.cfg.min_oi:
            return (
                False,
                f"OI {option.oi:,} below minimum {self.cfg.min_oi:,}",
            )

        # Days to expiry check
        expiry_date = date.fromisoformat(option.expiry)
        today = date.today()
        dte = (expiry_date - today).days
        if dte < self.cfg.min_days_to_expiry:
            return (
                False,
                f"DTE {dte} below minimum {self.cfg.min_days_to_expiry}",
            )

        return (True, "")

    def check_theta(
        self,
        option: OptionSelection,
        expected_hold_minutes: int,
        target_premium_move: float,
    ) -> ThetaCheck:
        """Evaluate whether theta decay makes the trade unviable.

        If theta cost exceeds ``max_theta_ratio`` of expected profit the
        trade is flagged as not viable.
        """
        # Daily theta is negative (cost), but we work with absolute values
        daily_theta = abs(option.theta)
        hold_fraction = expected_hold_minutes / (24 * 60)  # fraction of a day

        # Total theta cost for the position
        holding_cost = (
            daily_theta * hold_fraction * option.num_lots * option.lot_size
        )

        # Expected profit from premium move
        expected_profit = (
            target_premium_move * option.num_lots * option.lot_size
        )

        theta_ratio = (
            holding_cost / expected_profit if expected_profit > 0 else math.inf
        )

        return ThetaCheck(
            daily_theta=daily_theta,
            expected_hold_minutes=expected_hold_minutes,
            holding_cost=round(holding_cost, 2),
            expected_profit=round(expected_profit, 2),
            theta_ratio=round(theta_ratio, 4),
            viable=theta_ratio < self.cfg.max_theta_ratio,
        )

    def compute_lot_size(
        self,
        account_equity: float,
        risk_pct: float,
        stop_loss_points: float,
        lot_size: int,
    ) -> int:
        """Derive the number of lots from risk parameters.

        ``risk_amount = account_equity * risk_pct``
        ``lots = risk_amount / (lot_size * stop_loss_points)``

        Always returns at least 1.
        """
        if stop_loss_points <= 0 or lot_size <= 0:
            return 1
        risk_amount = account_equity * risk_pct
        lots = risk_amount / (lot_size * stop_loss_points)
        return max(1, math.floor(lots))

    def select_expiry(
        self,
        available_expiries: list[str],
        current_date: str,
    ) -> str | None:
        """Pick the optimal weekly expiry from *available_expiries*.

        Strategy:
        - Mon/Tue -> current week expiry (if it has >= ``min_days_to_expiry``
          trading days remaining).
        - Wed-Fri -> next week expiry.
        - Always enforce a minimum of ``min_days_to_expiry`` calendar days.

        Returns ``None`` when no suitable expiry is available.
        """
        today = date.fromisoformat(current_date)
        weekday = today.weekday()  # 0=Mon ... 6=Sun

        # Parse and sort available expiries chronologically
        parsed: list[date] = sorted(
            date.fromisoformat(e) for e in available_expiries if e >= current_date
        )

        if not parsed:
            return None

        min_dte = self.cfg.min_days_to_expiry

        if weekday <= 1:
            # Monday or Tuesday — prefer current-week expiry
            for exp in parsed:
                dte = (exp - today).days
                if dte >= min_dte:
                    return exp.isoformat()
        else:
            # Wednesday through Friday — skip to next week
            next_week_start = today + timedelta(days=(7 - weekday))
            for exp in parsed:
                dte = (exp - today).days
                if dte >= min_dte and exp >= next_week_start:
                    return exp.isoformat()

        # Fallback: first expiry meeting the minimum DTE requirement
        for exp in parsed:
            if (exp - today).days >= min_dte:
                return exp.isoformat()

        return None
