"""Post-trade analyst — fire-and-forget LLM quality scoring.

Triggered by PositionClosed events.  Results are stored for the
learning system; a timeout or inference failure is never fatal.

Spec:
  Trigger : PositionClosed event
  Output  : quality_score (1-10), mistake, improvement
  Timeout : 30 s (non-blocking)
  Temp    : 0.25 / max_tokens 150
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.domain.shared.port.llm_inference import ILLMInference
    from app.domain.shared.port.storage import IKeyValueStorage

logger = logging.getLogger(__name__)

POST_TRADE_TIMEOUT: float = 30.0

_INSTRUCTION = (
    "You are a post-trade analyst following Fabio Valentini's orderflow methodology. "
    "A trade has just closed. Analyze the entry/exit context, market conditions, "
    "and outcome to provide a brief quality assessment.\n"
    "Respond with a JSON object: "
    '{"quality_score": 1-10, "mistake": "description or none", "improvement": "note"}. '
    "Be concise. Max 150 tokens. Temperature 0.25."
)


@dataclass(frozen=True)
class PostTradeAnalysis:
    """Result of post-trade LLM quality scoring."""

    symbol: str
    quality_score: int
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
    """Build 4-section post-trade prompt (spec P3-3)."""
    rr = abs(exit_price - entry_price) / max(abs(entry_price * 0.01), 0.01)
    lines = [
        f"=== POST-TRADE ANALYSIS: {symbol} ===",
        (
            f"[Trade Data] Side={side} Entry={entry_price} Exit={exit_price} "
            f"PnL={pnl:.2f} Hold={hold_time_seconds:.0f}s "
            f"Close={close_reason} R={rr:.1f}"
        ),
        f"[Entry Context] {entry_context}" if entry_context else "[Entry Context] Not recorded",
        f"[Market at Close] {exit_context}" if exit_context else "[Market at Close] Not recorded",
        "[Instruction] Score 1-10, identify mistake if any, suggest one improvement.",
    ]
    return "\n".join(lines)


def parse_post_trade_response(raw: str) -> dict[str, Any]:
    """Extract quality_score / mistake / improvement from raw LLM output."""
    try:
        match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return {
                "quality_score": max(1, min(10, int(parsed.get("quality_score", 5)))),
                "mistake": str(parsed.get("mistake", "none")),
                "improvement": str(parsed.get("improvement", "")),
            }
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return {
        "quality_score": 5,
        "mistake": "none",
        "improvement": (raw or "").strip()[:200],
    }


class PostTradeAnalyst:
    """Non-blocking post-trade quality analyser.

    Pass an ILLMInference adapter.  Results are stored in kv storage when
    available; missed analyses are silently dropped.
    """

    def __init__(
        self,
        llm: ILLMInference,
        storage: IKeyValueStorage | None = None,
        enabled: bool = True,
    ) -> None:
        self._llm = llm
        self._storage = storage
        self._enabled = enabled
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="post_trade_analyst"
        )

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
        """Submit a non-blocking post-trade analysis task."""
        if not self._enabled or not self._llm.is_ready():
            return
        future = self._executor.submit(
            self._run,
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
        future.add_done_callback(self._on_done)

    def _run(
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
            raw = self._llm.predict(
                _INSTRUCTION,
                prompt,
                temperature=0.25,
                max_tokens=150,
            )
            parsed = parse_post_trade_response(raw)
            return PostTradeAnalysis(
                symbol=symbol,
                quality_score=parsed["quality_score"],
                mistake=parsed["mistake"],
                improvement=parsed["improvement"],
                raw_response=raw,
            )
        except Exception as exc:
            logger.debug("Post-trade analysis failed for %s: %s", symbol, exc)
            return PostTradeAnalysis(
                symbol=symbol,
                quality_score=5,
                mistake="analysis_failed",
                improvement=str(exc),
            )

    def _on_done(self, future: concurrent.futures.Future) -> None:
        try:
            result: PostTradeAnalysis = future.result(timeout=POST_TRADE_TIMEOUT)
            logger.info(
                "Post-trade [%s]: quality=%d/10 mistake=%s improvement=%s",
                result.symbol,
                result.quality_score,
                result.mistake,
                result.improvement,
            )
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
                    pass
        except concurrent.futures.TimeoutError:
            logger.debug("Post-trade analysis timed out (>%.0f s)", POST_TRADE_TIMEOUT)
        except Exception as exc:
            logger.debug("Post-trade callback error: %s", exc)

    def shutdown(self) -> None:
        """Graceful shutdown (non-blocking)."""
        self._executor.shutdown(wait=False)
