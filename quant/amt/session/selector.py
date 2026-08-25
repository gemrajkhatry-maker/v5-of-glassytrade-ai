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
import logging

from quant.contracts.instrument_registry import DEFAULT_REGISTRY
from quant.contracts.timezones import today_ist

logger = logging.getLogger(__name__)


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
    lot_size: int            # NIFTY=65, BANKNIFTY=30 (current NSE series)
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

    min_days_to_expiry: int = 0           # Scalping: allow 0-DTE for intraday scalping
    max_spread_pct: float = 0.02        # 2% of premium
    min_oi: int = 200_000               # Lower for current-week early buildup
    min_oi_next_week: int = 500_000     # Stricter for next-week expiry
    min_volume: int = 50_000
    max_theta_ratio: float = 0.20       # theta cost < 20% of expected profit
    # Exchange-authoritative current NSE series (Aug 2026). These defaults are
    # fallbacks only — callers should pass the broker/config lot size.
    nifty_lot_size: int = 65
    banknifty_lot_size: int = 30
    nifty_strike_interval: int = 50
    banknifty_strike_interval: int = 100


# Derived from InstrumentRegistry — kept as names tests already import.
MCX_LOT_SIZES: dict[str, int] = {
    s.root: s.lot_size for s in DEFAULT_REGISTRY.specs() if s.exchange == "MCX"
}
MCX_STRIKE_INTERVALS: dict[str, int] = {
    s.root: int(s.strike_interval)
    for s in DEFAULT_REGISTRY.specs()
    if s.exchange == "MCX"
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
        spec = DEFAULT_REGISTRY.try_resolve(underlying)
        if spec is not None:
            return int(spec.strike_interval)
        if underlying.upper() == "BANKNIFTY":
            return self.cfg.banknifty_strike_interval
        return self.cfg.nifty_strike_interval

    def _lot_size_for(self, underlying: str) -> int:
        """Return the standard lot size for *underlying*."""
        spec = DEFAULT_REGISTRY.try_resolve(underlying)
        if spec is not None:
            return spec.lot_size
        if underlying.upper() == "BANKNIFTY":
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
        chain=None,
    ) -> int:
        """Pick ATM strike for maximum gamma sensitivity (scalping-optimized).

        For scalping, ATM provides the highest gamma (fastest delta
        acceleration on small moves) and tightest spreads.  If a live
        option chain is supplied, selects the strike with the highest
        gamma × volume product near ATM for optimal scalping response.

        Falls back to pure ATM when chain/greeks are unavailable.
        """
        interval = self._strike_interval(underlying)
        atm = self._round_to_strike(spot_price, interval)

        # If chain with greeks available, pick best gamma×volume strike near ATM
        if chain is not None:
            opt_map = chain.calls if direction.upper() == "LONG" else chain.puts
            best_strike = atm
            best_gv = -1.0
            for offset in range(-1, 2):  # ATM-1, ATM, ATM+1
                s = atm + offset * interval
                opt = opt_map.get(float(s))
                if opt is None:
                    continue
                gamma = float(opt.gamma or 0) if hasattr(opt, 'gamma') and opt.gamma else 0.0
                vol = int(opt.volume or 0)
                gv = gamma * (vol + 1)  # +1 to avoid zero
                if gv > best_gv:
                    best_gv = gv
                    best_strike = s
            return int(best_strike)

        # No chain — return ATM directly (not OTM)
        return atm

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
        today = today_ist()
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

    def compute_option_lot_size(
        self,
        account_equity: float,
        risk_pct: float,
        underlying_stop_points: float,
        option_delta: float,
        lot_size: int,
        session_profit: float = 0.0,
        max_lots_cap: int = 50,
        is_expiry: bool = False,
    ) -> int:
        """Derive option lots from underlying stop points mapped via option delta.

        Enforces Fabio Cushion System:
        - Base risk: account_equity * risk_pct (e.g. 0.25% - 0.50%)
        - If session_profit > 0: add up to 20% of session profit (capped at 30% total profit)
        - Option stop points = underlying_stop_points * max(0.30, min(1.0, abs(option_delta)))
        - On expiry day: max lots capped at 50% of standard ceiling
        """
        if underlying_stop_points <= 0 or lot_size <= 0:
            return 1
        
        # 1. Calculate allowed rupee risk with intraday cushion
        base_risk = account_equity * risk_pct
        cushion = max(0.0, session_profit * 0.20) if session_profit > 0 else 0.0
        # Cap cushion at 30% of total session profit
        total_risk_rupees = base_risk + min(cushion, session_profit * 0.30 if session_profit > 0 else 0.0)

        # 2. Map underlying stop to option premium stop via observed delta
        effective_delta = max(0.30, min(1.0, abs(option_delta)))
        option_stop_points = underlying_stop_points * effective_delta

        # 3. Size lots
        lots = total_risk_rupees / (lot_size * option_stop_points)
        num_lots = max(1, math.floor(lots))

        # 4. Cap by expiry day and max lots limit
        effective_cap = max(1, max_lots_cap // 2) if is_expiry else max_lots_cap
        return min(num_lots, effective_cap)

    def select_expiry(
        self,
        available_expiries: list[str],
        current_date: str,
        current_hour: int = 10,
    ) -> str | None:
        """Pick the optimal weekly expiry from *available_expiries*.

        Scalping-optimized strategy:
        - ALWAYS prefer current-week expiry for maximum gamma.
        - Only skip to next week if today IS expiry day AND after 14:30
          (gamma trap zone in last 45 min).
        - Minimum DTE=1 (allow 1-day expiry for gamma scalping).

        Returns ``None`` when no suitable expiry is available.
        """
        today = date.fromisoformat(current_date)

        # Parse and sort available expiries chronologically
        parsed: list[date] = sorted(
            date.fromisoformat(e) for e in available_expiries if e >= current_date
        )

        if not parsed:
            return None

        min_dte = self.cfg.min_days_to_expiry  # default 1

        # Check if today is expiry day and we're in gamma-trap zone (after 14:30 IST)
        is_expiry_day = parsed[0] == today
        in_gamma_trap = is_expiry_day and current_hour >= 15  # 3 PM IST — last 15 min

        if is_expiry_day and in_gamma_trap:
            # Skip today's expiry, use next available
            for exp in parsed[1:]:
                return exp.isoformat()
            return None

        # Default: use nearest expiry (current week) for maximum gamma
        for exp in parsed:
            dte = (exp - today).days
            if dte >= min_dte:
                return exp.isoformat()

        # Even DTE=0 is acceptable for intraday scalping (before gamma trap)
        if parsed:
            return parsed[0].isoformat()

        return None

    def translate_underlying_signal_to_option(
        self,
        signal,
        option_symbol: str,
        option_ltp: float,
        delta: float = 0.50,
        tick_size: float = 0.05,
    ):
        """Translate an underlying futures/index signal into an option contract signal.
        
        - Underlying LONG -> Buys Call Option at option_ltp
        - Underlying SHORT -> Buys Put Option at option_ltp
        - Delta-adjusted stop & target:
            opt_risk_pts = max(tick_size, abs(signal.entry - signal.sl) * max(0.20, min(1.0, abs(delta))))
            opt_reward_pts = max(tick_size * 2, abs(signal.tp - signal.entry) * max(0.20, min(1.0, abs(delta))))
            opt_entry = float(option_ltp)
            opt_sl = max(tick_size, opt_entry - opt_risk)
            opt_tp = opt_entry + opt_reward
        """
        from quant.decision.signal_builder import Signal
        if option_ltp <= 0:
            logger.warning("[OPTION TRANSLATE] %s: option LTP <= 0, cannot price option signal", option_symbol)
            return None

        # NOTE (re-audit, this session): a "cross-scale contamination" guard
        # here (rejecting when signal.entry is >5x or <0.2x option_ltp) was
        # deleted earlier this session. The consolidated audit plan flagged
        # that deletion as a regression to restore. Verified empirically
        # instead of restoring blindly: the guard's polarity is backwards.
        # signal.entry is always UNDERLYING-scale (index spot / futures
        # price) while option_ltp is the option PREMIUM — these are
        # supposed to differ by 50-200x for any real ATM/OTM trade (NIFTY
        # spot 24500 vs a real ~150 premium is >160x; GOLDM spot ~1.6L vs a
        # real ~2837 premium is >55x). The guard as originally written would
        # reject essentially every real translation while *passing* the
        # actual bug it claims to catch (a mis-wired feed where option_ltp
        # accidentally equals the underlying price, ratio ~1x). Confirmed via
        # tests/quant/test_adversarial_regression.py and
        # tests/quant/decision/test_option_signal_translation.py, both of
        # which fail if this guard is restored verbatim. Deliberately not
        # restored — flagging here instead of re-deleting silently.

        from quant.contracts.instrument_registry import is_option_contract
        sym_upper = option_symbol.upper().rstrip()
        is_call = is_option_contract(option_symbol) and (
            sym_upper.endswith(("CALL", "CE")) or sym_upper.endswith("-CE")
        )
        is_put = is_option_contract(option_symbol) and (
            sym_upper.endswith(("PUT", "PE")) or sym_upper.endswith("-PE")
        )

        if str(signal.type).upper() == "LONG" and not is_call:
            logger.debug(
                "[OPTION DIRECTION GUARD] %s: ignoring LONG signal on PUT contract %s",
                option_symbol, signal.type,
            )
            return None
        if str(signal.type).upper() == "SHORT" and not is_put:
            logger.debug(
                "[OPTION DIRECTION GUARD] %s: ignoring SHORT signal on CALL contract %s",
                option_symbol, signal.type,
            )
            return None

        eff_delta = max(0.20, min(1.0, abs(delta)))
        underlying_risk = abs(signal.entry - signal.sl)
        underlying_reward = abs(signal.tp - signal.entry)
        
        opt_risk = max(tick_size, underlying_risk * eff_delta)
        opt_reward = max(tick_size * 2, underlying_reward * eff_delta)
        opt_entry = float(option_ltp)
        opt_sl = max(tick_size, opt_entry - opt_risk)
        opt_tp = opt_entry + opt_reward
        rr = opt_reward / opt_risk if opt_risk > 0 else signal.rr
        
        return Signal(
            type="LONG",  # Option buying is always LONG on the option contract
            reason=f"{signal.reason} [OptTranslated {signal.type}->{option_symbol}]",
            entry=opt_entry,
            sl=opt_sl,
            tp=opt_tp,
            rr=rr,
            model_label=signal.model_label,
            symbol=option_symbol,
            timestamp=signal.timestamp,
        )
