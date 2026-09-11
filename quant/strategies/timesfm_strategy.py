"""TimesFM 3.0 autonomous trading strategy.

This is the single model spine for the `TIMESFM_END_TO_END` mode. It owns
the forecast factory and delegates entry selection to the scanning agent, so
the decision path, the AMT/advisor view path, and the coordinator scanner
all read from the same TimesFM machinery instead of running two parallel
forecast factories.

Sizing and exits still flow through the runtime's existing authorities
(SessionRisk, ExitEngine with optional TimesFMRiskAuthority) so the model
strategy stays a decision layer, not a second risk or sizing authority.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import numpy as np

from quant.decision.context import DecisionContext
from quant.decision.decision_service import QuantDecision
from quant.decision.result import GateResult
from quant.decision.signal_builder import Signal
from quant.decision.timesfm_agents import (
    TimesFMForecast,
    TimesFMPositionAgent,
    TimesFMScanningAgent,
)
from quant.decision.timesfm_engine import TimesFMEngine, _TIMESFM_INFER_LOCK
from quant.decision.timesfm_forecast_factory import build_forecast
from quant.execution.exits import ExitEngine
from quant.modeling.contracts import ForecastStatus
from quant.modeling.forecast_provider import ForecastProvider


logger = logging.getLogger(__name__)


class TimesFMTradingStrategy:
    """Autonomous end-to-end trading strategy powered by Google TimesFM 3.0."""

    def __init__(
        self,
        target_horizon: int = 32,
        device: str = "cpu",
        engine: Optional[TimesFMEngine] = None,
        exit_engine: Optional[ExitEngine] = None,
        forecast_provider: Optional[ForecastProvider] = None,
    ) -> None:
        self.target_horizon = target_horizon
        self.device = device
        self._engine = engine or TimesFMEngine(target_horizon=target_horizon, device=device)
        self._exit_engine = exit_engine
        self._forecast_provider = forecast_provider
        self.scanning_agent = TimesFMScanningAgent(target_horizon=target_horizon)

        # Latest forecast cache, per symbol, so downstream AMT/advisor code can
        # read the same forecast the decision path just computed.
        self._latest_forecasts: dict[str, TimesFMForecast] = {}

    def on_bar(self, bar, auction, amt_dto: dict) -> None:
        """No per-bar state to update — the strategy is stateless."""
        pass

    @property
    def exit_engine(self) -> ExitEngine:
        """Return the exit engine that the runtime wires for this strategy.

        A TimesFMTradingStrategy created by the runtime is given the runtime's
        ExitEngine via ``exit_engine=`` so the strategy never builds its own
        copy. When constructed in isolation (tests, demo scripts) this path
        still answers with a default exit engine so the class is directly
        testable without the coordinator.
        """
        if getattr(self, "_exit_engine", None) is None:
            self._exit_engine = ExitEngine(time_stop_bars=self.target_horizon)
        return self._exit_engine

    def get_latest_forecast(self, symbol: str) -> Optional[TimesFMForecast]:
        """Return the most recently computed forecast for a symbol."""
        return self._latest_forecasts.get(symbol)

    def should_enter(
        self,
        ctx: DecisionContext,
        *,
        allow_positioned: bool = False,
        forecast: Optional[TimesFMForecast] = None,
    ) -> QuantDecision:
        """Evaluate market auction state using TimesFM 3.0 forecast and scanning agent.

        Returns an approved QuantDecision if TimesFM identifies a high-conviction
        directional auction setup with favorable velocity and risk-reward.
        """
        if ctx.bar is None:
            return QuantDecision(
                approved=False,
                signal=None,
                reason="NO_EDGE",
                phase="",
                gate_results=(),
                block_reasons=("No bar data",),
                model_label="",
            )

        # 1. Hard risk halt safety backstop (never bypassed for new entries)
        if ctx.risk_halted and not allow_positioned:
            return QuantDecision(
                approved=False,
                signal=None,
                reason="HALTED",
                phase="",
                gate_results=(),
                block_reasons=("Risk: session halted",),
                model_label="TimesFM-RiskHalted",
            )

        # 2. Compute or retrieve TimesFM forecast
        if forecast is None:
            forecast = self._compute_forecast(ctx)
        if forecast is None:
            return QuantDecision(
                approved=False,
                signal=None,
                reason="MODEL_UNAVAILABLE",
                phase="",
                gate_results=(),
                block_reasons=("TimesFM forecast unavailable",),
                model_label="TimesFM-Unavailable",
            )

        self._latest_forecasts[str(ctx.symbol)] = forecast
        # Freshness stamp: exits/sizing must never consume a forecast older
        # than 1 bar (TimesFMForecast is mutable — direct assignment).
        forecast.asof_bar = int(getattr(ctx, "bar_index", -1))

        # 3. Evaluate via TimesFMScanningAgent. In E2E mode the model is the
        # central intelligence: its directional decision is followed through.
        # The scanner's own gates (session, cooldown, direction, momentum) are
        # the model layer's filters; the runtime still enforces cooldown and
        # risk-halt before calling here. Canonical AMT gates do NOT override
        # the model's decision.
        scan_res = self.scanning_agent.evaluate(ctx, forecast)
        action = scan_res.get("action", "FLAT")
        direction = scan_res.get("direction", "FLAT")
        setup = scan_res.get("setup", "NO_EDGE")
        gate_dicts = scan_res.get("gateResults", [])

        # Convert gate dicts to GateResult objects
        gate_results = tuple(
            GateResult(
                gate=g.get("gate_no", i + 1),
                passed=bool(g.get("passed", False)),
                reason=str(g.get("message", "")),
            )
            for i, g in enumerate(gate_dicts)
        )

        all_gates_passed = all(g.passed for g in gate_results) if gate_results else False
        is_entry = action in ("ENTER_LONG", "ENTER_SHORT") and direction in ("LONG", "SHORT")

        if is_entry and (all_gates_passed or allow_positioned):
            curr_price = float(ctx.bar.close)
            # Single sizing authority is SessionRisk.position_size() at runtime.
            # The scanner emits ranking only (no sizing payload); the
            # strategy qualifies the entry with model-derived SL/TP here.
            var_stop, target, payoff = self._size_entry(curr_price, direction, forecast, setup, ctx)

            var_stop = round(var_stop, 2)
            target = round(target, 2)

            timestamp = str(ctx.bar.time if ctx.bar else "")
            model_label = f"TimesFM-{setup}"

            sig = Signal(
                type=direction,
                reason=setup,
                entry=curr_price,
                sl=var_stop,
                tp=target,
                rr=round(payoff, 2),
                model_label=model_label,
                symbol=str(ctx.symbol or ""),
                timestamp=timestamp,
            )

            logger.info(
                "TIMESFM APPROVAL %s %s @ %.2f | VaR SL: %.2f | TP: %.2f | RR: %.2f | Model: %s",
                ctx.symbol, direction, curr_price, var_stop, target, payoff, model_label,
            )

            return QuantDecision(
                approved=True,
                signal=sig,
                reason=setup,
                phase=str(ctx.session_phase or ""),
                gate_results=gate_results,
                block_reasons=(),
                model_label=model_label,
            )

        # Not approved: extract reasons
        failed_reasons = tuple(
            f"{g.name}: {g.reason}" for g in gate_results if not g.passed
        ) or (scan_res.get("rationale") or "No directional edge",)

        return QuantDecision(
            approved=False,
            signal=None,
            reason=setup if setup != "NO_EDGE" else "NO_EDGE",
            phase=str(ctx.session_phase or ""),
            gate_results=gate_results,
            block_reasons=failed_reasons,
            model_label=f"TimesFM-{setup}",
        )

    def _size_entry(
        self,
        curr_price: float,
        direction: str,
        forecast: TimesFMForecast,
        setup: str,
        ctx: DecisionContext,
    ) -> tuple[float, float, float]:
        """Compute the model-derived VaR stop, target, and resulting payoff ratio.

        This is the single, lightweight size math used to qualify an entry
        signal. It is intentionally kept here as entry qualification only; the
        runtime still owns final position sizing through SessionRisk so the
        strategy never becomes a second sizing authority.
        """
        from quant.decision.timesfm_sizing import TimesFMPositionSizer

        poc = float(getattr(ctx, "poc", 0.0) or 0.0)
        vah = float(getattr(ctx, "vah", 0.0) or 0.0)
        val = float(getattr(ctx, "val", 0.0) or 0.0)

        structural_target = None
        if direction == "LONG":
            if setup == "VA_FADE" and poc > curr_price:
                structural_target = poc
            elif setup in ("BREAKOUT", "MODEL_MOMENTUM"):
                structural_target = (
                    float(getattr(ctx, "npoc_above", 0.0) or 0.0)
                    or float(getattr(ctx, "prior_poc", 0.0) or 0.0)
                    or vah
                    or None
                )
        elif direction == "SHORT":
            if setup == "VA_FADE" and 0 < poc < curr_price:
                structural_target = poc
            elif setup in ("BREAKOUT", "MODEL_MOMENTUM"):
                structural_target = (
                    float(getattr(ctx, "npoc_below", 0.0) or 0.0)
                    or float(getattr(ctx, "prior_poc", 0.0) or 0.0)
                    or val
                    or None
                )

        sizer = TimesFMPositionSizer()
        var_stop = float(sizer.calculate_var_stop(curr_price, direction, forecast))
        target, _ = sizer.calculate_expected_target(
            curr_price,
            direction,
            forecast,
            structural_target=structural_target,
            var_stop=var_stop,
        )
        loss_dist = max(abs(curr_price - var_stop), 1e-4)
        payoff = abs(target - curr_price) / loss_dist
        return var_stop, target, payoff

    def _compute_forecast(self, ctx: DecisionContext) -> Optional[TimesFMForecast]:
        """Generate a forecast through the shared provider when configured."""
        bar_index = int(getattr(ctx, "bar_index", -1) or -1)

        # D-11: the advisor engine already inferred this bar on the shared
        # engine. Reuse that forecast instead of paying a second inference and
        # risking a divergent payload. An explicit forecast_provider still wins
        # (its own factory is authoritative), and a forecast from a different
        # bar_index is never served — Task 4 established strict monotonic bar
        # semantics, so a cached bar must match exactly.
        if self._forecast_provider is None:
            cached = self._engine.last_forecast_for(
                str(ctx.symbol or "UNKNOWN"),
                identity=self._engine._observation_identity(ctx),
            )
            if cached is not None:
                cached_bar = int(getattr(cached, "asof_bar", -1))
                if cached_bar >= 0 and cached_bar == bar_index:
                    return cached

        if self._forecast_provider is not None:
            context_prices, _ = self._engine.add_context(ctx)
            snapshot = self._forecast_provider.forecast(
                str(ctx.symbol or "UNKNOWN"),
                context_prices,
                decision_sequence=len(self._latest_forecasts) + 1,
            )
            if snapshot.status is not ForecastStatus.AVAILABLE:
                return None
            return TimesFMForecast(
                horizon=len(snapshot.p50_path),
                p50_path=np.asarray(snapshot.p50_path, dtype=np.float32),
                p10_path=np.asarray(snapshot.p10_path, dtype=np.float32),
                p90_path=np.asarray(snapshot.p90_path, dtype=np.float32),
                q_spread=float(snapshot.dispersion or 0.0),
                mean_forecast=float(snapshot.p50_path[-1]),
                pct_change=float(snapshot.expected_return or 0.0),
                forecast_steps=["LONG" if p > snapshot.p50_path[0] else ("SHORT" if p < snapshot.p50_path[0] else "FLAT") for p in snapshot.p50_path],
                curr_price=float(context_prices[-1]),
                lat_ms=float(snapshot.latency_ms),
                asof_bar=int(getattr(ctx, "bar_index", -1)),
            )
        try:
            t0 = time.perf_counter()
            context_prices, _ = self._engine.add_context(ctx)
            curr_price = context_prices[-1]

            self._engine.warmup()
            from quant.decision.timesfm_engine import get_timesfm_model

            model_inst = get_timesfm_model(self.device)
            np_prices = np.array(context_prices, dtype=np.float32)
            with _TIMESFM_INFER_LOCK:
                res = model_inst.predict(context=np_prices, horizon=self.target_horizon, return_quantiles=True)
            lat_ms = (time.perf_counter() - t0) * 1000.0

            quantiles = getattr(res, "quantiles", None)
            fc = build_forecast(quantiles, curr_price, self.target_horizon, lat_ms)
            fc.asof_bar = int(getattr(ctx, "bar_index", -1))
            # D-11 reverse direction: on the entry path runtime._decide calls
            # should_enter (this method) BEFORE the advisor's analyze, so the
            # strategy owns the bar's inference here. Record it on the shared
            # engine so the later analyze reuses it instead of re-inferring.
            self._engine.record_forecast(
                str(ctx.symbol or "UNKNOWN"),
                int(getattr(ctx, "bar_index", -1) or -1),
                fc,
                identity=self._engine._observation_identity(ctx),
            )
            return fc
        except Exception as exc:
            logger.debug("TimesFMTradingStrategy forecast error: %s", exc)
            return None
