"""PositionManager — exit evaluation and pyramid management.

Extracted from QuantEngine to improve locality: position management is a
single concern (evaluate exits, manage pyramids) with its own state.
The manager receives dependencies via constructor injection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from quant.contracts.enums import MarketState
from quant.contracts.vocabulary import absorption_direction
from quant.decision.stops import structural_stop
from quant.execution.exits import ExitDecision, ExitEngine
from quant.execution.ports import IOMS
from quant.execution.risk import SessionRisk
from quant.events import (
    Event, PositionClosed, PositionOpened, PositionReduced, RiskUpdated,
    StopMoved,
)
from quant.session_gates import session_allow_entry, session_force_exit, ist_dt as _ist_dt
from quant.amt.session.context import get_session_info, seconds_to_close

if TYPE_CHECKING:
    from quant.execution.order import Position

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages position exits and pyramid add-ons.
    
    Dependencies are injected via constructor:
    - oms: IOMS implementation (PaperOMS or LiveOMS)
    - exits: ExitEngine for exit evaluation
    - risk: SessionRisk for trade recording
    - emit_fn: Callable that emits events to the bus
    - symbol: The instrument symbol
    - market: Exchange market (NSE/MCX)
    - contract_expiry: Option contract expiry date
    - tick_size: Minimum price increment
    - get_depth: Callable returning current order book
    - get_amt_dto: Callable returning current AMT DTO
    - get_snapshot: Callable returning current AnalysisSnapshot (preferred on exit path)
    - portfolio_risk: Optional PortfolioRiskAuthority for cross-engine aggregate risk ceiling (E11)
    """

    def __init__(
        self,
        oms: IOMS,
        exits: ExitEngine,
        risk: SessionRisk,
        emit_fn: Callable[[Event], None],
        symbol: str,
        market: str,
        contract_expiry,
        tick_size: float,
        get_depth: Callable[[], object | None] = lambda: None,
        get_amt_dto: Callable[[], dict | None] = lambda: None,
        get_snapshot: Callable[[], object | None] = lambda: None,
        portfolio_risk=None,  # PortfolioRiskAuthority or None (paper mode may omit)
    ) -> None:
        self._oms: IOMS = oms
        self._exits = exits
        self._risk = risk
        self._emit = emit_fn
        self.symbol = symbol
        self._market = market
        self._contract_expiry = contract_expiry
        self._tick_size = tick_size
        self._get_depth = get_depth
        self._get_amt_dto = get_amt_dto
        self._get_snapshot = get_snapshot
        # E11: cross-engine aggregate risk ceiling for pyramid add-ons.
        self._portfolio_risk = portfolio_risk

        # Pyramid state
        self.pyramid_count: int = 0
        self.pyramid_positions: list = []
        # Current open position (None if flat). Used by OMS operations.
        # The engine's state.position holds the immutable PositionState;
        # this holds the live Position object for OMS calls.
        self.current_position: Position | None = None
        # Ratcheted base position produced by the latest pyramid fill. Consumed
        # (and cleared) by manage_exit's own return so the trail state keyed by
        # _id stays consistent with ExitEngine.
        self.base_override: Position | None = None
        # Reserved rupee risk per open pyramid add-on, keyed by position _id.
        self._pyramid_open_risk: dict[str, float] = {}
        # Fill for the most recent FULL close (None otherwise) — callers that
        # need the closing pnl (e.g. releasing a risk-authority reservation)
        # read this right after manage_exit() returns.
        self.last_fill = None
        self.last_partial_fill = None
        self.last_pyramid_pnl = 0.0
        # Double-close guard: position _ids that have already been fully closed.
        self._closed_ids: set[str] = set()

    def _get_lots(self, position) -> float:
        """Lot count of the live position.

        be9609ae added the call sites for lot-aware partial exits but never
        defined this helper — every partial-exit, BE-arm and tier decision
        crashed with AttributeError. Uses the IOMS lot_size port (Position.size
        is signed; lot_size > 0 is guaranteed by the port contract).
        """
        if position is None:
            return 0.0
        return abs(float(position.size)) / self._oms.lot_size

    def _emit_stop_moves(self, position, bar, prev_be, prev_trail,
                         be_floor, trail_stop) -> None:
        """Journal protective-stop level changes detected this bar."""
        sig_sl = float(position.order.signal.sl)
        long = position.size > 0
        if be_floor is not None and prev_be is None:
            # Breakeven floor armed at entry — via the 0.8R/CVD trailing path
            # on surviving bars, or via TP1 when the caller invokes this from
            # the partial-exit branch.
            self._emit(StopMoved(symbol=self.symbol, time=bar.time,
                                 old_sl=sig_sl, new_sl=float(be_floor),
                                 reason="BREAKEVEN_ARMED",
                                 position_id=str(position._id), stop_kind="BREAKEVEN"))
        tightened = (
            trail_stop is not None
            and (prev_trail is None
                 or (trail_stop > prev_trail if long else trail_stop < prev_trail))
        )
        if tightened:
            self._emit(StopMoved(symbol=self.symbol, time=bar.time,
                                 old_sl=float(prev_trail if prev_trail is not None else sig_sl),
                                 new_sl=float(trail_stop),
                                 reason="TRAIL_RATCHET",
                                 position_id=str(position._id), stop_kind="TRAIL"))

    def manage_exit(
        self,
        amt_dto: dict,
        bar,
        position,
        bar_index: int,
        entry_bar_index: int,
        entry_time_epoch: float,
        snapshot=None,
    ):
        """Evaluate exit conditions for an open position.

        Returns the position that survives this bar — unchanged, reduced by a
        tiered take-profit partial (spec §13.3), or None if it was closed
        entirely. If the latest pyramid fill ratcheted the base SL, returns the
        ratcheted base Position instead of the original (base_override lifecycle).
        """
        self.last_fill = None
        self.last_partial_fill = None
        self.last_pyramid_pnl = 0.0
        # Store current position for _manage_exit to access
        self.current_position = position
        # If position is None, nothing to evaluate
        if position is None:
            return None
        # Consume-and-clear any ratcheted base from the previous bar's pyramid fill.
        self.base_override = None
        if snapshot is None:
            snapshot = self._get_snapshot()
        amt_dto = amt_dto or self._get_amt_dto() or {}
        held_bars = bar_index - entry_bar_index
        if session_force_exit(
            bar.time, market=self._market, contract_expiry=self._contract_expiry
        ):
            exit_dec = ExitDecision(True, "SESSION_CLOSE", bar.close)
        else:
            book = self._get_depth()
            best_bid = float(book.bids[0].price) if book and book.bids else None
            best_ask = float(book.asks[0].price) if book and book.asks else None
            ist_dt = _ist_dt(bar.time)
            r = snapshot.result if snapshot is not None else None
            if r is not None and getattr(r, "market_state", None):
                raw_ms = str(r.market_state).upper()
            else:
                raw_ms = str(amt_dto.get("marketState") or "BALANCED").upper()
            if raw_ms == "IMBALANCED":
                market_state = MarketState.IMBALANCED
            elif raw_ms == "DEAD":
                market_state = MarketState.DEAD
            else:
                market_state = MarketState.BALANCED
            if ist_dt is not None:
                info = get_session_info(bar.time, market=self._market)
                session_phase = str(info.session)
                is_expiry = (
                    self._contract_expiry is not None
                    and ist_dt.date() == self._contract_expiry
                )
                time_to_close = seconds_to_close(bar.time, exchange=self._market)
                now_epoch = ist_dt.timestamp()
            else:
                session_phase, is_expiry, time_to_close, now_epoch = "", False, 0.0, 0.0
            if r is not None:
                session_vwap = float(getattr(r, "session_vwap", 0) or 0)
            else:
                session_vwap = float(amt_dto.get("sessionVwap") or 0.0)

            # Capture stop state before evaluation so any change (BE arm,
            # trail ratchet) is audited via StopMoved — silent stop moves are
            # a verified defect; every move must be journaled.
            prev_be, prev_trail = self._exits.stop_state(position)

            exit_dec = self._exits.evaluate(
                position, amt_dto, bar_index=held_bars,
                bar_high=bar.high, bar_low=bar.low,
                best_bid=best_bid, best_ask=best_ask,
                market_state=market_state, session_phase=session_phase,
                is_expiry=is_expiry, time_to_close=time_to_close,
                entry_time_epoch=entry_time_epoch,
                now_epoch=now_epoch,
                bar_close=bar.close,
                session_vwap=session_vwap,
                snapshot=snapshot,
            )

            # Emit StopMoved for any stop-level change detected this bar.
            # Full-close bars are excluded: no position survives, and the
            # exit is journaled through its own PositionClosed chain instead.
            if not exit_dec.should_exit:
                self._emit_stop_moves(position, bar, prev_be, prev_trail,
                                      *self._exits.stop_state(position))

        if exit_dec.should_exit:
            if (
                exit_dec.partial_fraction is not None
                and exit_dec.partial_fraction < 1.0
                and self._get_lots(position) >= 2
            ):
                partial_fill, remaining = self._oms.close_partial(
                    position, exit_dec.partial_fraction, exit_dec.close_price,
                    bar.time, exit_dec.reason,
                )
                # Remaining below one lot → treat as full close (no ghost size-0).
                if abs(remaining.size) < float(getattr(self._oms, "lot_size", 1.0) or 1.0) * 0.5:
                    self._exits.apply_pending_tp(position, exit_dec)
                    self._execute_full_close(position, exit_dec, bar.time)
                    return None
                self._exits.apply_pending_tp(position, exit_dec)
                self._emit(PositionReduced(
                    symbol=self.symbol,
                    time=bar.time,
                    fill=partial_fill,
                    remaining=remaining,
                ))
                risk = self._risk.record_trade(partial_fill.pnl, count_as_trade=False)
                logger.info(
                    "🎯 [TIERED TP] %s reason=%s closed=%.0f remaining=%.0f pnl=₹%.2f",
                    self.symbol, exit_dec.reason, abs(partial_fill.position.size),
                    abs(remaining.size), partial_fill.pnl,
                )
                self._emit(RiskUpdated(symbol=self.symbol, time=bar.time, risk=risk))
                self.last_partial_fill = partial_fill
                # A TP1 bar can arm the BE floor inside evaluate() — that is
                # still a stop move; journal it for the surviving runner.
                self._emit_stop_moves(position, bar, prev_be, prev_trail,
                                      *self._exits.stop_state(position))
                return remaining

            # _execute_full_close now returns the closing Fill (or None on a
            # guarded skip); manage_exit's contract is the SURVIVING position,
            # so a full close must still report None to the caller.
            self._exits.apply_pending_tp(position, exit_dec)
            self._execute_full_close(position, exit_dec, bar.time)
            return None
        else:
            # Position survived this bar. Check if we can add a pyramid.
            if position is not None and self._exits.is_risk_free(
                position, mark=float(bar.close),
            ):
                self.check_pyramid(amt_dto, bar, position, bar_index, snapshot=snapshot)
            # Consume-and-clear the ratcheted base produced by check_pyramid.
            survived = self.base_override if self.base_override is not None else position
            self.base_override = None
            return survived

    def _execute_full_close(
        self, position, exit_dec: ExitDecision, time_str: str,
        *, count_as_trade: bool = True,
    ):
        """Execute full position close and release risk/pyramid state.

        Double-close is prevented by the _closed_ids guard.

        Returns the closing ``Fill`` on success, or ``None`` when the
        double-close guard skipped the close (nothing was executed, so
        callers must not read ``last_fill`` or release risk against it).

        ``count_as_trade=False`` books the P&L but does NOT increment
        ``trades_today`` or move the win/loss streaks — used by the EOD
        pyramid-only flatten, which is bookkeeping, not a new round-trip.
        """
        # Double-close guard: skip if this position was already closed.
        pos_id = getattr(position, '_id', None) or getattr(position, 'id', None)
        if pos_id is None:
            # A position without an id cannot be guarded, closed against the
            # broker, or matched to its PositionClosed event — refusing to
            # proceed prevents a silent add of None to _closed_ids and a
            # phantom close the event fold could never reconcile.
            raise ValueError(
                f"{self.symbol}: cannot close a position without an id "
                f"(type={type(position).__name__})"
            )
        if pos_id in self._closed_ids:
            logger.warning(
                "⚠️ [DOUBLE-CLOSE GUARD] %s position %s already closed — skipping",
                self.symbol, str(pos_id)[:8],
            )
            return None

        # Exit-source truthfulness: closes that bypass ExitEngine.evaluate()
        # (thesis flip, EOD square-off, tick-path TP) carry their own
        # ExitDecision, so last_exit_source would otherwise log a stale value
        # from an earlier bar (or empty). Stamp the deterministic reason unless
        # the engine already named this exact reason itself.
        _engine_reason = self._exits.last_exit_source.rpartition(":")[2]
        if exit_dec.reason and _engine_reason != exit_dec.reason:
            self._exits.last_exit_source = f"DETERMINISTIC:{exit_dec.reason}"

        fill = self._oms.close(position, exit_dec.close_price, time_str, exit_dec.reason)
        self.last_fill = fill
        self._exits.pop_trail(position)
        # Reset pyramid state: close all pyramid add-ons at the same price.
        # Collect (pyr_pos, its_fill) pairs — the E11 release below must pair
        # each add-on with its OWN fill pnl, not a loop-leaked leftover.
        closed_pyrs: list[tuple[object, object]] = []
        for pyr_pos in self.pyramid_positions:
            pyr_fill = self._oms.close(pyr_pos, exit_dec.close_price, time_str, exit_dec.reason + "_PYRAMID")
            self._exits.pop_trail(pyr_pos)
            self._risk.record_trade(pyr_fill.pnl, count_as_trade=False)
            self._emit(PositionClosed(symbol=self.symbol, time=time_str, fill=pyr_fill))
            self.last_pyramid_pnl += float(pyr_fill.pnl)
            closed_pyrs.append((pyr_pos, pyr_fill))
            logger.info(
                "🔒 [PYRAMID CLOSED] %s level=%d reason=%s pnl=₹%.2f",
                self.symbol, pyr_pos.pyramid_level, exit_dec.reason, pyr_fill.pnl,
            )

        # E11 FIX — release the aggregate open risk reserved for these add-ons.
        if self._portfolio_risk is not None and closed_pyrs:
            released = 0.0
            for pyr_pos, pyr_fill in closed_pyrs:
                risk_i = self._pyramid_open_risk.pop(pyr_pos._id, 0.0)
                self._portfolio_risk.record_close(risk_i, float(pyr_fill.pnl))
                released += risk_i
            logger.info(
                "🔒 [PYRAMID RISK RELEASED] %s released ₹%.2f pyramid open risk (total portfolio open: ₹%.2f)",
                self.symbol, released, self._portfolio_risk.open_risk,
            )

        self.pyramid_positions = []
        self.pyramid_count = 0
        self.current_position = None
        self._closed_ids.add(pos_id)  # Mark as closed
        self._emit(PositionClosed(symbol=self.symbol, time=time_str, fill=fill))
        risk = self._risk.record_trade(fill.pnl, count_as_trade=count_as_trade)
        try:
            budget_mult = float(self._exits.session_budget_multiplier())
        except Exception:
            budget_mult = 1.0
        logger.info(
            "🔒 [POSITION CLOSED] %s reason=%s pnl=₹%.2f daily_pnl=₹%.2f "
            "trades=%d/%d equity=₹%.0f halted=%s exit_source=%s budget_mult=%.2f",
            self.symbol, exit_dec.reason, fill.pnl,
            risk.daily_pnl, risk.trades_today,
            6,  # max_trades_per_session
            risk.equity, risk.halted,
            self._exits.last_exit_source,
            budget_mult,
        )
        self._emit(RiskUpdated(symbol=self.symbol, time=time_str, risk=risk))
        return fill

    def manage_tick_exit(self, position, tick_price: float, tick_time: str):
        """Tick-level exit — routes through ExitEngine.evaluate_price_event."""
        if position is None:
            return None
        px = float(tick_price)
        exit_dec = self._exits.evaluate_price_event(
            position, last=px, high=px, low=px, source="tick",
        )
        if not exit_dec.should_exit:
            return position

        # Live fill at the tick print; reason comes from the shared resolver.
        fill_dec = ExitDecision(
            True,
            exit_dec.reason,
            px,
            partial_fraction=exit_dec.partial_fraction,
            pending_tp_tier=exit_dec.pending_tp_tier,
            pending_breakeven=exit_dec.pending_breakeven,
            trail_stop=exit_dec.trail_stop,
        )

        if exit_dec.partial_fraction and exit_dec.partial_fraction < 1.0:
            if self._get_lots(position) < 2:
                # Small size: collapse to a full close (matches prior tick path).
                reason = "TP" if exit_dec.reason == "TP1" else exit_dec.reason
                self._execute_full_close(
                    position, ExitDecision(True, reason, px), tick_time,
                )
                return None
            partial_fill, remaining = self._oms.close_partial(
                position, float(exit_dec.partial_fraction), px, tick_time, exit_dec.reason,
            )
            self._emit(PositionReduced(
                symbol=self.symbol,
                time=tick_time,
                fill=partial_fill,
                remaining=remaining,
            ))
            risk = self._risk.record_trade(partial_fill.pnl, count_as_trade=False)
            self._emit(RiskUpdated(symbol=self.symbol, time=tick_time, risk=risk))
            self.last_partial_fill = partial_fill
            survivor = remaining if remaining is not None else position
            self._exits.apply_pending_tp(survivor, exit_dec)
            return remaining

        self._exits.apply_pending_tp(position, fill_dec)
        self._execute_full_close(position, fill_dec, tick_time)
        return None

    @staticmethod
    def _resolve_leg_lvn(src, close_px: float) -> float:
        """Compatibility wrapper around the canonical LVN resolver."""
        from quant.amt.profile.leg_lvn import resolve_leg_lvn
        return resolve_leg_lvn(src, close_px).level

    def check_pyramid(
        self, amt_dto: dict, bar, position, bar_index: int, *, snapshot=None,
    ) -> None:
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

        # Gate 1 (spec §13.2): base trade must be risk-free (protective stop at
        # or better than fill). Do not pass the retest mark — an LVN pullback
        # is often below entry while BE is locked; mark-aware is_risk_free is
        # for explicit profit checks (exit parity contract), not pyramid auth.
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
        leg_src = snapshot if snapshot is not None else amt_dto
        leg_lvn = self._resolve_leg_lvn(leg_src, float(bar.close))
        if leg_lvn <= 0:
            return  # No Layer 3 LVN available yet

        price = float(bar.close)
        tick = self._tick_size
        from quant.amt.profile.leg_lvn import leg_lvn_retest_tolerance
        profile = amt_dto.get("legProfile") or []
        prices = []
        for level in profile:
            try:
                prices.append(float(level.get("price") if isinstance(level, dict) else level.price))
            except (AttributeError, TypeError, ValueError):
                continue
        bucket_width = abs(prices[1] - prices[0]) if len(prices) > 1 else tick
        leg_range = abs(max(prices) - min(prices)) if prices else 0.0
        tolerance = leg_lvn_retest_tolerance(tick, bucket_width, leg_range)
        if abs(price - leg_lvn) > tolerance:
            return  # Price not at the traceable LVN retest zone

        # Need fresh absorption at the LVN
        absorption_side = amt_dto.get("absorptionSide") or ""
        if not absorption_side:
            return  # No fresh absorption this bar

        long = position.size > 0

        # Absorption direction must agree with the open position (canonical
        # semantics: SELL_ABSORBED bullish, BUY_ABSORBED bearish).
        absorbed = absorption_direction(absorption_side)
        if long and absorbed != "LONG":
            return
        if not long and absorbed != "SHORT":
            return

        # Candle close must confirm the direction
        if long and float(bar.close) < float(bar.open):
            return  # Bearish candle at LVN for a long — skip
        if not long and float(bar.close) > float(bar.open):
            return  # Bullish candle at LVN for a short — skip

        # Size: 50% of base for P1, 25% for P2 — floor to lots; skip if sub-lot.
        base_size = abs(position.size)
        fraction = 0.50 if self.pyramid_count == 0 else 0.25
        pyramid_size = base_size * fraction
        lot = float(getattr(self._oms, "lot_size", 1.0) or 1.0)
        from quant.execution.lots import snap_to_lot_floor
        snapped = snap_to_lot_floor(pyramid_size, lot)
        if snapped <= 0:
            logger.info(
                "🛑 [PYRAMID SKIP] %s P%d: size %.2f < 1 lot — not upsizing",
                self.symbol, self.pyramid_count + 1, pyramid_size,
            )
            return
        pyramid_size = snapped

        # New SL behind the LVN shelf
        new_sl = structural_stop("LONG" if long else "SHORT", price, leg_lvn, tick)

        try:
            pyramid_pos = self._oms.add_pyramid(
                base=position,
                entry_price=price,
                new_sl=new_sl,
                size=pyramid_size,
                time=bar.time,
                pyramid_level=self.pyramid_count + 1,
            )
        except (ValueError, NotImplementedError, Exception) as exc:
            # CRIT-01 FIX: Unsupported pyramid in LiveOMS or oms failure must
            # log a warning and skip the pyramid instead of crashing QuantEngine.
            logger.warning("⚠️ [PYRAMID UNSUPPORTED/FAILED] %s P%d: %s", self.symbol, self.pyramid_count + 1, exc)
            return

        if pyramid_pos is None:
            return

        # E11 FIX — reserve aggregate portfolio risk for the add-on BEFORE we
        # commit. Without this, pyramids bypassed the cross-engine ceiling
        # (8 engines × 0.5% each would otherwise risk ~4% per engine on top of
        # the base). Reserve at fill time; release via record_close when the
        # pyramid is closed in manage_exit(). Checked BEFORE the count/append
        # so a refusal leaves no counted-but-unreserved ghost pyramid.
        add_risk = abs(float(pyramid_pos.order.signal.entry) - float(new_sl)) * max(1.0, abs(pyramid_size))
        if self._portfolio_risk is not None:
            ok, why = self._portfolio_risk.can_accept(add_risk, symbol=self.symbol, is_pyramid=True)
            if not ok:
                logger.info("🛑 [PYRAMID RISK] %s refused: %s", self.symbol, why)
                return
            if not self._portfolio_risk.register_open(add_risk, symbol=self.symbol, is_pyramid=True):
                logger.info("🛑 [PYRAMID RISK] %s refused at register", self.symbol)
                return
            self._pyramid_open_risk[pyramid_pos._id] = add_risk

        self.pyramid_count += 1
        self.pyramid_positions.append(pyramid_pos)

        if self._portfolio_risk is not None:
            logger.info(
                "⚡ [PYRAMID RISK] %s P%d registered ₹%.2f open risk (total portfolio open: ₹%.2f)",
                self.symbol, self.pyramid_count, add_risk, self._portfolio_risk.open_risk,
            )

        # E10 FIX — base-SL ratchet: the docstring promises the combined bundle
        # (base + pyramids) is guaranteed positive, so the base position's SL
        # must be ratcheted to the pyramid's new_sl at fill time. Position/Signal
        # are frozen dataclasses; rebuild via dataclasses.replace (same pattern as
        # partial-fill Position reconstruction). _id survives -> ExitEngine trail
        # state keyed by _id stays consistent. Only tighten, never widen.
        long = position.size > 0
        cur_sl = float(position.order.signal.sl)
        new_base_sl = float(new_sl)
        if (long and new_sl > cur_sl) or (not long and new_sl < cur_sl):
            from dataclasses import replace as _dc_replace

            ratcheted = _dc_replace(
                position,
                order=_dc_replace(position.order, signal=_dc_replace(position.order.signal, sl=new_base_sl)),
            )
            self.base_override = ratcheted
            self._emit(StopMoved(symbol=self.symbol, time=bar.time, old_sl=cur_sl,
                                 new_sl=float(new_sl), reason="PYRAMID_RATCHET",
                                 position_id=str(position._id), stop_kind="PYRAMID_BASE"))

        logger.info(
            "⚡ [PYRAMID ADD] %s P%d @ %.2f size=%.0f SL=%.2f LVN=%.2f | base SL ratcheted %.2f -> %.2f",
            self.symbol, self.pyramid_count, price, pyramid_size, new_sl, leg_lvn, cur_sl, float(new_sl),
        )
        self._emit(PositionOpened(symbol=self.symbol, time=bar.time, position=pyramid_pos))
