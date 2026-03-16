"""LLMEntryProcessor — wraps LLMInferencePort in the NiFi-style pipeline interface.

Consumes Message[SignalGatePayload] from inbox["signal_gates"].
Produces Message[LLMDecisionPayload] to outbox["llm_decisions"].

Design:
- gate_pass=False messages are passed through immediately as FLAT decisions (no LLM call).
- gate_pass=True messages trigger a synchronous LLM inference call protected by a
  timeout guard.  Timeouts are caught and emitted as FLAT decisions so downstream
  processors always receive exactly one output message per input message.

All LLM inference logic lives in the injected LLMInferencePort.  Prompt building and
response parsing are delegated to ``prompt_builder``.  This processor is a stateless
pipeline adapter only.

Configuration (ProcessorConfig.settings):
    llm_port: LLMInferencePort — injected at pipeline wiring time (required)
    timeout_seconds: float — LLM call timeout in seconds (default 15)
    instruction: str — LLM system instruction override (default from config)
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from typing import Any

from app.pipeline.channel import Channel
from app.pipeline.message import (
    LLMDecisionPayload,
    Message,
    SignalGateMessage,
    SignalGatePayload,
)
from app.pipeline.processor import BaseProcessor, ProcessorConfig

# Module-level imports for build_entry_prompt and parse_entry_response so that
# tests can patch them at the ``app.pipeline.processors.llm_entry`` namespace.
# We attempt the import eagerly; if the domain layer is unavailable the
# processor falls back to a minimal no-op prompt/parse implementation.
try:
    from app.domain.fabio_ai.services.prompt_builder import (  # noqa: E402
        build_entry_prompt,
        parse_entry_response,
    )
except Exception:  # pragma: no cover — only fails in stripped test environments
    def build_entry_prompt(data: dict) -> str:  # type: ignore[misc]
        """Fallback: return empty string when domain layer unavailable."""
        return ""

    def parse_entry_response(text: str) -> dict:  # type: ignore[misc]
        """Fallback: return FLAT when domain layer unavailable."""
        return {"direction": "FLAT", "logic": "domain layer unavailable", "trigger": "fallback"}

logger = logging.getLogger(__name__)


class LLMEntryProcessor(BaseProcessor):
    """Adapts LLMInferencePort to the pipeline Channel interface for entry decisions.

    For each SignalGateMessage:
      - gate_pass=False  -> emit FLAT decision immediately (no LLM call)
      - gate_pass=True   -> build prompt, call LLM with timeout guard, parse response,
                           emit LLMDecisionPayload
      - LLM timeout      -> emit FLAT decision (never raises to caller)
    """

    name = "llm_entry"

    async def setup(self, config: ProcessorConfig) -> None:
        """Initialise settings and validate required dependencies."""
        await super().setup(config)

        # LLMInferencePort is injected via settings at pipeline wiring time.
        self._llm_port: Any = config.settings.get("llm_port")
        if self._llm_port is None:
            logger.warning(
                "[%s] 'llm_port' not set in settings — all decisions will be FLAT", self.name
            )

        self._timeout_seconds: float = float(config.settings.get("timeout_seconds", 15.0))

        # System instruction can be overridden per-deployment; falls back to config default.
        # The import is deferred so that the processor module remains importable in
        # stripped test environments where ``shared`` (a config dependency) is absent.
        _default_instruction = (
            "You are READING the auction using Fabio Valentini's AMT methodology."
        )
        if "instruction" in config.settings:
            self._instruction: str = str(config.settings["instruction"])
        else:
            try:
                from app.config import settings as _app_settings
                self._instruction = _app_settings.LLM_INSTRUCTION
            except Exception:
                self._instruction = _default_instruction

        # Dedicated thread-pool so the async event loop is never blocked by inference.
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="llm_entry"
        )

    async def teardown(self) -> None:
        """Shutdown the inference thread pool."""
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def process(
        self,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None:
        """Read SignalGateMessages forever; emit one LLMDecisionMessage per message."""
        in_ch: Channel = inbox["signal_gates"]
        out_ch: Channel = outbox["llm_decisions"]

        async for msg in in_ch:
            try:
                await self._handle_gate(msg, out_ch)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "[%s] Unhandled error processing gate message for %s",
                    self.name,
                    getattr(msg, "symbol", "?"),
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_gate(
        self, msg: SignalGateMessage, out: Channel
    ) -> None:
        """Process a single SignalGateMessage and emit a LLMDecisionMessage."""
        p: SignalGatePayload = msg.payload

        if not p.passed:
            # Gate blocked — skip LLM call, emit FLAT immediately.
            logger.debug(
                "[%s] Gate blocked for %s (%s) — emitting FLAT",
                self.name,
                msg.symbol,
                p.reason,
            )
            await self._emit_decision(
                out=out,
                gate_msg=msg,
                direction="FLAT",
                logic=f"Gate blocked: {p.reason}",
                trigger="gate_blocked",
                probability=0.0,
                latency_ms=0.0,
            )
            return

        # Gate passed — call LLM with timeout guard.
        direction, logic, trigger, probability, latency_ms = await self._call_llm(
            msg=msg, gate_payload=p
        )

        await self._emit_decision(
            out=out,
            gate_msg=msg,
            direction=direction,
            logic=logic,
            trigger=trigger,
            probability=probability,
            latency_ms=latency_ms,
        )

    async def _call_llm(
        self,
        msg: SignalGateMessage,
        gate_payload: SignalGatePayload,
    ) -> tuple[str, str, str, float, float]:
        """Call LLM inference and return (direction, logic, trigger, probability, latency_ms).

        Returns FLAT on timeout, model unavailability, or parse failure.
        Runs inference in a background thread so the event loop is not blocked.
        """
        if self._llm_port is None or not self._llm_port.is_ready():
            logger.warning("[%s] LLM port not ready — returning FLAT", self.name)
            return "FLAT", "LLM not ready", "no_model", 0.0, 0.0

        # Build a minimal context dict from the gate payload for prompt construction.
        # The pipeline carries only SignalGatePayload at this stage; a richer context
        # (AMTResult, tick) would require the upstream processor to carry it forward in
        # an expanded payload.  For now we build a minimal prompt that includes the
        # setup grade and confidence so the model has useful context.
        prompt_data = self._build_prompt_data(msg, gate_payload)

        t0 = time.monotonic()
        try:
            # build_entry_prompt and parse_entry_response are imported at module level
            # (with fallbacks) so that tests can patch them at this namespace.
            prompt_text = build_entry_prompt(prompt_data)

            # Submit inference to thread pool so the event loop stays responsive.
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                self._executor,
                self._llm_port.predict,
                self._instruction,
                prompt_text,
            )

            raw_response = await asyncio.wait_for(future, timeout=self._timeout_seconds)

        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "[%s] LLM timed out after %.0fms for %s — returning FLAT",
                self.name,
                elapsed_ms,
                msg.symbol,
            )
            return "FLAT", "LLM timeout", "timeout", 0.0, elapsed_ms

        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.error(
                "[%s] LLM inference error for %s", self.name, msg.symbol, exc_info=True
            )
            return "FLAT", "LLM error", "error", 0.0, elapsed_ms

        elapsed_ms = (time.monotonic() - t0) * 1000

        # Parse the raw LLM response.
        try:
            parsed = parse_entry_response(raw_response)
            direction = str(parsed.get("direction", "FLAT")).upper()
            if direction not in ("LONG", "SHORT", "FLAT"):
                direction = "FLAT"
            logic = str(parsed.get("logic", parsed.get("rationale", "")))
            trigger = str(parsed.get("trigger", "llm"))
            probability = float(parsed.get("probability", gate_payload.confidence))
        except Exception:
            logger.warning(
                "[%s] Failed to parse LLM response for %s — returning FLAT",
                self.name,
                msg.symbol,
                exc_info=True,
            )
            direction, logic, trigger, probability = "FLAT", "parse_error", "parse_error", 0.0

        logger.info(
            "[%s] %s decision for %s in %.0fms (grade=%s)",
            self.name,
            direction,
            msg.symbol,
            elapsed_ms,
            gate_payload.setup_grade,
        )

        return direction, logic, trigger, probability, elapsed_ms

    def _build_prompt_data(
        self, msg: SignalGateMessage, gate_payload: SignalGatePayload
    ) -> dict:
        """Build the minimal context dictionary for build_entry_prompt.

        At the LLM entry stage the pipeline carries only gate-level context.
        Fields not available are set to safe zero-value defaults so that
        ``_build_core_amt_narrative`` can run without AttributeError.
        """
        return {
            # Price context — not available at gate stage; POC defaults to 0.
            "ltp": 0.0,
            "vah": 0.0,
            "val": 0.0,
            "poc": 0.0,
            "delta": 0.0,
            "volume": 0.0,
            # Market structure
            "market_state": "BALANCED",
            "profile_shape": "D",
            "cvd": 0.0,
            "cvd_divergence": "",
            "is_second_drive": False,
            "market_structure": "",
            "aggressive_prints": [],
            "bubble_retests": [],
            "lvn_play": None,
            # Gate context
            "setup_grade": gate_payload.setup_grade,
            "confidence": gate_payload.confidence,
            "gate_reason": gate_payload.reason,
        }

    async def _emit_decision(
        self,
        out: Channel,
        gate_msg: SignalGateMessage,
        direction: str,
        logic: str,
        trigger: str,
        probability: float,
        latency_ms: float,
    ) -> None:
        """Construct and send a LLMDecisionMessage to the outbox channel."""
        payload = LLMDecisionPayload(
            direction=direction,
            logic=logic,
            trigger=trigger,
            probability=probability,
            latency_ms=latency_ms,
        )
        out_msg = Message(
            payload=payload,
            symbol=gate_msg.symbol,
            timestamp=gate_msg.timestamp,
            correlation_id=gate_msg.correlation_id,
            source_processor=self.name,
            pipeline_id=gate_msg.pipeline_id,
        )
        await self._safe_send(out, out_msg)
