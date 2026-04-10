"""Strategy Orchestrator — wires AMT analysis → state machine → gates → signal.

Per-symbol orchestration:
1. Receive candle
2. Update Volume Profile, VWAP, CVD
3. Run market state machine
4. If tradeable state → run gate pipeline
5. If gates pass → generate signal
6. If signal → send to execution
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from appv2.domain.models.ohlc import OHLC
from appv2.domain.models.signal import Signal
from appv2.domain.models.tick import Tick
from appv2.domain.services.incremental_volume_profile import IncrementalVolumeProfile
from appv2.domain.services.vwap_calculator import VWAPCalculator
from appv2.domain.services.cvd_tracker import CVDTracker
from appv2.domain.services.aggression_scorer import PersistentAggressionScorer
from appv2.domain.services.auction_state_machine import AuctionStateMachine
from appv2.domain.services.session_context import get_session_info, SessionInfo
from appv2.domain.services.market_state_engine import MarketStateResult
from appv2.domain.services.gate_pipeline import GateContext, run_gate_pipeline
from appv2.domain.services.signal_generator import build_signal
from appv2.domain.services.exit_engine import check_exit, ExitDecision
from appv2.config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class AMTObservation:
    """Output of AMT analysis for a candle."""
    symbol: str
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    vwap: float = 0.0
    vwap_sigma: float = 0.0
    market_state: str = "NO_TRADE"
    session_phase: str = ""
    aggression_score: float = 0.0
    cvd: float = 0.0
    cvd_slope: float = 0.0
    balance_ratio: float = 0.0
    profile_shape: str = ""


class StrategyOrchestrator:
    """Per-symbol strategy orchestration."""

    def __init__(self, symbol: str, underlying: str, tick_size: float = 0.05):
        self.symbol = symbol
        self.underlying = underlying
        self._tick_size = tick_size

        # Services
        self._vp = IncrementalVolumeProfile(tick_size=tick_size)
        self._vwap = VWAPCalculator()
        self._cvd = CVDTracker()
        self._agg_scorer = PersistentAggressionScorer()
        self._state_machine = AuctionStateMachine()
        self._candles: list[OHLC] = []

        # State
        self._last_observation: AMTObservation | None = None
        self._pending_signal: Signal | None = None
        self._session_info: SessionInfo | None = None

    def process_candle(self, candle: OHLC) -> AMTObservation:
        """Process a new candle and return AMT observation."""
        self._candles.append(candle)

        # Update services
        self._vp.update_candle(candle)
        vwap_result = self._vwap.update_candle(candle)
        cvd_state = self._cvd.update_candle(candle)

        # Compute profile
        poc, vah, val = self._vp.compute_value_area()
        poc = self._vp.get_poc_with_vwap_tiebreak(vwap_result.vwap)

        # Balance ratio (fraction of last 20 candles inside VA)
        balance_ratio = self._compute_balance_ratio(candle.close, vah, val)

        # Displacement & acceptance (simplified)
        has_displacement = self._check_displacement(candle)
        has_acceptance = self._check_acceptance(candle, vah, val)

        # Session context
        self._session_info = get_session_info(
            timestamp=candle.time,
            open_price=self._candles[0].open if self._candles else 0,
            prior_vah=0, prior_val=0,
            exchange=settings.EXCHANGE,
        )

        # State machine
        state = self._state_machine.evaluate(
            price=candle.close,
            poc=poc,
            vah=vah,
            val=val,
            tick_size=self._tick_size,
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
        )

        # Aggression score
        agg_result = self._agg_scorer.score(
            footprint_confirmed=candle.volume > 0,
            cvd_confirmed=abs(cvd_state.slope) > 0.5,
        )

        obs = AMTObservation(
            symbol=self.symbol,
            poc=poc,
            vah=vah,
            val=val,
            vwap=vwap_result.vwap,
            vwap_sigma=vwap_result.sigma,
            market_state=state.value,
            session_phase=self._session_info.phase.value if self._session_info else "",
            aggression_score=agg_result.score,
            cvd=cvd_state.cvd,
            cvd_slope=cvd_state.slope,
            balance_ratio=balance_ratio,
        )
        self._last_observation = obs
        return obs

    def check_gates(self, direction: str) -> tuple[bool, str, str]:
        """Run gate pipeline for a potential trade direction."""
        if self._last_observation is None:
            return False, "No observation", ""

        obs = self._last_observation
        risk = abs(obs.vwap - obs.val) if obs.val > 0 else 1.0
        reward = abs(obs.vah - obs.vwap) if obs.vah > 0 else 1.0
        rr = reward / risk if risk > 0 else 0.0

        ctx = GateContext(
            session_phase=obs.session_phase,
            market_state=obs.market_state,
            data_candles=len(self._candles),
            is_risk_halted=False,
            price=self._candles[-1].close if self._candles else 0,
            entry_zone=obs.val if direction == "LONG" else obs.vah,
            aggression_score=obs.aggression_score,
            opposing_level=obs.vah if direction == "LONG" else obs.val,
            r_r_ratio=rr,
            tick_age_seconds=0,
            tick_size=self._tick_size,
        )

        return run_gate_pipeline(ctx)

    def generate_signal(
        self,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> Signal | None:
        """Generate a trade signal."""
        if self._last_observation is None:
            return None

        obs = self._last_observation
        return build_signal(
            symbol=self.symbol,
            underlying=self.underlying,
            direction=direction,
            setup_type="VA_BOUNCE",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=min(1.0, obs.aggression_score / 5.0),
            market_state=obs.market_state,
            session_phase=obs.session_phase,
            poc=obs.poc,
            vah=obs.vah,
            val=obs.val,
            vwap=obs.vwap,
            aggression_score=obs.aggression_score,
            tick_size=self._tick_size,
        )

    def check_exit(
        self,
        current_price: float,
        stop_loss: float,
        take_profit: float,
        is_long: bool = True,
        force_exit: bool = False,
    ) -> ExitDecision:
        """Check if open position should be exited."""
        if self._session_info and self._session_info.forces_exit:
            force_exit = True

        return check_exit(
            current_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            is_long=is_long,
            force_exit=force_exit,
        )

    def reset(self) -> None:
        """Reset all services (session boundary)."""
        self._vp.reset()
        self._vwap.reset()
        self._cvd.reset()
        self._agg_scorer.reset()
        self._state_machine.reset()
        self._candles.clear()
        self._last_observation = None
        self._pending_signal = None

    def _check_displacement(self, candle: OHLC) -> bool:
        if len(self._candles) < 14:
            return False
        atr = sum(c.range for c in self._candles[-14:]) / 14
        return candle.range > atr * 1.5

    def _check_acceptance(self, candle: OHLC, vah: float, val: float) -> bool:
        """Acceptance = 2+ candles beyond VA boundary."""
        beyond = 0
        for c in self._candles[-3:]:
            if c.close > vah or c.close < val:
                beyond += 1
        return beyond >= 2

    def _compute_balance_ratio(self, price: float, vah: float, val: float) -> float:
        if not self._candles or vah <= val:
            return 0.0
        count = sum(1 for c in self._candles[-20:] if val <= c.close <= vah)
        return count / min(len(self._candles[-20:]), 20)
