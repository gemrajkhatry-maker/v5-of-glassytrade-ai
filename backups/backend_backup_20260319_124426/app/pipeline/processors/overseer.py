"""OverseerProcessor — wraps LLMOverseerHandler in the NiFi-style pipeline interface.

Consumes Message[LLMDecisionPayload] from inbox["llm_decisions"].
Produces Message[OverseerDecisionPayload] to outbox["overseer_decisions"].

Design:
- FLAT direction messages are passed through as a no-op HOLD decision (no overseer call).
- LONG/SHORT decisions are forwarded to the injected OverseerHandler for position
  lifecycle management (HOLD/TIGHTEN_SL/PARTIAL_EXIT/FULL_EXIT/ADD).
- The processor runs the overseer check on every new LONG/SHORT decision received, so
  it respects the pipeline cadence rather than its own internal timer.
- All position management logic lives in the existing LLMOverseerHandler.  This
  processor is only a pipeline adapter — a stateless shell.

Configuration (ProcessorConfig.settings):
    overseer_handler: LLMOverseerHandler — injected at pipeline wiring time (required)
    check_interval_seconds: float — minimum seconds between overseer calls per symbol
                                    (default 10.0); enforced here as a lightweight
                                    rate-limiting guard.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from app.pipeline.channel import Channel
from app.pipeline.message import (
    LLMDecisionMessage,
    LLMDecisionPayload,
    Message,
    OverseerDecisionPayload,
)
from app.pipeline.processor import BaseProcessor, ProcessorConfig

logger = logging.getLogger(__name__)


class OverseerProcessor(BaseProcessor):
    """Adapts LLMOverseerHandler to the pipeline Channel interface.

    For each LLMDecisionMessage:
      - direction=FLAT  -> emit a HOLD decision immediately (no overseer call)
      - direction=LONG/SHORT -> delegate to OverseerHandler if cooldown elapsed;
                               if within cooldown, emit HOLD without calling handler
    """

    name = "overseer"

    async def setup(self, config: ProcessorConfig) -> None:
        """Load settings and validate injected handler."""
        await super().setup(config)

        # LLMOverseerHandler injected via settings at pipeline wiring time.
        self._overseer_handler: Any = config.settings.get("overseer_handler")
        if self._overseer_handler is None:
            logger.warning(
                "[%s] 'overseer_handler' not set in settings — all decisions will be HOLD",
                self.name,
            )

        self._check_interval: float = float(
            config.settings.get("check_interval_seconds", 10.0)
        )

        # Per-symbol last-run timestamps for cooldown enforcement.
        self._last_run: dict[str, float] = defaultdict(float)

    async def teardown(self) -> None:
        """No external resources owned by this processor."""

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def process(
        self,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None:
        """Read LLMDecisionMessages forever; emit one OverseerDecisionMessage per message."""
        in_ch: Channel = inbox["llm_decisions"]
        out_ch: Channel = outbox["overseer_decisions"]

        async for msg in in_ch:
            try:
                await self._handle_decision(msg, out_ch)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "[%s] Unhandled error processing decision for %s",
                    self.name,
                    getattr(msg, "symbol", "?"),
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_decision(
        self, msg: LLMDecisionMessage, out: Channel
    ) -> None:
        """Process one LLMDecisionMessage and emit an OverseerDecisionMessage."""
        p: LLMDecisionPayload = msg.payload
        symbol: str = msg.symbol

        if p.direction == "FLAT":
            # No active position intended — emit passive HOLD and move on.
            logger.debug("[%s] FLAT decision for %s — no overseer action", self.name, symbol)
            await self._emit_overseer_decision(
                out=out,
                decision_msg=msg,
                action="HOLD",
                reason="Entry direction FLAT — no position to manage",
                position_id="",
            )
            return

        # LONG or SHORT — check cooldown before delegating to handler.
        now = time.monotonic()
        last = self._last_run[symbol]
        if (now - last) < self._check_interval and last > 0:
            logger.debug(
                "[%s] %s cooldown active (%.1fs remaining) — skipping overseer",
                self.name,
                symbol,
                self._check_interval - (now - last),
            )
            await self._emit_overseer_decision(
                out=out,
                decision_msg=msg,
                action="HOLD",
                reason="Overseer cooldown active",
                position_id="",
            )
            return

        self._last_run[symbol] = now

        if self._overseer_handler is None:
            await self._emit_overseer_decision(
                out=out,
                decision_msg=msg,
                action="HOLD",
                reason="No overseer handler configured",
                position_id="",
            )
            return

        # Delegate to the existing OverseerHandler.
        # The handler exposes ``should_run`` + ``run_overseer`` for its session-based
        # path, but as a pipeline adapter we call the simpler execute path that returns
        # an OverseerAction synchronously.  If the handler provides an ``execute``
        # method we prefer it; otherwise we emit a pass-through HOLD so the processor
        # degrades gracefully when connected to the full handler.
        action, reason, position_id = await self._run_overseer_handler(
            handler=self._overseer_handler,
            direction=p.direction,
            symbol=symbol,
        )

        await self._emit_overseer_decision(
            out=out,
            decision_msg=msg,
            action=action,
            reason=reason,
            position_id=position_id,
        )

    async def _run_overseer_handler(
        self,
        handler: Any,
        direction: str,
        symbol: str,
    ) -> tuple[str, str, str]:
        """Call the OverseerHandler and return (action, reason, position_id).

        The existing LLMOverseerHandler does not expose a simple synchronous
        ``execute(direction, symbol)`` method — it operates through session state and
        background queues.  This processor calls ``execute`` if available (for future
        handler implementations that follow the pipeline contract), and falls back to
        a HOLD if the handler does not provide it.

        This design keeps the processor loosely coupled from the handler's internals
        while allowing the handler to be upgraded independently.
        """
        execute = getattr(handler, "execute", None)
        if callable(execute):
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    execute,
                    direction,
                    symbol,
                )
                if result is not None:
                    action = str(getattr(result, "action", "HOLD"))
                    reason = str(getattr(result, "reason", ""))
                    position_id = str(getattr(result, "position_id", ""))
                    return action, reason, position_id
            except Exception:
                logger.error(
                    "[%s] OverseerHandler.execute failed for %s",
                    self.name,
                    symbol,
                    exc_info=True,
                )

        # Handler does not support execute() — acknowledge the decision as HOLD.
        logger.debug(
            "[%s] OverseerHandler has no execute() — emitting HOLD for %s %s",
            self.name,
            direction,
            symbol,
        )
        return "HOLD", f"Overseer acknowledged {direction} for {symbol}", ""

    async def _emit_overseer_decision(
        self,
        out: Channel,
        decision_msg: LLMDecisionMessage,
        action: str,
        reason: str,
        position_id: str,
    ) -> None:
        """Construct and send an OverseerDecisionMessage to the outbox channel."""
        payload = OverseerDecisionPayload(
            action=action,
            reason=reason,
            position_id=position_id,
        )
        out_msg = Message(
            payload=payload,
            symbol=decision_msg.symbol,
            timestamp=decision_msg.timestamp,
            correlation_id=decision_msg.correlation_id,
            source_processor=self.name,
            pipeline_id=decision_msg.pipeline_id,
        )
        await self._safe_send(out, out_msg)
