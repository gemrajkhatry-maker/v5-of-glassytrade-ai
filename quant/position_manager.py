"""PositionManager — exit evaluation and pyramid management.

Extracted from QuantEngine to improve locality: position management is a
single concern (evaluate exits, manage pyramids) with its own state.
The manager receives dependencies via constructor injection.
"""

from __future__ import annotations

import logging
from typing import Callable

from quant.contracts.enums import MarketState
from quant.execution.exits import ExitDecision, ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk
from quant.events import Event, PositionClosed, PositionOpened, RiskUpdated
from quant.session_gates import session_allow_entry, session_force_exit, ist_dt as _ist_dt
from quant.amt.session.context import get_session_info, is_expiry_day, seconds_to_close

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages position exits and pyramid add-ons.
    
    Dependencies are injected via constructor:
    - oms: PaperOMS for position management
    - exits: ExitEngine for exit evaluation
    - risk: SessionRisk for trade recording
    - emit_fn: Callable that emits events to the bus
    - symbol: The instrument symbol
    - market: Exchange market (NSE/MCX)
    - contract_expiry: Option contract expiry date
    - tick_size: Minimum price increment
    - get_depth: Callable returning current order book
    - get_amt_dto: Callable returning current AMT DTO
    """

    def __init__(
        self,
        oms: PaperOMS,
        exits: ExitEngine,
        risk: SessionRisk,
        emit_fn: Callable[[Event], None],
        symbol: str,
        market: str,
        contract_expiry,
        tick_size: float,
        get_depth: Callable[[], object | None] = lambda: None,
        get_amt_dto: Callable[[], dict | None] = lambda: None,
    ) -> None:
        self._oms = oms
        self._exits = exits
        self._risk = risk
        self._emit = emit_fn
        self.symbol = symbol
        self._market = market
        self._contract_expiry = contract_expiry
        self._tick_size = tick_size
        self._get_depth = get_depth
        self._get_amt_dto = get_amt_dto

        # Pyramid state
        self.pyramid_count: int = 0
        self.pyramid_positions: list = []

    def manage_exit(
        self,
        amt_dto: dict,
        bar,
        position,
        bar_index: int,
        entry_bar_index: int,
        entry_time_epoch: float,
    ) -> bool:
        """Evaluate exit conditions for an open position.
        
        Returns True if the position was closed, False if it survived.
        """
        held_bars = bar_index - entry_bar_index
        if session_force_exit(
            bar.time, market=self._market, contract_expiry=self._contract_expiry
        ):
            exit_dec = ExitDecision(True, "SESSION_CLOSE", float(bar.close))
        else:
            book = self._get_depth()
            best_bid = float(book.bids[0].price) if book and book.bids else None
            best_ask = float(book.asks[0].price) if book and book.asks else None
            ist_dt = _ist_dt(bar.time)
            # Use the passed-in amt_dto (from the engine's analyze() call)
            # instead of re-reading last_amt_dto which could be stale.
            raw_ms = str(amt_dto.get("marketState") or "BALANCED").upper()
            if raw_ms == "IMBALANCED":
                market_state = MarketState.IMBALANCED
            else:
                market_state = MarketState.BALANCED
            if ist_dt is not None:
                info = get_session_info(bar.time, market=self._market)
                session_phase = str(info.session)
                is_expiry = (
                    self._market == "NSE" and is_expiry_day(ist_dt.date())
                ) or (
                    self._contract_expiry is not None
                    and ist_dt.date() == self._contract_expiry
                )
                time_to_close = seconds_to_close(bar.time, exchange=self._market)
                now_epoch = ist_dt.timestamp()
            else:
                session_phase, is_expiry, time_to_close, now_epoch = "", False, 0.0, 0.0
            exit_dec = self._exits.evaluate(
                position, amt_dto, bar_index=held_bars,
                bar_high=bar.high, bar_low=bar.low,
                best_bid=best_bid, best_ask=best_ask,
                market_state=market_state, session_phase=session_phase,
                is_expiry=is_expiry, time_to_close=time_to_close,
                entry_time_epoch=entry_time_epoch,
                now_epoch=now_epoch,
                bar_close=bar.close,
            )
        if exit_dec.should_exit:
            fill = self._oms.close(position, exit_dec.close_price, bar.time,
                                   exit_dec.reason)
            self._exits.pop_trail(position)
            # Reset pyramid state: close all pyramid add-ons at the same price
            for pyr_pos in self.pyramid_positions:
                pyr_fill = self._oms.close(pyr_pos, exit_dec.close_price, bar.time,
                                           exit_dec.reason + "_PYRAMID")
                self._exits.pop_trail(pyr_pos)
                self._risk.record_trade(pyr_fill.pnl)
                logger.info(
                    "🔒 [PYRAMID CLOSED] %s level=%d reason=%s pnl=₹%.2f",
                    self.symbol, pyr_pos.pyramid_level, exit_dec.reason, pyr_fill.pnl,
                )
            self.pyramid_positions = []
            self.pyramid_count = 0
            self._emit(PositionClosed(symbol=self.symbol, time=bar.time, fill=fill))
            risk = self._risk.record_trade(fill.pnl)
            logger.info(
                "🔒 [POSITION CLOSED] %s reason=%s pnl=₹%.2f daily_pnl=₹%.2f "
                "trades=%d/%d equity=₹%.0f halted=%s",
                self.symbol, exit_dec.reason, fill.pnl,
                risk.daily_pnl, risk.trades_today,
                6,  # max_trades_per_session
                risk.equity, risk.halted,
            )
            self._emit(RiskUpdated(symbol=self.symbol, time=bar.time, risk=risk))
            return True
        else:
            # Position survived this bar. Check if we can add a pyramid.
            if position is not None and self._exits.is_risk_free(position):
                self.check_pyramid(amt_dto, bar, position, bar_index)
            return False

    def check_pyramid(self, amt_dto: dict, bar, position, bar_index: int) -> None:
        """Spec §13.2 pyramid engine: add-on positions at Impulse Leg LVN retest.

        Authorization gates (all must pass):
          1. Base trade is risk-free (SL at breakeven or better)
          2. Maximum 2 pyramid add-ons not yet reached
          3. Session allows entry (no force-exit window)
          4. Risk engine not halted

        Entry conditions (per bar):
          - Price is within 2 ticks of the Impulse Leg LVN (Layer 3 profile)
          - Fresh absorption (bar_age == 0) at the LVN in the trade direction
          - 1m candle closes in the trade direction (close confirms level)

        Sizing:
          Pyramid 1: 50% of base position size (absolute units)
          Pyramid 2: 25% of base position size (absolute units)

        SL ratchet: combined SL moves to LVN - 2*tick (LONG) / LVN + 2*tick
        (SHORT) so the entire bundle (base + pyramids) is always net positive.
        """
        if self.pyramid_count >= 2:
            return  # Max 2 add-ons reached

        # Gate 1 (spec §13.2): base trade must be risk-free (SL at breakeven
        # or better). Enforced HERE, not just in the manage_exit caller —
        # certification found the add-on path was unguarded against any
        # future/direct invocation pyramiding a losing base.
        if not self._exits.is_risk_free(position):
            return

        # Guard: session must allow new entries
        if not session_allow_entry(
            bar.time, market=self._market, contract_expiry=self._contract_expiry
        ):
            return

        # Guard: risk engine must be healthy
        can_trade, _ = self._risk.can_trade()
        if not can_trade:
            return

        # Need the Impulse Leg LVN from the AMT DTO — use the caller-passed
        # payload (event purity), not a fresh read of mutable state.
        amt_dto = amt_dto or self._get_amt_dto() or {}
        leg_lvn = float(amt_dto.get("legLvn") or 0.0)
        if leg_lvn <= 0:
            return  # No Layer 3 LVN available yet

        price = float(bar.close)
        tick = self._tick_size
        if abs(price - leg_lvn) > 2.0 * tick:
            return  # Price not at LVN zone

        # Need fresh absorption at the LVN
        absorption_side = amt_dto.get("absorptionSide") or ""
        if not absorption_side:
            return  # No fresh absorption this bar

        long = position.size > 0

        # Absorption direction must agree with the open position
        # "SELL_ABSORBED" is bullish (absorbed sellers), "BUY_ABSORBED" is bearish
        if long and absorption_side != "SELL_ABSORBED":
            return
        if not long and absorption_side != "BUY_ABSORBED":
            return

        # Candle close must confirm the direction
        if long and float(bar.close) < float(bar.open):
            return  # Bearish candle at LVN for a long — skip
        if not long and float(bar.close) > float(bar.open):
            return  # Bullish candle at LVN for a short — skip

        # Size: 50% of base for P1, 25% for P2
        base_size = abs(position.size)
        fraction = 0.50 if self.pyramid_count == 0 else 0.25
        pyramid_size = base_size * fraction

        # New SL behind the LVN shelf
        new_sl = (leg_lvn - 2.0 * tick) if long else (leg_lvn + 2.0 * tick)

        try:
            pyramid_pos = self._oms.add_pyramid(
                base=position,
                entry_price=price,
                new_sl=new_sl,
                size=pyramid_size,
                time=bar.time,
                pyramid_level=self.pyramid_count + 1,
            )
        except ValueError as exc:
            logger.debug("⏩ [PYRAMID SKIP] %s: %s", self.symbol, exc)
            return

        self.pyramid_count += 1
        self.pyramid_positions.append(pyramid_pos)

        logger.info(
            "⚡ [PYRAMID ADD] %s P%d @ %.2f size=%.0f SL=%.2f LVN=%.2f",
            self.symbol, self.pyramid_count, price, pyramid_size, new_sl, leg_lvn,
        )
        self._emit(PositionOpened(symbol=self.symbol, time=bar.time, position=pyramid_pos))
