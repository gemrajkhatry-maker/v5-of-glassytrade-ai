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
    market: str — "NSE" | "MCX" | "GLOBAL" (default "NSE")
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
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

    NOW WITH:
    - Full AMT context carried to LLM (Fix #1)
    - 3/3 confirmation enforcement (Fix #2)
    - Second drive detection (Fix #3)
    - Session strategy enforcement (Fix #4)
    - CVD hard block (Fix #5)
    """

    name = "signal_gate"

    async def setup(self, config: ProcessorConfig) -> None:
        """Load settings."""
        await super().setup(config)
        self._min_candles: int = int(config.settings.get("min_candles", 6))
        self._market: str = str(config.settings.get("market", "NSE"))

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

    def _build_domain_amt_result(self, p: AMTResultPayload) -> SimpleNamespace:
        """Reconstruct a minimal AMTResult-compatible object from the payload.
        
        NOW WITH FULL CONTEXT — passes developing VA, leg profile, VWAP,
        LVNs, HVNs, aggressive prints, and LVN play to the gate.
        """
        return SimpleNamespace(
            market_state=p.market_state,
            poc=p.poc,
            value_area_high=p.vah,
            value_area_low=p.val,
            cvd_slope=p.cvd_slope,
            cvd_divergence=p.cvd_divergence,
            profile_shape=p.profile_shape,
            aggression=p.delta_score,
            # Developing VA (NEW)
            session_vwap=p.session_vwap,
            vwap_upper_2=p.vwap_upper_2,
            vwap_lower_2=p.vwap_lower_2,
            dev_poc=p.dev_poc,
            dev_vah=p.dev_vah,
            dev_val=p.dev_val,
            # Impulse leg (NEW)
            leg_poc=p.leg_poc,
            leg_vah=p.leg_vah,
            leg_val=p.leg_val,
            # Structural levels (NEW)
            hvns=p.hvns,
            lvns=p.lvns,
            # Aggressive prints (NEW)
            aggressive_prints=[
                SimpleNamespace(price=ap.get("price", 0), volume=ap.get("volume", 0), side=ap.get("side", ""))
                for ap in p.aggressive_prints
            ] if p.aggressive_prints else (),
            # LVN Play (NEW)
            lvn_play=p.lvn_play,
        )

    def _build_synthetic_tick(self, p: AMTResultPayload) -> SimpleNamespace:
        """Create a minimal tick-like object representing current price.
        
        Uses POC as price reference — the fair-value anchor for proximity checks.
        """
        price = p.poc if p.poc > 0 else 1.0
        return SimpleNamespace(
            time="",
            open=price,
            high=price,
            low=price,
            close=price,
            volume=0.0,
            vwap=p.session_vwap if p.session_vwap > 0 else 0.0,
            taker_buy_volume=0.0,
            delta=p.delta_score,
        )

    def _get_session_context(self, timestamp: datetime) -> dict:
        """Get session context for the current time.
        
        Returns session info needed for session-strategy enforcement.
        """
        try:
            from app.domain.fabio_ai.services.session_context import get_session_info
            session_info = get_session_info(
                timestamp=str(timestamp),
                market=self._market,
            )
            return {
                "session_name": session_info.session,
                "favor_strategy": session_info.favor_strategy,
                "allow_entry": session_info.allow_entry,
                "allow_trend": session_info.allow_trend,
                "allow_reversion": session_info.allow_reversion,
                "force_exit": session_info.force_exit,
                "opening_bias": getattr(session_info, 'opening_relation', 'IN_BALANCE'),
            }
        except Exception:
            logger.debug("[%s] Could not get session context, using defaults", self.name)
            return {
                "session_name": "UNKNOWN",
                "favor_strategy": "NEUTRAL",
                "allow_entry": True,
                "allow_trend": True,
                "allow_reversion": True,
                "force_exit": False,
                "opening_bias": "IN_BALANCE",
            }

    def _check_cvd_hard_block(self, p: AMTResultPayload, direction_hint: str = "") -> tuple[bool, str]:
        """Fabio Rule: If CVD is strongly against you, NO TRADE.
        
        Returns (is_blocked, reason).
        """
        cvd = p.cvd_slope
        
        # Extreme selling in balance = don't fade (potential breakdown)
        if cvd < -50.0 and p.market_state == "BALANCED":
            return True, f"CVD extreme selling ({cvd:.0f}) in balance — do not fade"
        
        # Extreme buying in balance = don't fade (potential breakout)
        if cvd > 50.0 and p.market_state == "BALANCED":
            return True, f"CVD extreme buying (+{cvd:.0f}) in balance — do not fade"
        
        # CVD divergence against trade direction
        if p.cvd_divergence:
            if cvd > 0 and direction_hint == "SHORT":
                return True, "CVD bullish divergence against SHORT direction"
            if cvd < 0 and direction_hint == "LONG":
                return True, "CVD bearish divergence against LONG direction"
        
        return False, ""

    def _derive_cvd_divergence_str(self, p: AMTResultPayload) -> str:
        """Convert cvd_divergence bool + cvd_slope direction into string."""
        if not p.cvd_divergence:
            return ""
        if p.cvd_slope < 0:
            return "BEARISH_DIV"
        if p.cvd_slope > 0:
            return "BULLISH_DIV"
        return "DIVERGENCE"

    def _grade_setup(
        self, gate_passed: bool, confirmation_strong: bool, p: AMTResultPayload
    ) -> tuple[str, float]:
        """Assign setup grade (A/B/C) and confidence based on confirmation quality.
        
        A-grade: Strong confirmation + aligned CVD + LVN play present
        B-grade: Gate passed but confirmation weak or minor headwinds
        """
        if not gate_passed:
            return "", 0.0

        score = 0.0

        # Confirmation quality
        if confirmation_strong:
            score += 0.4
        else:
            score += 0.15

        # CVD alignment
        if abs(p.cvd_slope) < 20.0:
            score += 0.2  # No extreme CVD = good
        elif abs(p.cvd_slope) < 50.0:
            score += 0.1  # Moderate CVD = okay

        # No divergence
        if not p.cvd_divergence:
            score += 0.15

        # Profile shape aligned
        if p.profile_shape in ("D", "B"):
            score += 0.1  # Balanced/bimodal = clean
        elif p.profile_shape in ("P", "b"):
            score += 0.05  # Skewed = watch out

        # LVN play bonus
        if p.lvn_play is not None:
            score += 0.15

        # Aggression present
        if p.aggression == "AGGRESSIVE":
            score += 0.1

        # Map to grade
        if score >= 0.8:
            return "A", min(score, 1.0)
        elif score >= 0.5:
            return "B", score
        else:
            return "C", score

    async def _handle_amt_result(
        self, msg: AMTResultMessage, out: Channel
    ) -> None:
        """Evaluate the gate and emit a SignalGateMessage WITH FULL AMT CONTEXT."""
        p: AMTResultPayload = msg.payload

        # Get session context
        session_ctx = self._get_session_context(msg.timestamp)

        # ── FIX #4: Session strategy enforcement ──
        # Block entries outside allowed session phases
        if not session_ctx["allow_entry"]:
            reason = f"Gate BLOCKED: session '{session_ctx['session_name']}' does not allow entry"
            logger.debug("[%s] %s: %s", self.name, msg.symbol, reason)
            await self._emit_gate(
                out=out,
                msg=msg,
                passed=False,
                reason=reason,
                setup_grade="",
                confidence=0.0,
                amt_payload=p,
                session_ctx=session_ctx,
                cvd_block=(False, ""),
                is_second_drive=False,
            )
            return

        if session_ctx.get("force_exit", False):
            reason = f"Gate BLOCKED: session '{session_ctx['session_name']}' forces exit only"
            await self._emit_gate(
                out=out,
                msg=msg,
                passed=False,
                reason=reason,
                setup_grade="",
                confidence=0.0,
                amt_payload=p,
                session_ctx=session_ctx,
                cvd_block=(False, ""),
                is_second_drive=False,
            )
            return

        # ── FIX #5: CVD hard block check ──
        cvd_blocked, cvd_reason = self._check_cvd_hard_block(p)
        if cvd_blocked:
            reason = f"Gate BLOCKED: {cvd_reason}"
            logger.info("[%s] %s: CVD hard block — %s", self.name, msg.symbol, cvd_reason)
            await self._emit_gate(
                out=out,
                msg=msg,
                passed=False,
                reason=reason,
                setup_grade="",
                confidence=0.0,
                amt_payload=p,
                session_ctx=session_ctx,
                cvd_block=(True, cvd_reason),
                is_second_drive=False,
            )
            return

        # ── Three-Align Gate Execution ──
        amt_domain = self._build_domain_amt_result(p)
        tick = self._build_synthetic_tick(p)
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
            # Returns (gate_passed, confirmation_strong, is_second_drive)
            gate_passed = bool(gate_result[0])
            confirmation_strong = bool(gate_result[1])
            is_second_drive = bool(gate_result[2]) if len(gate_result) > 2 else False
        except Exception:
            logger.error(
                "[%s] three_align_check failed for %s",
                self.name,
                msg.symbol,
                exc_info=True,
            )
            gate_passed = False
            confirmation_strong = False
            is_second_drive = False

        # ── FIX #4: Session-specific model enforcement ──
        if gate_passed:
            is_trend = p.market_state == "IMBALANCED"
            is_reversion = p.market_state == "BALANCED"

            if is_trend and not session_ctx.get("allow_trend", True):
                gate_passed = False
                reason = f"Gate BLOCKED: session '{session_ctx['session_name']}' forbids trend entries"
            elif is_reversion and not session_ctx.get("allow_reversion", True):
                gate_passed = False
                reason = f"Gate BLOCKED: session '{session_ctx['session_name']}' forbids reversion entries"
            else:
                reason = "Three-Align PASSED"
                if confirmation_strong:
                    reason += " (confirmation strong)"
                if is_second_drive:
                    reason += " (second drive)"
        else:
            if p.poc <= 0 or p.vah <= 0 or p.val <= 0:
                reason = "Gate BLOCKED: invalid profile (no VP data)"
            elif p.market_state not in ("BALANCED", "IMBALANCED"):
                reason = f"Gate BLOCKED: market state '{p.market_state}' not tradeable"
            else:
                reason = "Gate BLOCKED: price not near structural level"

        # Grade and confidence
        setup_grade, confidence = self._grade_setup(gate_passed, confirmation_strong, p)

        # Build CVD divergence string
        cvd_div_str = self._derive_cvd_divergence_str(p)

        await self._emit_gate(
            out=out,
            msg=msg,
            passed=gate_passed,
            reason=reason,
            setup_grade=setup_grade,
            confidence=confidence,
            amt_payload=p,
            session_ctx=session_ctx,
            cvd_block=(cvd_blocked, cvd_reason),
            is_second_drive=is_second_drive,
            cvd_div_str=cvd_div_str,
        )

    async def _emit_gate(
        self,
        out: Channel,
        msg: AMTResultMessage,
        passed: bool,
        reason: str,
        setup_grade: str,
        confidence: float,
        amt_payload: AMTResultPayload,
        session_ctx: dict,
        cvd_block: tuple[bool, str],
        is_second_drive: bool,
        cvd_div_str: str = "",
    ) -> None:
        """Construct and send a fully-enriched SignalGateMessage to the outbox."""
        p = amt_payload

        gate_payload = SignalGatePayload(
            passed=passed,
            reason=reason,
            setup_grade=setup_grade,
            confidence=confidence,
            
            # ── AMT Context (FIX #1) ──
            market_state=p.market_state,
            profile_shape=p.profile_shape,
            poc=p.poc,
            vah=p.vah,
            val=p.val,
            cvd_slope=p.cvd_slope,
            cvd_divergence=cvd_div_str,
            delta_score=p.delta_score,
            aggression=p.aggression,
            
            # Developing VA
            dev_poc=p.dev_poc,
            dev_vah=p.dev_vah,
            dev_val=p.dev_val,
            
            # Impulse leg
            leg_poc=p.leg_poc,
            leg_vah=p.leg_vah,
            leg_val=p.leg_val,
            
            # VWAP
            session_vwap=p.session_vwap,
            vwap_upper_2=p.vwap_upper_2,
            vwap_lower_2=p.vwap_lower_2,
            
            # Structural levels
            lvns=p.lvns,
            hvns=p.hvns,
            is_second_drive=is_second_drive,
            
            # LVN Play
            lvn_play=p.lvn_play,
            
            # Aggressive prints
            aggressive_prints=p.aggressive_prints,
            bubble_retests=p.bubble_retests,
            
            # Session context
            session_name=session_ctx.get("session_name", ""),
            favor_strategy=session_ctx.get("favor_strategy", ""),
            opening_bias=session_ctx.get("opening_bias", ""),
            ib_high=0.0,
            ib_low=0.0,
            session_phase=session_ctx.get("session_name", ""),
            
            # CVD hard block
            cvd_hard_block=cvd_block[0],
            cvd_hard_block_reason=cvd_block[1],
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
