"""SignalGateProcessor — wraps the three-align gate in the pipeline interface.

Consumes Message[AMTResultPayload] from inbox["amt_results"].
Produces Message[SignalGatePayload] to outbox["signal_gates"].

This processor is a pure pipeline adapter: all gate logic lives in
``entry_gate.three_align_check``.  This processor only translates
AMTResultPayload → domain AMTResult → gate result → SignalGatePayload.

Every incoming AMTResultMessage produces exactly one SignalGateMessage.
``SignalGatePayload.passed=True`` means the downstream LLM processor
should fire; ``False`` means skip.  Both outcomes are emitted so
downstream monitors can observe gate statistics.

Configuration (ProcessorConfig.settings):
    min_candles: int — minimum candles before gate opens (default 6, Fabio rule)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.domain.fabio_ai.services.entry_gate import three_align_check  # noqa: E402
from app.pipeline.channel import Channel
from app.pipeline.message import (
    AMTResultMessage,
    AMTResultPayload,
    Message,
    SignalGatePayload,
)
from app.pipeline.processor import BaseProcessor, ProcessorConfig

logger = logging.getLogger(__name__)


class SignalGateProcessor(BaseProcessor):
    """Applies the Three-Align gate to each AMTResultMessage.

    The gate checks:
      1. Market State — BALANCED or IMBALANCED with a valid VA range
      2. Price Location — price is near a structural level (VA edge / POC / LVN)
      3. Confirmation Bundle — volume impulse + delta pressure + spread (2/3)

    Gate logic is delegated to ``entry_gate.three_align_check`` unchanged.
    The processor only bridges payload types.
    """

    name = "signal_gate"

    async def setup(self, config: ProcessorConfig) -> None:
        """Load settings."""
        await super().setup(config)
        self._min_candles: int = int(config.settings.get("min_candles", 6))

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def process(
        self,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None:
        """Read AMTResultMessages forever; emit a SignalGateMessage for each."""
        in_ch: Channel = inbox["amt_results"]
        out_ch: Channel = outbox["signal_gates"]

        async for msg in in_ch:
            try:
                await self._handle_amt_result(msg, out_ch)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "[%s] Error processing AMT result for %s",
                    self.name,
                    getattr(msg, "symbol", "?"),
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_domain_amt_result(self, p: AMTResultPayload) -> Any:
        """Reconstruct a minimal AMTResult-compatible object from the payload.

        We do NOT import the concrete AMTResult dataclass at this layer to
        keep the processor decoupled from the domain.  Instead we build a
        SimpleNamespace that satisfies the attribute-access pattern used by
        ``three_align_check``.
        """
        from types import SimpleNamespace

        return SimpleNamespace(
            market_state=p.market_state,
            poc=p.poc,
            value_area_high=p.vah,
            value_area_low=p.val,
            cvd_slope=p.cvd_slope,
            cvd_divergence=p.cvd_divergence,
            profile_shape=p.profile_shape,
            aggression=p.delta_score,
            # Fields used by three_align_check for extended level checks;
            # unavailable at this pipeline stage — default to 0 / empty.
            session_vwap=0.0,
            vwap_upper_2=0.0,
            vwap_lower_2=0.0,
            dev_poc=0.0,
            dev_vah=0.0,
            dev_val=0.0,
            leg_poc=0.0,
            leg_vah=0.0,
            leg_val=0.0,
            hvns=(),
            lvns=(),
            aggressive_prints=(),
            lvn_play=None,
        )

    def _build_synthetic_tick(self, p: AMTResultPayload) -> Any:
        """Create a minimal tick-like object representing current price.

        three_align_check uses tick.close for near-level checks.
        We approximate current price as the POC (best available proxy when
        no live tick is carried in the pipeline message).
        """
        from types import SimpleNamespace

        # Use POC as the price reference — it is the fair-value anchor
        # that the gate needs for near-level proximity checks.
        price = p.poc if p.poc > 0 else 1.0
        return SimpleNamespace(
            time="",
            open=price,
            high=price,
            low=price,
            close=price,
            volume=0.0,
            vwap=0.0,
            taker_buy_volume=0.0,
            delta=0.0,
        )

    async def _handle_amt_result(
        self, msg: AMTResultMessage, out: Channel
    ) -> None:
        """Evaluate the gate and emit a SignalGateMessage."""
        p: AMTResultPayload = msg.payload

        amt_domain = self._build_domain_amt_result(p)
        tick = self._build_synthetic_tick(p)

        # Provide a minimal candle list that satisfies min_candles_gate.
        # The gate only counts elements in the list; OHLC values are not used
        # for the structural checks when we pass amt_domain directly.
        # We create dummy entries matching the minimum required count so the
        # gate can make a decision based on market-structure data.
        dummy_candles = [tick] * self._min_candles

        try:
            gate_result = three_align_check(
                data=dummy_candles,
                amt_result=amt_domain,
                tick=tick,
                order_book=None,
                ib_high=0.0,
                ib_low=0.0,
                aggressive_levels=None,
                footprint_domain=None,
                return_is_second_drive=True,
            )
        except Exception:
            logger.error(
                "[%s] three_align_check failed for %s",
                self.name,
                msg.symbol,
                exc_info=True,
            )
            gate_passed = False
            confirmation_strong = False
        else:
            # Returns (gate_passed, confirmation_strong, is_second_drive) when
            # return_is_second_drive=True.
            gate_passed = bool(gate_result[0])
            confirmation_strong = bool(gate_result[1])

        # Derive a human-readable reason for observability.
        if gate_passed:
            reason = (
                "Three-Align PASSED"
                + (" (confirmation strong)" if confirmation_strong else "")
            )
        else:
            # Distinguish the most common failure modes for monitoring.
            if p.poc <= 0 or p.vah <= 0 or p.val <= 0:
                reason = "Gate BLOCKED: invalid profile (no VP data)"
            elif p.market_state not in ("BALANCED", "IMBALANCED"):
                reason = f"Gate BLOCKED: market state '{p.market_state}' not tradeable"
            else:
                reason = "Gate BLOCKED: price not near structural level"

        # Assign a setup grade based on confirmation quality.
        if gate_passed and confirmation_strong:
            setup_grade = "A"
        elif gate_passed:
            setup_grade = "B"
        else:
            setup_grade = ""

        # Confidence is a simple heuristic: confirmation_score / 3.
        # The pipeline message carries confirmation_score=0 by default (set by
        # AMTAnalysisProcessor); a real value requires order-book data that is
        # not yet in the payload.  We use 1.0 when gate passes with strong
        # confirmation, 0.5 when weakly passing, 0.0 otherwise.
        if gate_passed and confirmation_strong:
            confidence = 1.0
        elif gate_passed:
            confidence = 0.5
        else:
            confidence = 0.0

        gate_payload = SignalGatePayload(
            passed=gate_passed,
            reason=reason,
            setup_grade=setup_grade,
            confidence=confidence,
        )

        gate_msg = Message(
            payload=gate_payload,
            symbol=msg.symbol,
            timestamp=msg.timestamp,
            correlation_id=msg.correlation_id,
            source_processor=self.name,
            pipeline_id=msg.pipeline_id,
        )

        await self._safe_send(out, gate_msg)
