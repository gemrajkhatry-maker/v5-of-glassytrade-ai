"""DecisionContextBuilder — constructs the DecisionContext from engine state.

Extracted from QuantEngine to improve locality: context construction is a
pure function of inputs (state, bar, AMT DTO, risk state) with no side
effects. The builder receives dependencies via constructor injection.
"""

from __future__ import annotations

import logging

from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.session_gates import ist_dt, session_allow_entry
from quant.amt.session.context import get_session_info
from quant.bars import DEFAULT_INTERVAL_SEC

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
        interval_seconds: int = DEFAULT_INTERVAL_SEC,
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
        warmup_bars = 15  # _WARMUP_BARS constant
        obi = float(amt_dto.get("obi") or 0.0)

        raw_ms = str(amt_dto.get("marketState") or "BALANCED").upper()
        break_dir = str(amt_dto.get("breakDirection") or "").upper()
        break_type = str(amt_dto.get("breakType") or "").upper()

        # Session & Expiry Context
        session_info = None
        bar_text = str(bar.time if bar else "").strip()
        is_epoch = (
            bar_text.replace(".", "", 1).lstrip("-").isdigit()
            and len(bar_text) >= 9
            and "T" not in bar_text
        )
        is_iso = "T" in bar_text or "+" in bar_text or ":" in bar_text
        if is_epoch or is_iso:
            try:
                session_info = get_session_info(bar.time, market=market)
            except Exception:
                pass

        session_phase = session_info.session if session_info else "PRIMARY"
        _si_dir, _si_mag, _si_low, _si_high = _latest_stacked_imbalance(amt_dto)
        _buy_wall_below, _sell_wall_above = _print_levels_from_dto(amt_dto, bar)
        allow_trend = session_info.allow_trend if session_info else True
        allow_reversion = session_info.allow_reversion if session_info else True

        bar_dt = ist_dt(bar.time) if (bar and bar.time and (is_epoch or is_iso)) else None
        is_expiry = (bar_dt.date() == contract_expiry) if (contract_expiry and bar_dt) else False

        # Direction input to the gates follows a strict hierarchy of intent:
        # 1. Initiative Breakouts (structural, overrides local mean-reversion)
        # 2. Triple-A Aggression Edge (canonical state machine edge)
        # 3. Fresh Absorption Cluster (microstructure edge)
        # 4. Deep Book OBI Imbalance (depth edge)
        # 5. Value Area Reversion (contextual mean-reversion)
        # 5. Value Area Reversion (contextual mean-reversion)
        close_px = float(bar.close if bar else 0.0)
        vah = float(amt_dto.get("valueAreaHigh") or 0.0)
        val = float(amt_dto.get("valueAreaLow") or 0.0)
        ofi = float(amt_dto.get("ofi") or 0.0)
        vwap_upper_1 = float(amt_dto.get("vwapUpper1") or float("inf"))
        vwap_lower_1 = float(amt_dto.get("vwapLower1") or float("-inf"))

        agent_direction = None
        if break_type == "INITIATIVE" and break_dir in ("UP", "DOWN"):
            agent_direction = "LONG" if break_dir == "UP" else "SHORT"
        elif amt_dto.get("absorptionSide") in ("SELL_ABSORBED", "BUY_ABSORBED"):
            # Simple assumption: fresh absorption maps directly to direction
            agent_direction = {"SELL_ABSORBED": "LONG", "BUY_ABSORBED": "SHORT"}.get(amt_dto.get("absorptionSide"))
        elif obi >= 0.20 and close_px > vwap_upper_1:
            agent_direction = "LONG"
        elif obi <= -0.20 and close_px < vwap_lower_1:
            agent_direction = "SHORT"
        elif raw_ms == "IMBALANCED":
            if (vah > 0 and close_px > vah) or ofi > 0.10 or (close_px > vwap_upper_1):
                agent_direction = "LONG"
            elif (val > 0 and close_px < val) or ofi < -0.10 or (close_px < vwap_lower_1):
                agent_direction = "SHORT"
        elif raw_ms == "BALANCED":
            if val > 0 and close_px <= val:
                agent_direction = "LONG"
            elif vah > 0 and close_px >= vah:
                agent_direction = "SHORT"

        # Market state + balance ratio from the AMT analyzer
        if raw_ms == "DEAD":
            amt_market_state = "DEAD"
        elif raw_ms == "IMBALANCED":
            amt_market_state = MarketState.IMBALANCED
        else:
            amt_market_state = MarketState.BALANCED

        # Derive nearest leg LVN from legLvns list or legLvn float
        leg_lvns_raw = amt_dto.get("legLvns")
        nearest_leg_lvn = 0.0
        if isinstance(leg_lvns_raw, (list, tuple)) and leg_lvns_raw:
            valid_lvns = [float(x) for x in leg_lvns_raw if float(x) > 0]
            if valid_lvns:
                nearest_leg_lvn = min(valid_lvns, key=lambda x: abs(x - close_px))
        elif amt_dto.get("legLvn"):
            nearest_leg_lvn = float(amt_dto.get("legLvn"))

        # Build SetupEvidence
        from quant.decision.setup_state import SetupEvidence
        setup_type = str(amt_dto.get("setupType") or "").upper()
        setup_dir = str(amt_dto.get("setupDirection") or agent_direction or "").upper()
        cvd_val = float(amt_dto.get("cvdSlope") or 0.0)
        cvd_agrees = bool(
            amt_dto.get("cvdAgrees")
            or (setup_dir == "LONG" and cvd_val >= -0.2)
            or (setup_dir == "SHORT" and cvd_val <= 0.2)
        )

        rejection_at_high = bool(amt_dto.get("rejectionAtHigh"))
        rejection_at_low = bool(amt_dto.get("rejectionAtLow"))
        acceptance_above = bool(amt_dto.get("acceptanceAbove"))
        acceptance_below = bool(amt_dto.get("acceptanceBelow"))
        is_second_drive = bool(amt_dto.get("isSecondDrive"))
        drive_number = int(amt_dto.get("driveNumber") or 0)

        setup_evidence = None
        if setup_type == "TRIPLE_A":
            setup_evidence = SetupEvidence(
                setup_type="TRIPLE_A",
                direction=setup_dir or ("LONG" if cvd_val >= 0 else "SHORT"),
                absorption=bool(amt_dto.get("absorption")),
                accumulation=bool(amt_dto.get("accumulation")),
                aggression=bool(amt_dto.get("aggression")),
                acceptance=bool(amt_dto.get("acceptance")),
                cvd_agrees=cvd_agrees,
            )
        elif is_second_drive or drive_number == 2 or setup_type == "SECOND_DRIVE":
            setup_evidence = SetupEvidence(
                setup_type="SECOND_DRIVE",
                direction=setup_dir or ("SHORT" if rejection_at_high else ("LONG" if rejection_at_low else "LONG")),
                drive_number=drive_number or 2,
                d1_rejected=True,
                rejection=rejection_at_high or rejection_at_low or bool(amt_dto.get("rejection")),
                cvd_agrees=cvd_agrees,
            )
        elif rejection_at_high or rejection_at_low or setup_type == "VA_FADE":
            rejection = rejection_at_high or rejection_at_low or bool(amt_dto.get("rejection"))
            acceptance = acceptance_above or acceptance_below or bool(amt_dto.get("acceptance", False))
            direction = "SHORT" if rejection_at_high else ("LONG" if rejection_at_low else (setup_dir or "LONG"))
            setup_evidence = SetupEvidence(
                setup_type="VA_FADE",
                direction=direction,
                rejection=rejection,
                acceptance=acceptance,
                cvd_agrees=cvd_agrees,
            )
        elif nearest_leg_lvn > 0 and (amt_dto.get("absorptionSide") in ("SELL_ABSORBED", "BUY_ABSORBED") or setup_type == "LVN_SNIPER"):
            direction = "LONG" if amt_dto.get("absorptionSide") == "SELL_ABSORBED" else ("SHORT" if amt_dto.get("absorptionSide") == "BUY_ABSORBED" else (setup_dir or "LONG"))
            setup_evidence = SetupEvidence(
                setup_type="LVN_SNIPER",
                direction=direction,
                level=nearest_leg_lvn,
                absorption=True,
                cvd_agrees=cvd_agrees,
            )
        elif setup_type and setup_type != "NONE":
            setup_evidence = SetupEvidence(
                setup_type=setup_type,  # type: ignore
                direction=setup_dir,
                cvd_agrees=cvd_agrees,
            )

        return DecisionContext(
            state=None,
            bar=bar,
            symbol=symbol,
            session_open=session_allow_entry(
                bar.time, market=market, contract_expiry=contract_expiry
            ),
            warmup_complete=(bar_index + warm_bars) >= warmup_bars,
            position_open=False,
            cooldown_remaining_sec=cooldown_remaining_sec,
            risk_halted=risk_state.halted,
            consecutive_losses=risk_state.consecutive_losses,
            agent_direction=agent_direction,
            agent_probability=_DETERMINISTIC_CONVICTION,
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
            bid=float(amt_dto.get("bid") or getattr(bar, "bid", 0.0) or 0.0),
            ask=float(amt_dto.get("ask") or getattr(bar, "ask", 0.0) or 0.0),
            time_str=str(bar.time if bar else ""),
            session_phase=session_phase,
            allow_trend=allow_trend,
            allow_reversion=allow_reversion,
            is_expiry=is_expiry,
            profile_shape=str(amt_dto.get("profileShape") or ""),
            option_delta=float(amt_dto.get("optionDelta") or 0.50),
            contested_bubble_zone=bool(amt_dto.get("contestedZone") or False),
            stacked_imbalance_direction=_si_dir,
            stacked_imbalance_magnitude=_si_mag,
            stacked_imbalance_price_low=_si_low,
            stacked_imbalance_price_high=_si_high,
            nearest_buy_print_below=_buy_wall_below,
            nearest_sell_print_above=_sell_wall_above,
        )
