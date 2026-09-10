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
from quant.session_gates import session_allow_entry

logger = logging.getLogger(__name__)

# Global singleton model cache
_TIMESFM_MODEL: Any = None
_TIMESFM_LOCK = threading.Lock()
_TIMESFM_MODEL_LOAD_ERROR: Optional[str] = None


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
                global _TIMESFM_MODEL_LOAD_ERROR
                _TIMESFM_MODEL_LOAD_ERROR = str(e)
                raise
    return _TIMESFM_MODEL


def reset_timesfm_model_cache() -> None:
    """Reset the global model cache (for testing)."""
    global _TIMESFM_MODEL, _TIMESFM_MODEL_LOAD_ERROR
    with _TIMESFM_LOCK:
        _TIMESFM_MODEL = None
        _TIMESFM_MODEL_LOAD_ERROR = None


class TimesFMEngine:
    """In-process TimesFM 3.0 forecasting & AMT decision engine."""

    # We keep up to 512 bars of context per symbol. TimesFM uses the last
    # `target_horizon` (32) bars for inference; having 512 buffered means
    # the model always has a warm, realistic window from day-1 once
    # seed_history() is called during startup.
    CONTEXT_WINDOW = 512

    def __init__(self, target_horizon: int = 32, device: str = "cpu") -> None:
        self.target_horizon = target_horizon
        self.device = device
        self._price_buffers: Dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=self.CONTEXT_WINDOW)
        )
        # Track how many live ticks have been added per symbol (after seeding)
        self._live_bar_counts: Dict[str, int] = collections.defaultdict(int)
        # Last DecisionContext.bar_index recorded per symbol. The advisor's
        # native engine and the E2E strategy share ONE TimesFMEngine, so both
        # call add_context() for the same bar. Without this guard the model
        # sees every price twice — a duplicated, distorted input series.
        self._last_context_bar: Dict[str, int] = {}
        from quant.decision.timesfm_agents import (
            TimesFMForecast,
            TimesFMPositionAgent,
            TimesFMScanningAgent,
        )
        self.scanning_agent = TimesFMScanningAgent(target_horizon=self.target_horizon)
        self.position_agent = TimesFMPositionAgent(target_horizon=self.target_horizon)
        self._model_loaded = False

    def warmup(self) -> bool:
        """Load the model on startup. Returns True if model loaded successfully.

        This method is idempotent — calling it multiple times is safe.
        If the model fails to load, the engine falls back to rule-based mode.
        """
        if self._model_loaded:
            return True
        try:
            get_timesfm_model(self.device)
            self._model_loaded = True
            logger.info("TimesFMEngine: warmup complete — model ready")
            return True
        except Exception as e:
            logger.warning("TimesFMEngine: warmup failed — falling back to rule-based mode: %s", e)
            self._model_loaded = False
            return False

    def is_healthy(self) -> bool:
        """Return True if model is loaded and ready for inference."""
        return self._model_loaded

    @staticmethod
    def health_check() -> Dict[str, Any]:
        """Static health check that tries to load model and returns status dict.

        Returns a dict with:
        - status: "healthy" | "degraded" | "unavailable"
        - model_loaded: bool
        - error: error message if model failed to load
        """
        try:
            get_timesfm_model()
            return {
                "status": "healthy",
                "model_loaded": True,
                "error": None,
            }
        except Exception as e:
            return {
                "status": "unavailable",
                "model_loaded": False,
                "error": _TIMESFM_MODEL_LOAD_ERROR or str(e),
            }

    def seed_history(self, symbol: str, prices: List[float]) -> int:
        """Pre-populate the price buffer with historical closes.

        Called once per symbol at startup (AMT engine seed phase) so the model
        has a full context window from bar-1 rather than starting from a single
        repeated value.

        Args:
            symbol: Instrument root/symbol key.
            prices: Ordered list of historical close prices (oldest → newest).

        Returns:
            Number of prices loaded into the buffer.
        """
        buf = self._price_buffers[symbol]
        valid = [float(p) for p in prices if p and p > 0]
        for p in valid:
            buf.append(p)
        seeded = len(valid)
        logger.info(
            "TimesFMEngine: seeded %d historical bars for %s (buffer=%d)",
            seeded, symbol, len(buf),
        )
        return seeded

    def add_context(self, ctx: DecisionContext) -> Tuple[List[float], int]:
        """Record the latest live price/close.

        Returns:
            (prices_for_inference, context_bars_used)
            prices_for_inference — exactly `target_horizon` values for the model
            context_bars_used   — raw buffer depth (including historical seed)

        Idempotent per bar: when the advisor and the strategy share one engine
        (TIMESFM_END_TO_END + native advisor) both call this for the same
        DecisionContext, and the price must be recorded exactly once.
        """
        symbol = str(ctx.symbol or "DEFAULT")
        price = float(ctx.bar.close if ctx.bar else (ctx.state.poc if ctx.state else 100.0))
        bar_index = int(getattr(ctx, "bar_index", -1) or -1)
        buf = self._price_buffers[symbol]

        # A stamped bar index already recorded for this symbol means another
        # consumer (advisor vs strategy) beat us to it this bar. bar_index < 0
        # means the caller did not stamp one (unit tests, ad-hoc probes) —
        # append unchanged so those callers keep their existing semantics.
        if bar_index >= 0 and self._last_context_bar.get(symbol) == bar_index:
            return self._context_window(buf)

        buf.append(price)
        self._live_bar_counts[symbol] += 1
        if bar_index >= 0:
            self._last_context_bar[symbol] = bar_index

        return self._context_window(buf)

    def _context_window(self, buf) -> Tuple[List[float], int]:
        """Project the rolling buffer to (inference window, raw depth)."""
        raw_prices = list(buf)
        context_bars_used = len(raw_prices)

        # Use the most recent `target_horizon` bars for inference
        inference_prices = raw_prices[-self.target_horizon:]
        if len(inference_prices) < self.target_horizon:
            pad_count = self.target_horizon - len(inference_prices)
            inference_prices = [inference_prices[0]] * pad_count + inference_prices
        return inference_prices, context_bars_used

    def analyze(self, ctx: DecisionContext) -> Dict[str, Any]:
        """Run TimesFM 3.0 forecasting and route to the proper specialized agent."""
        t0 = time.perf_counter()
        symbol = str(ctx.symbol or "UNKNOWN")

        # 1. Always record the incoming price context first so the rolling buffer
        # and live event counts stay continuous even during opening/cooldown phases.
        context_prices, context_bars_used = self.add_context(ctx)
        curr_price = context_prices[-1]
        events_processed = self._live_bar_counts.get(symbol, 0)

        # Session Gate: check if new entries are allowed at this time/market
        is_blocked_by_time = bool(ctx.time_str and not session_allow_entry(ctx.time_str, ctx.market))
        if (not ctx.session_open) or is_blocked_by_time:
            time_msg = f" at {ctx.time_str}" if ctx.time_str else ""
            return {
                "role": "SCANNING",
                "action": "FLAT",
                "direction": "FLAT",
                "setup": "NO_EDGE",
                "reason": "SESSION_GATE_BLOCKED",
                "confidence": "Low",
                "confidenceScore": 0.0,
                "rationale": f"Session gate blocked entry for {symbol}{time_msg} (market={ctx.market}).",
                "forecastSteps": ["FLAT"] * self.target_horizon,
                "quantileSpread": 0.0,
                "meanForecast": float(ctx.bar.close if ctx.bar else 0.0),
                "gateResults": [
                    {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": False, "message": "Session gate blocked"},
                    {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": True, "message": ""},
                    {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": False, "message": "No trade"},
                    {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": False, "message": "No trade"},
                ],
                "activePosition": None,
                "dynamicTrailStop": None,
                "modelVersions": {"timesfm": "3.0", "engine": "native_direct"},
                "source": "TIMESFM_3.0_NATIVE",
                "latencyMs": 0.1,
                "modelLabel": "TimesFM-SessionGateBlocked",
                "regime": ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED"),
                "timing": str(ctx.session_phase or "REGULAR"),
                "sizeFraction": 0.0,
                "latencyUs": 100,
                "contextBarsUsed": context_bars_used,
                "eventsProcessed": events_processed,
                "inferenceWindow": self.target_horizon,
            }

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
                "contextBarsUsed": context_bars_used,
                "eventsProcessed": events_processed,
                "inferenceWindow": self.target_horizon,
            }

        session_phase = str(ctx.session_phase or "").upper()
        is_opening = any(p in session_phase for p in ("OPENING", "PRE_OPEN", "PRE_MARKET"))
        if is_opening:
            return {
                "role": "SCANNING",
                "action": "FLAT",
                "direction": "FLAT",
                "setup": "NO_EDGE",
                "reason": "OPENING_NOISE",
                "confidence": "Low",
                "confidenceScore": 0.1,
                "rationale": f"Opening noise / warmup phase active on {symbol} ({session_phase}) — no trade execution allowed.",
                "forecastSteps": ["FLAT"] * self.target_horizon,
                "quantileSpread": 0.0,
                "meanForecast": float(ctx.bar.close if ctx.bar else 0.0),
                "gateResults": [
                    {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": False, "message": f"Opening noise ({session_phase})"},
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
                "contextBarsUsed": context_bars_used,
                "eventsProcessed": events_processed,
                "inferenceWindow": self.target_horizon,
            }

        # 2. Run TimesFM 3.0 inference (with graceful fallback)
        try:
            model = get_timesfm_model(self.device)
            self._model_loaded = True
        except Exception as e:
            # Graceful fallback: log error and return rule-based decision
            logger.warning("TimesFMEngine: model not available (%s) — returning rule-based fallback", e)
            return self._rule_based_fallback(ctx, curr_price, str(e), context_bars_used, events_processed)

        try:
            np_prices = np.array(context_prices, dtype=np.float32)
            res = model.predict(context=np_prices, horizon=self.target_horizon, return_quantiles=True)
            lat_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as e:
            # Inference failed — graceful fallback to rule-based
            logger.warning("TimesFMEngine: inference failed (%s) — returning rule-based fallback", e)
            return self._rule_based_fallback(ctx, curr_price, str(e), context_bars_used, events_processed)

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
        # The advisor is UI-only. In E2E mode the TimesFM model is the entry
        # authority, so the advisor's gate display shows the scanner's own
        # model gates — the same source that drives the real decision.
        if ctx.position_open:
            result = self.position_agent.evaluate(ctx, forecast)
        else:
            result = self.scanning_agent.evaluate(ctx, forecast)

        # 4. Annotate with context transparency fields
        result["contextBarsUsed"] = context_bars_used
        result["eventsProcessed"] = events_processed
        result["inferenceWindow"] = self.target_horizon
        return result

    def _rule_based_fallback(
        self,
        ctx: DecisionContext,
        curr_price: float,
        error_msg: str,
        context_bars_used: int = 0,
        events_processed: int = 0,
    ) -> Dict[str, Any]:
        """Return a valid decision payload in rule-based fallback mode.

        This is used when the TimesFM model fails to load or inference fails.
        The engine degrades gracefully — never crashes, always returns a valid payload.
        """
        logger.info("TimesFMEngine: using rule-based fallback for %s (error: %s)", ctx.symbol, error_msg)

        # Simple rule-based direction from AMT context. Absorption follows
        # canonical AMT semantics: SELL_ABSORBED = sellers absorbed = bullish
        # (LONG), BUY_ABSORBED = buyers absorbed = bearish (SHORT). Substring
        # match tolerates both the full `_ABSORBED` DTO form and the legacy
        # bare "BUY"/"SELL" form; the bare-only comparison this replaces was
        # dead against the live DTO (which always sends `_ABSORBED`).
        direction = "FLAT"
        absorption = str(ctx.absorption_side or "").upper()
        if ctx.cvd_slope > 0 and "SELL" in absorption:
            direction = "LONG"
        elif ctx.cvd_slope < 0 and "BUY" in absorption:
            direction = "SHORT"

        forecast_steps = [direction] * self.target_horizon
        if direction == "FLAT":
            forecast_steps = ["FLAT"] * self.target_horizon

        active_position = None
        if ctx.position_open:
            side = str(ctx.position_side or "LONG").upper()
            entry_price = float(ctx.position_entry_price or curr_price)
            stop_loss = float(ctx.position_sl or 0.0)
            take_profit = float(ctx.position_tp or 0.0)
            active_position = {
                "side": side,
                "entryPrice": round(entry_price, 2),
                "currentPrice": round(curr_price, 2),
                "pnl": round(float(ctx.position_unrealized_pnl or 0.0), 2),
                "stopLoss": round(stop_loss, 2) if stop_loss > 0 else None,
                "takeProfit": round(take_profit, 2) if take_profit > 0 else None,
                "barsHeld": int(ctx.position_bars_held or 0),
                "isRiskFree": (stop_loss >= entry_price) if side == "LONG" else (stop_loss > 0 and stop_loss <= entry_price),
                "rrAchieved": round(
                    ((curr_price - entry_price) if side == "LONG" else (entry_price - curr_price))
                    / max(abs(entry_price - stop_loss), 1e-4),
                    2,
                ),
            }

        return {
            "role": "POSITION_MANAGEMENT" if ctx.position_open else "SCANNING",
            "action": "HOLD" if ctx.position_open else (f"ENTER_{direction}" if direction != "FLAT" else "FLAT"),
            "direction": direction,
            "setup": "RULE_BASED_FALLBACK",
            "reason": "TIMESFM_FALLBACK",
            "confidence": "Low",
            "confidenceScore": 0.2,
            "rationale": f"TimesFM unavailable ({error_msg[:100]}) — using rule-based AMT signals.",
            "forecastSteps": forecast_steps,
            "quantileSpread": 0.0,
            "meanForecast": curr_price,
            "gateResults": [
                {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": True, "message": ""},
                {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": True, "message": ""},
                {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": False, "message": "Fallback mode"},
                {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": False, "message": "Fallback mode"},
            ],
            "activePosition": active_position,
            "dynamicTrailStop": None,
            "modelVersions": {"timesfm": "unavailable", "engine": "rule_based_fallback"},
            "source": "TIMESFM_FALLBACK",
            "latencyMs": 0.1,
            "modelLabel": "TimesFM-Fallback",
            "regime": ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED"),
            "timing": str(ctx.session_phase or "REGULAR"),
            "sizeFraction": 0.0,
            "latencyUs": 100,
            "contextBarsUsed": context_bars_used,
            "eventsProcessed": events_processed,
            "inferenceWindow": self.target_horizon,
        }
