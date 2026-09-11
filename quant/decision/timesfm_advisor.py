"""TimesFM + Qwen Asynchronous Market Thesis Advisor.

Connects to the TimesFM Prediction Service (http://localhost:8091),
buffers rolling 32-snapshot windows from DecisionContext, and asynchronously
emits AgentDecisionProduced events containing:
- Direction (LONG | SHORT | FLAT)
- Multi-step forecast horizon (32 steps)
- Quantile spread & mean forecast
- 4-gate validation results
- Model versions (TimesFM 3.0, Qwen 3.8-27B)
- Institutional narrative reasoning
- Microsecond/millisecond latency metrics
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional

from quant.decision.context import DecisionContext
from quant.decision.timesfm_client import (
    DEFAULT_SERVICE_URL,
    TimesFMClient,
    TimesFMSnapshotBuffer,
    context_to_snapshot,
)
from quant.events import AgentDecisionProduced
from quant.llm.narrative import build_rule_based_narrative

logger = logging.getLogger(__name__)


def build_decision_payload(
    ctx: DecisionContext,
    service_res: Optional[Dict[str, Any]],
    rule_narrative: Dict[str, Any],
    fallback_source: str = "AMT_LOCAL",
) -> Dict[str, Any]:
    """Assemble the unified agent decision dictionary for WS transmission."""
    if service_res:
        direction = str(service_res.get("direction") or "FLAT").upper()
        role = str(service_res.get("role") or ("POSITION_MANAGEMENT" if ctx.position_open else "SCANNING"))
        default_action = "HOLD" if ctx.position_open else (f"ENTER_{direction}" if direction != "FLAT" else "FLAT")
        action = str(service_res.get("action") or default_action)
        setup = str(service_res.get("setup") or ("POSITION_MGMT" if ctx.position_open else "TIMESFM_AUCTION"))
        reason = service_res.get("reason")
        conf_score = float(service_res.get("confidenceScore") or service_res.get("confidence", 0.0))
        conf_str = service_res.get("confidence") if isinstance(service_res.get("confidence"), str) else ("High" if conf_score >= 0.75 else ("Medium" if conf_score >= 0.45 else "Low"))
        q_narrative = str(service_res.get("narrative") or "").strip()
        rationale = q_narrative if q_narrative else str(service_res.get("rationale") or rule_narrative.get("rationale") or "")
        source = service_res.get("source") or ("TIMESFM_QWEN" if q_narrative else "TIMESFM_3.0")
        lat_ms = float(service_res.get("latencyMs") or service_res.get("latency_ms", 0.0))
        forecast_steps = list(service_res.get("forecastSteps") or service_res.get("forecast_steps") or [])
        quantile_spread = float(service_res.get("quantileSpread") or service_res.get("quantile_spread", 0.0))
        mean_forecast = float(service_res.get("meanForecast") or service_res.get("mean_forecast", 0.0))
        gate_results = list(service_res.get("gateResults") or service_res.get("gate_results") or [])
        model_versions = dict(service_res.get("modelVersions") or service_res.get("model_versions") or {"timesfm": "3.0", "agent_role": role})
        active_pos = service_res.get("activePosition")
        dyn_trail = service_res.get("dynamicTrailStop")
    else:
        role = "POSITION_MANAGEMENT" if ctx.position_open else "SCANNING"
        direction = str(rule_narrative.get("direction") or "FLAT").upper()
        conf_str = str(rule_narrative.get("confidence") or "Low")
        conf_score = 0.5 if conf_str == "High" else 0.2
        rationale = str(rule_narrative.get("rationale") or "")
        source = fallback_source
        lat_ms = 0.0
        forecast_steps = [direction] * 32
        quantile_spread = 0.0
        mean_forecast = float(ctx.bar.close if ctx.bar else (ctx.state.poc if ctx.state else 0.0))
        gate_results = []
        model_versions = {"engine": "rule_based", "agent_role": role}
        dyn_trail = None
        if ctx.position_open:
            action = str(rule_narrative.get("action") or "HOLD")
            setup = "POSITION_MGMT"
            reason = str(rule_narrative.get("setup") or "TREND_INTACT")
            active_pos = {
                "side": ctx.position_side or direction,
                "entryPrice": round(ctx.position_entry_price, 2),
                "currentPrice": round(ctx.bar.close if ctx.bar else 0.0, 2),
                "pnl": round(ctx.position_unrealized_pnl, 2),
                "stopLoss": round(ctx.position_sl, 2) if ctx.position_sl > 0 else None,
                "takeProfit": round(ctx.position_tp, 2) if ctx.position_tp > 0 else None,
                "barsHeld": ctx.position_bars_held,
                "isRiskFree": bool(ctx.position_sl >= ctx.position_entry_price) if ctx.position_side == "LONG" else bool(ctx.position_sl > 0 and ctx.position_sl <= ctx.position_entry_price),
            }
        else:
            action = f"ENTER_{direction}" if direction != "FLAT" else "FLAT"
            setup = "AMT_AUCTION"
            reason = None
            active_pos = None

    regime = ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED")
    timing = str(ctx.session_phase or "REGULAR")

    return {
        "role": role,
        "action": action,
        "direction": direction,
        "setup": setup,
        "reason": reason,
        "confidence": conf_str,
        "confidenceScore": round(conf_score, 3),
        "rationale": rationale,
        "source": source,
        "latencyMs": round(lat_ms, 1),
        "forecastSteps": forecast_steps,
        "quantileSpread": round(quantile_spread, 4),
        "meanForecast": round(mean_forecast, 2),
        "gateResults": gate_results,
        "activePosition": active_pos,
        "dynamicTrailStop": dyn_trail,
        "modelVersions": model_versions,
        # Backward compatibility with WSAgentDecision:
        "modelLabel": f"TimesFM-{role}",
        "regime": regime,
        "timing": timing,
        "sizeFraction": 1.0 if (action in ("ENTER_LONG", "ENTER_SHORT", "HOLD", "TIGHTEN_SL")) else 0.0,
        "latencyUs": int(lat_ms * 1000),
    }


class TimesFMAdvisor:
    """Non-blocking advisor backed by native TimesFM 3.0 or microservice."""

    def __init__(
        self,
        emit_fn: Optional[Callable[[Any], None]] = None,
        service_url: str = DEFAULT_SERVICE_URL,
        enable_llm_narrative: bool = False,
        use_native_engine: bool = True,
        device: str = "cpu",
    ) -> None:
        self._emit_fn = emit_fn
        self._service_url = service_url
        self._enable_llm_narrative = enable_llm_narrative
        self._use_native_engine = use_native_engine

        if self._use_native_engine:
            from quant.decision.timesfm_engine import TimesFMEngine
            self._native_engine: Optional[TimesFMEngine] = TimesFMEngine(target_horizon=32, device=device)
            self._client = None
            self._buffer = None
            logger.info("TimesFMAdvisor running in NATIVE in-process mode (zero LLM / zero microservice)")
        else:
            self._native_engine = None
            self._client = TimesFMClient(service_url)
            self._buffer = TimesFMSnapshotBuffer(target_size=32)
            logger.info("TimesFMAdvisor initialized with remote service: %s", service_url)

        # Single-slot queue so slow inference drops stale bars
        self._queue: queue.Queue[DecisionContext] = queue.Queue(maxsize=3)
        self._running = True
        self._last_narrative_time: Dict[str, float] = {}

        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="TimesFMAdvisorWorker"
        )
        self._worker_thread.start()

    def set_emit_fn(self, emit_fn: Callable[[Any], None]) -> None:
        self._emit_fn = emit_fn

    def on_context(self, ctx: DecisionContext) -> None:
        """Enqueue DecisionContext for async TimesFM analysis.
        Emits instant baseline rule narrative (0ms) so UI is never blank.
        """
        # 1. Instant baseline emission (0ms) - guarded so advisory never crashes caller
        try:
            rule_decision = build_rule_based_narrative(ctx)
            baseline = build_decision_payload(ctx, None, rule_decision, fallback_source="AMT_LOCAL")
            self._emit_decision(ctx, baseline)
        except Exception:
            logger.exception("Failed to build/emit rule-based narrative in on_context for %s", getattr(ctx, "symbol", "UNKNOWN"))

        # 2. Queue for TimesFM worker thread
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:  # silent-except - queue.Empty when draining a full queue
                    pass
            self._queue.put_nowait(ctx)
        except Exception:  # silent-except - advisor enqueue is best-effort and must never block decisions
            pass

    def _emit_decision(self, ctx: DecisionContext, decision: Dict[str, Any]) -> None:
        if not self._emit_fn or not decision:
            return
        event_time = ctx.time_str or (ctx.bar.time if ctx.bar else "")
        self._emit_fn(AgentDecisionProduced(symbol=ctx.symbol, time=event_time, decision=decision))

    def _worker_loop(self) -> None:
        while self._running:
            try:
                ctx = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._process_context(ctx)
            except Exception as e:
                logger.debug("TimesFMAdvisor worker error: %s", e)
            finally:
                self._queue.task_done()

    def _process_context(self, ctx: DecisionContext) -> None:
        if self._use_native_engine and self._native_engine is not None:
            try:
                native_payload = self._native_engine.analyze(ctx)
                self._emit_decision(ctx, native_payload)
            except Exception as e:
                logger.warning("TimesFM native analyze error: %s", e)
            return

        if not self._client or not self._buffer:
            return

        snapshot = context_to_snapshot(ctx)
        snapshots = self._buffer.add_snapshot(snapshot)
        rule_narrative = build_rule_based_narrative(ctx)

        # 1. Fast path: TimesFM forecast steps, spread, mean forecast & gates (~200ms)
        res_fast = self._client.predict(snapshots, invoke_llm=False, timeout=3.0)
        if res_fast:
            fast_payload = build_decision_payload(ctx, res_fast, rule_narrative)
            self._emit_decision(ctx, fast_payload)
        else:
            # Service not responding — keep rule-based baseline
            return

        # 2. Deep narrative path: invoke Qwen 27B if enabled and not throttled
        # Rate-limit deep LLM call to at most once every 30 seconds per symbol
        if self._enable_llm_narrative and res_fast.get("direction") != "FLAT":
            now = time.time()
            last_time = self._last_narrative_time.get(ctx.symbol, 0.0)
            if now - last_time >= 30.0:
                self._last_narrative_time[ctx.symbol] = now
                try:
                    res_deep = self._client.predict(snapshots, invoke_llm=True, timeout=35.0)
                    if res_deep and res_deep.get("narrative"):
                        deep_payload = build_decision_payload(ctx, res_deep, rule_narrative)
                        self._emit_decision(ctx, deep_payload)
                except Exception as e:
                    logger.debug("TimesFM deep narrative generation skipped: %s", e)

    def shutdown(self) -> None:
        self._running = False
        try:
            self._worker_thread.join(timeout=2.0)
        except Exception:  # silent-except - worker thread join on shutdown is best-effort
            pass
