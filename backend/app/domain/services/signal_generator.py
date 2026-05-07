"""Signal Generator Service - generates trading signals based on AMT analysis.

Generates Fabio-compliant signals with structural stop placement based on:
- Volume Profile levels (POC, VAH, VAL, LVNs, HVNs)
- Initial Balance extremes
- Setup type (AAA, MOMENTUM, MEAN_REVERSION, FAILED_AUCTION)
- ATR-based risk capping
"""

import logging
from datetime import datetime

from app.domain.trading.models.entities import Signal
from app.domain.trading.models.enums import SetupType, SignalType, Source
from app.domain.fabio_ai.services.structural_stop_engine import compute_structural_stop

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Generates trading signals from AMT analysis results."""

    def __init__(self):
        self._last_signal: Signal | None = None

    def generate(
        self,
        symbol: str,
        market_state: str,
        poc: float,
        vah: float,
        val: float,
        aggression: float,
        ofi: float,
        cvd_slope: float,
        lvns: tuple[float, ...] = (),
        hvns: tuple[float, ...] = (),
        ib_high: float = 0.0,
        ib_low: float = 0.0,
        atr: float = 0.0,
        tick_size: float = 0.05,
        probe_extreme: float = 0.0,
    ) -> Signal:
        """Generate a trading signal with structural stop placement.
        
        Fabio's methodology: stops are placed at structural invalidation levels,
        NOT fixed percentages. The engine computes optimal SL based on setup type.
        """
        # Determine signal type and setup based on AMT metrics
        confidence = 0.0
        reason = "No clear signal"
        signal_type: SignalType = SignalType.BUY
        setup = SetupType.MEAN_REVERSION
        price = poc

        # Simple example logic (should be expanded with full AMT rules)
        if aggression > 0.5 and cvd_slope > 0:
            signal_type = SignalType.BUY
            setup = SetupType.MEAN_REVERSION
            confidence = min(aggression, 0.9)
            reason = "High aggression with positive CVD"
        elif aggression < -0.5 and cvd_slope < 0:
            signal_type = SignalType.SELL
            setup = SetupType.RESPONSIVE_FADE
            confidence = min(abs(aggression), 0.9)
            reason = "High aggression with negative CVD"

        # Compute structural stop using Fabio's methodology
        direction = "LONG" if signal_type == SignalType.BUY else "SHORT"
        setup_type_str = setup.value if hasattr(setup, 'value') else str(setup)
        
        structural_stop = compute_structural_stop(
            entry_price=price,
            direction=direction,
            setup_type=setup_type_str,
            lvns=lvns,
            hvns=hvns,
            vah=vah,
            val=val,
            ib_high=ib_high,
            ib_low=ib_low,
            atr=atr,
            tick_size=tick_size,
            probe_extreme=probe_extreme,
        )
        
        sl = structural_stop.price
        
        # Take profit: use 2x risk distance (minimum 1.5:1 R:R)
        risk_distance = abs(price - sl)
        tp = price + (risk_distance * 2) if signal_type == SignalType.BUY else price - (risk_distance * 2)
        
        logger.info(
            "Signal generated: %s @ %.2f, SL=%.2f (%s), TP=%.2f, R:R=%.1f",
            direction, price, sl, structural_stop.reason, tp, 
            abs(tp - price) / max(risk_distance, 0.01)
        )
        
        signal = Signal.create(
            type=signal_type,
            price=price,
            reason=reason,
            stop_loss=sl,
            take_profit=tp,
            timestamp=datetime.utcnow().isoformat(),
            setup=setup,
            source=Source.AMT,
            metadata={
                "symbol": symbol,
                "market_state": market_state,
                "aggression": aggression,
                "confidence": confidence,
                "ofi": ofi,
                "cvd_slope": cvd_slope,
                "poc": poc,
                "vah": vah,
                "val": val,
                "structural_stop_reason": structural_stop.reason,
                "structural_stop_thesis": structural_stop.thesis,
                "atr_multiple": structural_stop.atr_multiple,
            },
        )
        self._last_signal = signal
        return signal