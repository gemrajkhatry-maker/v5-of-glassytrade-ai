"""DecisionContextBuilder — constructs the DecisionContext from engine state.

Extracted from QuantEngine to improve locality: context construction is a
pure function of inputs (state, bar, AMT DTO, risk state) with no side
effects. The builder receives dependencies via constructor injection.
"""

from __future__ import annotations

import logging

from quant.contracts.enums import MarketState
from quant.contracts.instrument_registry import is_option_contract
from quant.decision.context import DecisionContext
from quant.session_gates import ist_dt, session_allow_entry
from quant.amt.session.context import get_session_info
from quant.bars import DEFAULT_INTERVAL_SEC
from quant.decision.data_quality import normalize_data_quality

logger = logging.getLogger(__name__)

# Deterministic conviction used for gate 4's probability check when the engine
# decides from the auction state alone (above the 0.55 min_probability
# threshold). The decision-critical path is 100% deterministic by design — no
# model inference is involved, so _decide never waits on external calls.
_DETERMINISTIC_CONVICTION = 0.7


def _print_levels_from_dto(amt_dto: dict, bar) -> tuple[float, float]:
    """Nearest big aggressive-print levels relative to the current close.

    A large BUY print below price acts as support; a large SELL print above
    acts as resistance (Fabio Gap #10: prints CREATE structural levels).
    "Big" = volume >= 2x the mean print volume. Returns (support, resistance)
    with 0.0 when absent.
    """
    prints = amt_dto.get("aggressivePrints") or []
    if not prints:
        return 0.0, 0.0
    px = float(getattr(bar, "close", 0) or 0) if bar is not None else 0.0
    if px <= 0:
        return 0.0, 0.0
    mean_vol = sum(float(p.get("volume") or 0) for p in prints) / len(prints)
    big = [p for p in prints if float(p.get("volume") or 0) >= 2.0 * mean_vol]
    support = max(
        (float(p["price"]) for p in big
         if p.get("side") == "BUY" and float(p["price"]) < px),
        default=0.0,
    )
    resistance = min(
        (float(p["price"]) for p in big
         if p.get("side") == "SELL" and float(p["price"]) > px),
        default=0.0,
    )
    return support, resistance


def _latest_stacked_imbalance(amt_dto: dict) -> tuple[str, int, float, float]:
    """Summarize the most recent stacked footprint imbalance.

    Returns (direction, magnitude, price_low, price_high). Empty/zero when no
    stacked imbalance exists in the latest footprint candle. Fabio: 3+
    consecutive 3:1 diagonal imbalances = institutional volume bubble.
    """
    fps = amt_dto.get("footprints") or {}
    if not fps:
        return "", 0, 0.0, 0.0
    latest_key = max(fps.keys())  # epoch-string keys sort chronologically
    levels = (fps[latest_key] or {}).get("levels") or []
    best_dir, best_n = "", 0
    run_dir, run_n, run_prices = "", 0, []
    for lvl in levels:
        if not lvl.get("stacked"):
            # close any open run only if direction differs; stacked flags mark
            # ALL levels of a run, so a non-stacked level ends the run
            run_dir, run_n, run_prices = "", 0, []
            continue
        d = "BUY" if lvl.get("ask", 0) > lvl.get("bid", 0) else "SELL"
        if d != run_dir:
            run_dir, run_n, run_prices = d, 1, [lvl.get("price", 0.0)]
        else:
            run_n += 1
            run_prices.append(lvl.get("price", 0.0))
        if run_n > best_n:
            best_dir, best_n = run_dir, run_n
            best_prices = list(run_prices)
    if best_n < 3:
        return "", 0, 0.0, 0.0
    return best_dir, best_n, min(best_prices), max(best_prices)


class DecisionContextBuilder:
    """Builds a DecisionContext from engine state and AMT analysis.

    The builder encapsulates the direction resolution logic (auction-state
    edge, absorption side, OBI imbalance, VA location) and the VWAP bias
    filter, producing a fully-populated DecisionContext ready for evaluation.
    """

    def _resolve_direction(self, amt_dto: dict, close_px: float, vah: float,
                           val: float, obi: float, ofi: float,
                           vwap_upper_1: float, vwap_lower_1: float,
                           market: str = "NSE") -> str | None:
        """Determine agent direction from AMT state (hierarchy of intent)."""
        raw_ms = str(amt_dto.get("marketState") or "BALANCED").upper()
        break_dir = str(amt_dto.get("breakDirection") or "").upper()
        break_type = str(amt_dto.get("breakType") or "").upper()
        triple_a_sig = str(amt_dto.get("tripleASignal") or "").upper()
        cvd_val = float(amt_dto.get("cvdSlope") or 0.0)

        cvd_threshold = 0.3 if str(market).upper() == "MCX" else 0.5
        if break_type == "INITIATIVE" and break_dir in ("UP", "DOWN"):
            # ponytail: CVD strongly opposing the break indicates absorption/exhaustion trap (Fabio Gap #2/#7)
            if break_dir == "DOWN" and cvd_val > cvd_threshold:
                return "LONG"
            if break_dir == "UP" and cvd_val < -cvd_threshold:
                return "SHORT"
            return "LONG" if break_dir == "UP" else "SHORT"
        if triple_a_sig in ("LONG", "SHORT"):
            return triple_a_sig
        if amt_dto.get("absorptionSide") in ("SELL_ABSORBED", "BUY_ABSORBED"):
            return {"SELL_ABSORBED": "LONG", "BUY_ABSORBED": "SHORT"}.get(amt_dto.get("absorptionSide"))
        if obi >= 0.20 and close_px > vwap_upper_1:
            return "LONG"
        if obi <= -0.20 and close_px < vwap_lower_1:
            return "SHORT"
        if cvd_val > cvd_threshold and (close_px > vah or ofi > 0.10):
            return "LONG"
        if cvd_val < -cvd_threshold and (close_px < val or ofi < -0.10):
            return "SHORT"
        if raw_ms == "IMBALANCED":
            if (vah > 0 and close_px > vah) or ofi > 0.10 or (close_px > vwap_upper_1):
                return "LONG"
            if (val > 0 and close_px < val) or ofi < -0.10 or (close_px < vwap_lower_1):
                return "SHORT"
        if raw_ms == "BALANCED":
            if val > 0 and close_px <= val and cvd_val >= -0.2:
                return "LONG"
            if vah > 0 and close_px >= vah and cvd_val <= 0.2:
                return "SHORT"
            if cvd_val > cvd_threshold:
                return "LONG"
            if cvd_val < -cvd_threshold:
                return "SHORT"
        return None

    @staticmethod
    def _nearest_leg_lvn(amt_dto: dict, close_px: float) -> float:
        """Derive nearest leg LVN from legLvns list or legLvn float."""
        leg_lvns_raw = amt_dto.get("legLvns")
        if isinstance(leg_lvns_raw, (list, tuple)) and leg_lvns_raw:
            valid_lvns = [float(x) for x in leg_lvns_raw if float(x) > 0]
            if valid_lvns:
                return min(valid_lvns, key=lambda x: abs(x - close_px))
        if amt_dto.get("legLvn"):
            return float(amt_dto.get("legLvn"))
        return 0.0

    def _build_setup_evidence(self, amt_dto: dict, agent_direction: str | None,
                              nearest_leg_lvn: float) -> object | None:
        """Construct SetupEvidence from AMT state.

        Evidence is derived EXCLUSIVELY from live DTO keys (triple-a phase /
        acceptance, drive flags, rejection flags, absorption side, leg LVNs).
        It is NOT derived from the analyzer's ``setup`` regime key
        (``TREND_MODEL``/``MEAN_REVERSION``/``RESPONSIVE_FADE``) — that is a
        market-regime taxonomy, not a playbook detection, and the legacy
        ``setupType``/``setupDirection``/``cvdAgrees`` DTO reads removed here
        had no producer (architectural review finding 5): a dead ``setupType``
        read made the VA_FADE/LVN_SNIPER fall-through arms and the direction
        fallback silently depend on a key that never arrived.
        """
        from quant.decision.setup_state import SetupEvidence
        setup_dir = str(agent_direction or "").upper()
        cvd_val = float(amt_dto.get("cvdSlope") or 0.0)
        cvd_agrees = bool(
            (setup_dir == "LONG" and cvd_val >= -0.2)
            or (setup_dir == "SHORT" and cvd_val <= 0.2)
        )
        rejection_at_high = bool(amt_dto.get("rejectionAtHigh"))
        rejection_at_low = bool(amt_dto.get("rejectionAtLow"))
        is_second_drive = bool(amt_dto.get("isSecondDrive"))
        drive_number = int(amt_dto.get("driveNumber") or 0)
        triple_phase = str(amt_dto.get("tripleAPhase") or "")
        triple_signal = str(amt_dto.get("tripleASignal") or "")

        if triple_phase == "AGGRESSION" and (triple_signal in ("LONG", "SHORT") or agent_direction in ("LONG", "SHORT")):
            direction = triple_signal or agent_direction
            accepted = bool(
                amt_dto.get("acceptanceAbove") if direction == "LONG"
                else amt_dto.get("acceptanceBelow")
            )
            if accepted:
                return SetupEvidence(
                    setup_type="TRIPLE_A", direction=direction,
                    absorption=True, accumulation=True, aggression=True,
                    acceptance=True, cvd_agrees=cvd_agrees,
                )
            # No A/R-engine acceptance for this direction: do NOT fabricate it.
            # Fall through — a different setup may still qualify; we never
            # claim Triple-A completeness from "machine says AGGRESSION" alone.
        if is_second_drive:
            return SetupEvidence(
                setup_type="SECOND_DRIVE",
                direction=setup_dir or ("SHORT" if rejection_at_high else "LONG"),
                drive_number=drive_number or 2, d1_rejected=True,
                rejection=rejection_at_high or rejection_at_low or bool(amt_dto.get("rejection")),
                cvd_agrees=cvd_agrees,
            )
        if rejection_at_high or rejection_at_low:
            direction = "SHORT" if rejection_at_high else "LONG"
            return SetupEvidence(
                setup_type="VA_FADE", direction=direction,
                rejection=rejection_at_high or rejection_at_low or bool(amt_dto.get("rejection")),
                acceptance=bool(amt_dto.get("acceptanceAbove") or amt_dto.get("acceptanceBelow") or amt_dto.get("acceptance", False)),
                cvd_agrees=cvd_agrees,
            )
        if nearest_leg_lvn > 0 and amt_dto.get("absorptionSide") in ("SELL_ABSORBED", "BUY_ABSORBED"):
            direction = "LONG" if amt_dto.get("absorptionSide") == "SELL_ABSORBED" else "SHORT"
            return SetupEvidence(
                setup_type="LVN_SNIPER", direction=direction,
                level=nearest_leg_lvn, absorption=True, cvd_agrees=cvd_agrees,
            )
        return None

    def _extract_position(self, position, close_px: float, bar_index: int,
                          entry_bar_index: int) -> dict:
        """Extract position state into a flat dict for DecisionContext.
        
        Supports Position (quant/execution/order.py), PositionState (quant/state_machine.py),
        and dict (frontend DTO / portfolio) transparently.
        """
        if position is None:
            return {"pos_open": False, "pos_side": "", "pos_entry": 0.0,
                    "pos_size": 0.0, "pos_sl": 0.0, "pos_tp": 0.0,
                    "pos_pnl": 0.0, "pos_bars_held": 0}

        if isinstance(position, dict):
            raw_sz = float(position.get("size", 0.0))
            pos_side = str(position.get("side", "")).upper() or ("LONG" if raw_sz > 0 else ("SHORT" if raw_sz < 0 else ""))
            pos_entry = float(position.get("entryPrice", 0.0) or position.get("entry", 0.0) or position.get("open_price", 0.0) or 0.0)
            pos_sl = float(position.get("stopLoss", 0.0) or position.get("sl", 0.0) or position.get("stop_loss", 0.0) or 0.0)
            pos_tp = float(position.get("takeProfit", 0.0) or position.get("tp", 0.0) or position.get("take_profit", 0.0) or 0.0)
            pos_pnl = float(position.get("pnl", 0.0))
            pos_bars_held = int(position.get("barsHeld", 0) or 0)
            if pos_bars_held == 0 and entry_bar_index > 0:
                pos_bars_held = max(0, bar_index - entry_bar_index)
            return {"pos_open": True, "pos_side": pos_side, "pos_entry": pos_entry,
                    "pos_size": raw_sz, "pos_sl": pos_sl, "pos_tp": pos_tp,
                    "pos_pnl": pos_pnl, "pos_bars_held": pos_bars_held}

        raw_sz = float(getattr(position, "size", 0.0))
        pos_side = str(getattr(position, "side", "") or "").upper() or ("LONG" if raw_sz > 0 else ("SHORT" if raw_sz < 0 else ""))
        pos_entry = float(
            getattr(position, "entry", 0.0)
            or getattr(position, "open_price", 0.0)
            or getattr(position, "entry_price", 0.0)
            or getattr(position, "entryPrice", 0.0)
            or 0.0
        )
        if hasattr(position, "order") and hasattr(position.order, "signal") and position.order.signal is not None:
            pos_sl = float(position.order.signal.sl or 0.0)
            pos_tp = float(position.order.signal.tp or 0.0)
        else:
            pos_sl = float(
                getattr(position, "sl", 0.0)
                or getattr(position, "stop_loss", 0.0)
                or getattr(position, "stopLoss", 0.0)
                or 0.0
            )
            pos_tp = float(
                getattr(position, "tp", 0.0)
                or getattr(position, "take_profit", 0.0)
                or getattr(position, "takeProfit", 0.0)
                or 0.0
            )
        mult = 1.0 if pos_side == "LONG" else (-1.0 if pos_side == "SHORT" else 1.0)
        pos_pnl = (close_px - pos_entry) * abs(raw_sz) * mult if close_px > 0 and pos_entry > 0 and raw_sz != 0 else float(getattr(position, "pnl", 0.0) or 0.0)
        pos_bars_held = max(0, bar_index - entry_bar_index) if entry_bar_index > 0 else int(getattr(position, "bars_held", 0) or 0)
        return {"pos_open": True, "pos_side": pos_side, "pos_entry": pos_entry,
                "pos_size": raw_sz, "pos_sl": pos_sl, "pos_tp": pos_tp,
                "pos_pnl": pos_pnl, "pos_bars_held": pos_bars_held}

    def build(
        self,
        bar,
        symbol: str,
        market: str,
        contract_expiry,
        tick_size: float,
        bar_index: int,
        warm_bars: int,
        cooldown_remaining_sec: float,
        risk_state,
        amt_dto: dict,
        order_book=None,
        interval_seconds: int = DEFAULT_INTERVAL_SEC,
        position=None,
        entry_bar_index: int = 0,
        recent_decisions: list | None = None,
    ) -> DecisionContext:
        """Build a DecisionContext from the given inputs.
        
        Args:
            bar: The closed Bar
            symbol: Instrument symbol
            market: Exchange market (NSE/MCX)
            contract_expiry: Option contract expiry date
            tick_size: Minimum price increment
            bar_index: Current bar count
            warm_bars: Number of seeded history bars
            cooldown_remaining_sec: Cooldown time remaining in seconds
            risk_state: Current RiskState
            amt_dto: AMT analysis DTO
            interval_seconds: Bar interval in seconds
            
        Returns:
            A fully-populated DecisionContext
        """
        warmup_bars = 15
        obi = float(amt_dto.get("obi") or 0.0)
        close_px = float(bar.close if bar else 0.0)
        vah = float(amt_dto.get("valueAreaHigh") or 0.0)
        val = float(amt_dto.get("valueAreaLow") or 0.0)
        ofi = float(amt_dto.get("ofi") or 0.0)
        vwap_upper_1 = float(amt_dto.get("vwapUpper1") or float("inf"))
        vwap_lower_1 = float(amt_dto.get("vwapLower1") or float("-inf"))
        best_bid = 0.0
        best_ask = 0.0
        if order_book is not None:
            bids = getattr(order_book, "bids", ()) or ()
            asks = getattr(order_book, "asks", ()) or ()
            if bids: best_bid = float(bids[0].price)
            if asks: best_ask = float(asks[0].price)

        # Session & Expiry
        bar_text = str(bar.time if bar else "").strip()
        is_epoch = bar_text.replace(".", "", 1).lstrip("-").isdigit() and len(bar_text) >= 9 and "T" not in bar_text
        is_iso = "T" in bar_text or "+" in bar_text or ":" in bar_text
        session_info = None
        if is_epoch or is_iso:
            try: session_info = get_session_info(bar.time, market=market)
            except Exception: pass
        session_phase = session_info.session if session_info else "PRIMARY"
        bar_dt = ist_dt(bar.time) if (bar and bar.time and (is_epoch or is_iso)) else None
        is_expiry = (bar_dt.date() == contract_expiry) if (contract_expiry and bar_dt) else False

        # Direction, Setup, Position via extracted helpers
        agent_direction = self._resolve_direction(amt_dto, close_px, vah, val, obi, ofi, vwap_upper_1, vwap_lower_1, market=market)
        nearest_leg_lvn = self._nearest_leg_lvn(amt_dto, close_px)
        setup_evidence = self._build_setup_evidence(amt_dto, agent_direction, nearest_leg_lvn)
        # ponytail: a confirmed structural setup evidence establishes the trade direction
        if setup_evidence and getattr(setup_evidence, "direction", None) and getattr(setup_evidence, "is_complete", lambda: False)():
            agent_direction = setup_evidence.direction
        if is_option_contract(symbol) and agent_direction == "SHORT":
            # Retail scalpers are option buyers (long calls / long puts) with defined risk.
            # Shorting naked options is disabled.
            agent_direction = None
        pos = self._extract_position(position, close_px, bar_index, entry_bar_index)
        _si_dir, _si_mag, _si_low, _si_high = _latest_stacked_imbalance(amt_dto)
        _buy_wall_below, _sell_wall_above = _print_levels_from_dto(amt_dto, bar)

        # Squeeze (Fabio Playbook #4): direction + trapped level from Task 2a's
        # DTO keys; pullback = a retest of the trapped VA level within 3 ticks.
        squeeze_dir = str(amt_dto.get("squeezeDirection", ""))
        trapped_lvl = float(amt_dto.get("squeezeTrappedLevel", 0.0))
        pullback = False
        if squeeze_dir and trapped_lvl > 0 and bar is not None:
            tick = tick_size or 0.05
            pullback = abs(float(bar.close) - trapped_lvl) <= 3.0 * tick  # ponytail: retest proxy; proper LVN-pullback when leg_lvn lands near trapped level

        # Market state + break info
        raw_ms = str(amt_dto.get("marketState") or "BALANCED").upper()
        break_dir = str(amt_dto.get("breakDirection") or "").upper()
        break_type = str(amt_dto.get("breakType") or "").upper()
        if raw_ms == "DEAD": amt_market_state = "DEAD"
        elif raw_ms == "IMBALANCED": amt_market_state = MarketState.IMBALANCED
        else: amt_market_state = MarketState.BALANCED

        bar_time = bar.time if bar is not None else str(amt_dto.get("time") or "")
        allow_trend = session_info.allow_trend if session_info else True
        allow_reversion = session_info.allow_reversion if session_info else True

        return DecisionContext(
            state=None,
            bar=bar,
            symbol=symbol,
            market=market,
            session_open=session_allow_entry(
                bar_time, market=market, contract_expiry=contract_expiry
            ) if bar_time else True,
            warmup_complete=(bar_index + warm_bars) >= warmup_bars,
            position_open=pos["pos_open"],
            position_side=pos["pos_side"],
            position_entry_price=pos["pos_entry"],
            position_size=pos["pos_size"],
            position_unrealized_pnl=pos["pos_pnl"],
            position_sl=pos["pos_sl"],
            position_tp=pos["pos_tp"],
            position_bars_held=pos["pos_bars_held"],
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_halted=risk_state.halted,
            consecutive_losses=risk_state.consecutive_losses,
            agent_direction=agent_direction,
            agent_probability=_DETERMINISTIC_CONVICTION,
            data_quality=(
                normalize_data_quality(
                    amt_dto.get("dataQuality") or amt_dto.get("data_quality")
                )
                if ("dataQuality" in amt_dto or "data_quality" in amt_dto)
                else None
            ),
            setup_evidence=setup_evidence,
            market_state=amt_market_state,
            balance_ratio=float(amt_dto.get("balanceRatio") or 0.0),
            drive_entry_valid=bool(amt_dto.get("isSecondDrive") or False),
            drive_number=int(amt_dto.get("driveNumber") or 0),
            break_direction=break_dir,
            break_type=break_type,
            obi=obi,
            poc=float(amt_dto.get("poc") or 0.0),
            vah=float(amt_dto.get("valueAreaHigh") or 0.0),
            val=float(amt_dto.get("valueAreaLow") or 0.0),
            prior_poc=float(amt_dto.get("priorPoc") or 0.0),
            npoc_above=float(amt_dto.get("npocAbove") or 0.0),
            npoc_below=float(amt_dto.get("npocBelow") or 0.0),
            tick_size=tick_size,
            vwap_std=float(amt_dto.get("vwapDeviationSigmas") or 0.0),
            vwap_upper_2=float(amt_dto.get("vwapUpper2") or 0.0),
            vwap_lower_2=float(amt_dto.get("vwapLower2") or 0.0),
            cvd_slope=float(amt_dto.get("cvdSlope") or 0.0),
            absorption_side=amt_dto.get("absorptionSide") or "",
            equity=risk_state.equity,
            risk_per_trade_pct=risk_state.risk_per_trade_pct,
            leg_lvn=nearest_leg_lvn,
            bid=float(amt_dto.get("bid") or best_bid or 0.0),
            ask=float(amt_dto.get("ask") or best_ask or 0.0),
            time_str=str(bar.time if bar else ""),
            session_phase=session_phase,
            allow_trend=allow_trend,
            allow_reversion=allow_reversion,
            is_expiry=is_expiry,
            profile_shape=str(amt_dto.get("profileShape") or ""),
            # deltaNormalizedOption is candle order-flow delta, not an option
            # Greek. Only a chain-provided optionGreekDelta may reach option
            # premium stop translation; missing Greeks stay None.
            option_delta=(
                float(amt_dto["optionGreekDelta"])
                if amt_dto.get("optionGreekDelta") is not None
                else (0.50 if is_option_contract(symbol) else None)
            ),
            contested_bubble_zone=bool(amt_dto.get("contestedZone") or False),
            stacked_imbalance_direction=_si_dir,
            stacked_imbalance_magnitude=_si_mag,
            stacked_imbalance_price_low=_si_low,
            stacked_imbalance_price_high=_si_high,
            nearest_buy_print_below=_buy_wall_below,
            nearest_sell_print_above=_sell_wall_above,
            triple_a_phase=str(amt_dto.get("tripleAPhase") or ""),
            triple_a_signal=str(amt_dto.get("tripleASignal") or ""),
            absorption_cluster_high=float(amt_dto.get("absorptionClusterHigh") or 0.0),
            absorption_cluster_low=float(amt_dto.get("absorptionClusterLow") or 0.0),
            squeeze_detected=bool(squeeze_dir and trapped_lvl > 0),
            squeeze_direction=squeeze_dir,
            squeeze_trapped_level=trapped_lvl,
            pullback_confirmed=pullback,
            vars_result=amt_dto.get("vars"),
            recent_decisions=tuple(recent_decisions or ()),
        )
