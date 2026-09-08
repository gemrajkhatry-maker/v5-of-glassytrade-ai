"""Native TimesFM 3.0 Quantitative Decision Engine (Zero LLM / Zero External Microservice).

Uses Google TimesFM 3.0 PyTorch model loaded directly from local HuggingFace cache:
- Predicts 32-step future price trajectory
- Calculates uncertainty via quantile spread (p90 - p10)
- Applies Fabio Valentini Auction Market Theory (AMT) alignment
- Evaluates Triple-A, VA-Fade, and Breakout setups
- Emits structured decisions matching the exact AMT dataset schema in ~200ms
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from quant.decision.context import DecisionContext

logger = logging.getLogger(__name__)

# Global singleton model cache
_TIMESFM_MODEL: Any = None
_TIMESFM_LOCK = threading.Lock()


def get_timesfm_model(device: str = "cpu") -> Any:
    """Load and cache the TimesFM 3.0 PyTorch model singleton."""
    global _TIMESFM_MODEL
    if _TIMESFM_MODEL is not None:
        return _TIMESFM_MODEL

    with _TIMESFM_LOCK:
        if _TIMESFM_MODEL is None:
            try:
                import timesfm
                import torch

                # Check if MPS is supported and stable, else fallback to CPU
                target_device = device
                if target_device == "mps" and not torch.backends.mps.is_available():
                    target_device = "cpu"

                logger.info("TimesFMEngine: Loading TimesFM 3.0 on device=%s...", target_device)
                t0 = time.perf_counter()
                model = timesfm.TimesFM3Forecaster.from_pretrained(
                    "google/timesfm-3.0-pytorch",
                    device=target_device,
                )
                _TIMESFM_MODEL = model
                logger.info("TimesFMEngine: Model loaded successfully in %.2fs", time.perf_counter() - t0)
            except Exception as e:
                logger.error("TimesFMEngine: Failed to load TimesFM 3.0 model: %s", e)
                raise
    return _TIMESFM_MODEL


class TimesFMEngine:
    """In-process TimesFM 3.0 forecasting & AMT decision engine."""

    def __init__(self, target_horizon: int = 32, device: str = "cpu") -> None:
        self.target_horizon = target_horizon
        self.device = device
        self._price_buffers: Dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=self.target_horizon)
        )
        from quant.decision.timesfm_agents import (
            TimesFMForecast,
            TimesFMPositionAgent,
            TimesFMScanningAgent,
        )
        self.scanning_agent = TimesFMScanningAgent(target_horizon=self.target_horizon)
        self.position_agent = TimesFMPositionAgent(target_horizon=self.target_horizon)

    def add_context(self, ctx: DecisionContext) -> List[float]:
        """Record the latest price/close and return a 32-element array (padded if needed)."""
        symbol = str(ctx.symbol or "DEFAULT")
        price = float(ctx.bar.close if ctx.bar else (ctx.state.poc if ctx.state else 100.0))
        buf = self._price_buffers[symbol]
        buf.append(price)

        prices = list(buf)
        if len(prices) < self.target_horizon:
            # Replicate earliest price to fill 32 context elements
            pad_count = self.target_horizon - len(prices)
            padded = [prices[0]] * pad_count + prices
            return padded
        return prices

    def analyze(self, ctx: DecisionContext) -> Dict[str, Any]:
        """Run TimesFM 3.0 forecasting and route to the proper specialized agent."""
        t0 = time.perf_counter()
        symbol = str(ctx.symbol or "UNKNOWN")

        # Session & Risk Guards
        if ctx.risk_halted:
            return {
                "role": "POSITION_MANAGEMENT" if ctx.position_open else "SCANNING",
                "action": "FLAT",
                "direction": "FLAT",
                "setup": "NO_EDGE",
                "reason": "RISK_HALTED",
                "confidence": "Low",
                "confidenceScore": 0.0,
                "rationale": "Daily risk threshold reached; trading engine halted.",
                "forecastSteps": ["FLAT"] * self.target_horizon,
                "quantileSpread": 0.0,
                "meanForecast": float(ctx.bar.close if ctx.bar else 0.0),
                "gateResults": [
                    {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": True, "message": ""},
                    {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": False, "message": "Risk halted"},
                    {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": False, "message": "No trade"},
                    {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": False, "message": "Risk halted"},
                ],
                "activePosition": None,
                "dynamicTrailStop": None,
                "modelVersions": {"timesfm": "3.0", "engine": "native_direct"},
                "source": "TIMESFM_3.0_NATIVE",
                "latencyMs": 0.1,
                "modelLabel": "TimesFM-RiskHalted",
                "regime": ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED"),
                "timing": str(ctx.session_phase or "REGULAR"),
                "sizeFraction": 0.0,
                "latencyUs": 100,
            }

        session_phase = str(ctx.session_phase or "").upper()
        if "OPENING_NOISE" in session_phase:
            return {
                "role": "SCANNING",
                "action": "FLAT",
                "direction": "FLAT",
                "setup": "NO_EDGE",
                "reason": "OPENING_NOISE",
                "confidence": "Low",
                "confidenceScore": 0.1,
                "rationale": f"Opening noise / warmup phase active on {symbol} — no trade execution allowed.",
                "forecastSteps": ["FLAT"] * self.target_horizon,
                "quantileSpread": 0.0,
                "meanForecast": float(ctx.bar.close if ctx.bar else 0.0),
                "gateResults": [
                    {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": False, "message": "Opening noise"},
                    {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": True, "message": ""},
                    {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": False, "message": "Waiting for primary"},
                    {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": False, "message": "No setup"},
                ],
                "activePosition": None,
                "dynamicTrailStop": None,
                "modelVersions": {"timesfm": "3.0", "engine": "native_direct"},
                "source": "TIMESFM_3.0_NATIVE",
                "latencyMs": 0.1,
                "modelLabel": "TimesFM-OpeningNoise",
                "regime": ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED"),
                "timing": str(ctx.session_phase or "REGULAR"),
                "sizeFraction": 0.0,
                "latencyUs": 100,
            }

        # 1. Prepare price context
        context_prices = self.add_context(ctx)
        curr_price = context_prices[-1]

        # 2. Run TimesFM 3.0 inference
        model = get_timesfm_model(self.device)
        np_prices = np.array(context_prices, dtype=np.float32)
        res = model.predict(context=np_prices, horizon=self.target_horizon, return_quantiles=True)
        lat_ms = (time.perf_counter() - t0) * 1000.0

        # Quantile shape: (32, 9) where index 4 is p50, 0 is p10, 8 is p90
        quantiles = res.quantiles if hasattr(res, "quantiles") else None
        if quantiles is None or len(quantiles) == 0:
            p50_path = np.full(self.target_horizon, curr_price)
            p10_path = np.full(self.target_horizon, curr_price * 0.998)
            p90_path = np.full(self.target_horizon, curr_price * 1.002)
            q_spread = 0.0
        else:
            p50_path = quantiles[:, 4]
            p10_path = quantiles[:, 0]
            p90_path = quantiles[:, 8]
            q_spread = float(np.mean(p90_path - p10_path))

        mean_forecast = float(p50_path[-1])
        pct_change = (mean_forecast - curr_price) / max(curr_price, 1e-4)

        # Build step-by-step horizon trajectory
        vah = float(ctx.vah or (ctx.state.vah if ctx.state else curr_price))
        val = float(ctx.val or (ctx.state.val if ctx.state else curr_price))
        forecast_steps = []
        for p in p50_path:
            if p > vah:
                forecast_steps.append("LONG")
            elif p < val:
                forecast_steps.append("SHORT")
            else:
                forecast_steps.append("FLAT")

        from quant.decision.timesfm_agents import TimesFMForecast
        forecast = TimesFMForecast(
            horizon=self.target_horizon,
            p50_path=p50_path,
            p10_path=p10_path,
            p90_path=p90_path,
            q_spread=q_spread,
            mean_forecast=mean_forecast,
            pct_change=pct_change,
            forecast_steps=forecast_steps,
            curr_price=curr_price,
            lat_ms=lat_ms,
        )

        # 3. Dynamic Role Switch: Route to Proper Specialized Agent
        if ctx.position_open:
            return self.position_agent.evaluate(ctx, forecast)
        else:
            return self.scanning_agent.evaluate(ctx, forecast)
