"""Post-Trade Analyst — analyzes completed trades via LLM.

Triggered by PositionClosed event. Fire-and-forget, 30s timeout.
Produces trade quality score, mistake identification, and improvement notes.

Spec (Improvement_phasev1.md):
  Trigger: PositionClosed event
  Output: trade_quality_score, mistake_identified, improvement_note
  Timeout: 30s (non-blocking — trade already closed, no rush)
  Temperature: 0.25
  Max tokens: 150
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    from app.domain.ports.storage import IStorage

logger = logging.getLogger(__name__)

# Post-trade timeout per spec
POST_TRADE_TIMEOUT = 30.0

POST_TRADE_INSTRUCTION = (
    "You are a post-trade analyst following Fabio Valentini's orderflow methodology. "
    "A trade has just closed. Analyze the entry/exit context, market conditions, "
    "and outcome to provide a brief quality assessment.\n"
    "Respond with a JSON object: "
    '{"quality_score": 1-10, "mistake": "description or none", "improvement": "note"}. '
    "Be concise. Max 150 tokens. Temperature 0.25."
)


@dataclass(frozen=True)
class PostTradeAnalysis:
    """Result of post-trade LLM analysis."""

    symbol: str
    quality_score: int  # 1-10
    mistake: str
    improvement: str
    raw_response: str = ""


def build_post_trade_prompt(
    symbol: str,
    entry_price: float,
    exit_price: float,
    side: str,
    pnl: float,
    hold_time_seconds: float,
    close_reason: str,
    entry_context: str = "",
    exit_context: str = "",
) -> str:
    """Build 4-section post-trade prompt per spec P3-3.

    Section 1: Trade data (entry, exit, PnL, hold time, close reason)
    Section 2: Entry context (AMT state, setup type, confidence)
    Section 3: Market state at close (POC/VAH/VAL, regime, aggression)
    Section 4: Instruction (quality score, mistake, improvement)
    """
    pnl_str = f"{pnl:.2f}"
    hold_str = f"{hold_time_seconds:.0f}s"
    rr = abs(exit_price - entry_price) / max(abs(entry_price * 0.01), 0.01)

    lines = [
        f"=== POST-TRADE ANALYSIS: {symbol} ===",
        f"[Trade Data] Side={side} Entry={entry_price} Exit={exit_price} PnL={pnl_str} Hold={hold_str} Close={close_reason} R={rr:.1f}",
    ]

    if entry_context:
        lines.append(f"[Entry Context] {entry_context}")
    else:
        lines.append("[Entry Context] Not recorded")

    if exit_context:
        lines.append(f"[Market at Close] {exit_context}")
    else:
        lines.append("[Market at Close] Not recorded")

    lines.append(
        "[Instruction] Score 1-10, identify mistake if any, suggest one improvement."
    )
    return "\n".join(lines)


def parse_post_trade_response(raw_response: str) -> dict[str, Any]:
    """Parse post-trade LLM response."""
    try:
        import json as _json

        match = re.search(r"\{[^{}]+\}", raw_response, re.DOTALL)
        if match:
            parsed = _json.loads(match.group())
            return {
                "quality_score": max(1, min(10, int(parsed.get("quality_score", 5)))),
                "mistake": str(parsed.get("mistake", "none")),
                "improvement": str(parsed.get("improvement", "")),
            }
    except (_json.JSONDecodeError, ValueError, TypeError):
        pass

    return {
        "quality_score": 5,
        "mistake": "none",
        "improvement": (raw_response or "").strip()[:200],
    }


class PostTradeAnalyst:
    """Post-trade analysis service — fire-and-forget LLM analysis.

    Subscribes to PositionClosed events and generates quality assessments.
    Results are stored for the learning system to consume.
    """

    def __init__(
        self,
        gen_ai_service: GenerativeAIService,
        storage: IStorage | None = None,
        enabled: bool = True,
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._storage = storage
        self._enabled = enabled
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def analyze(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        side: str,
        pnl: float,
        hold_time_seconds: float,
        close_reason: str,
        entry_context: str = "",
        exit_context: str = "",
    ) -> None:
        """Fire post-trade analysis — non-blocking, 30s timeout.

        Args:
            symbol: Trading symbol
            entry_price: Entry price
            exit_price: Exit price
            side: LONG or SHORT
            pnl: Realized PnL
            hold_time_seconds: How long position was held
            close_reason: STOP_LOSS, TAKE_PROFIT, PARTIAL_TP, TIME_STOP, MANUAL
            entry_context: AMT state at entry (optional)
            exit_context: AMT state at exit (optional)
        """
        if not self._enabled:
            return
        if not self._gen_ai_service.is_ready():
            return

        future = self._executor.submit(
            self._do_analysis,
            symbol,
            entry_price,
            exit_price,
            side,
            pnl,
            hold_time_seconds,
            close_reason,
            entry_context,
            exit_context,
        )
        future.add_done_callback(self._handle_result)

    def _do_analysis(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        side: str,
        pnl: float,
        hold_time_seconds: float,
        close_reason: str,
        entry_context: str,
        exit_context: str,
    ) -> PostTradeAnalysis:
        """Execute post-trade LLM call."""
        try:
            prompt = build_post_trade_prompt(
                symbol=symbol,
                entry_price=entry_price,
                exit_price=exit_price,
                side=side,
                pnl=pnl,
                hold_time_seconds=hold_time_seconds,
                close_reason=close_reason,
                entry_context=entry_context,
                exit_context=exit_context,
            )

            raw_response = self._gen_ai_service.llm_adapter.predict(
                POST_TRADE_INSTRUCTION,
                prompt,
            )

            parsed = parse_post_trade_response(raw_response)

            return PostTradeAnalysis(
                symbol=symbol,
                quality_score=parsed["quality_score"],
                mistake=parsed["mistake"],
                improvement=parsed["improvement"],
                raw_response=raw_response,
            )

        except Exception as e:
            logger.debug("Post-trade analysis failed for %s: %s", symbol, e)
            return PostTradeAnalysis(
                symbol=symbol,
                quality_score=5,
                mistake="analysis_failed",
                improvement=str(e),
            )

    def _handle_result(self, future: concurrent.futures.Future) -> None:
        """Handle completed post-trade analysis."""
        try:
            result = future.result(timeout=POST_TRADE_TIMEOUT)
            logger.info(
                "Post-trade [%s]: quality=%d/10 mistake=%s improvement=%s",
                result.symbol,
                result.quality_score,
                result.mistake,
                result.improvement,
            )
            # Store result for learning system
            if self._storage:
                try:
                    self._storage.kv_set(
                        f"post_trade:{result.symbol}",
                        {
                            "quality_score": result.quality_score,
                            "mistake": result.mistake,
                            "improvement": result.improvement,
                        },
                    )
                except Exception:
                    pass  # Storage is best-effort
        except concurrent.futures.TimeoutError:
            logger.debug("Post-trade analysis timed out (>%.0fs)", POST_TRADE_TIMEOUT)
        except Exception as e:
            logger.debug("Post-trade callback error: %s", e)

    def shutdown(self) -> None:
        """Shutdown the executor."""
        self._executor.shutdown(wait=False)
