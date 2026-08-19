"""DecisionContextBuilder — constructs the DecisionContext from engine state.

Extracted from QuantEngine to improve locality: context construction is a
pure function of inputs (state, bar, AMT DTO, risk state) with no side
effects. The builder receives dependencies via constructor injection.
"""

from __future__ import annotations

import logging

from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.session_gates import session_allow_entry

logger = logging.getLogger(__name__)

# Deterministic conviction used for gate 4's probability check when the engine
# decides from the auction state alone (above the 0.55 min_probability
# threshold). The decision-critical path is 100% deterministic by design — no
# model inference is involved, so _decide never waits on external calls.
_DETERMINISTIC_CONVICTION = 0.7


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
        interval_seconds: int = 60,
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

        # Direction input to the gates follows a strict hierarchy of intent:
        # 1. Initiative Breakouts (structural, overrides local mean-reversion)
        # 2. Triple-A Aggression Edge (canonical state machine edge)
        # 3. Fresh Absorption Cluster (microstructure edge)
        # 4. Deep Book OBI Imbalance (depth edge)
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
            market_state=amt_market_state,
            balance_ratio=float(amt_dto.get("balanceRatio") or 0.0),
            drive_entry_valid=bool(amt_dto.get("isSecondDrive") or False),
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
            leg_lvn=float(amt_dto.get("legLvn") or 0.0),
            bid=float(amt_dto.get("bid") or getattr(bar, "bid", 0.0) or 0.0),
            ask=float(amt_dto.get("ask") or getattr(bar, "ask", 0.0) or 0.0),
            time_str=str(bar.time if bar else ""),
        )
