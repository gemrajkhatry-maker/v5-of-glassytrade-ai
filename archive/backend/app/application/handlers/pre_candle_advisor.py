"""Pre-Candle Advisory — fires T-60s before 5-min bar close.

Non-blocking advisory service that generates scenario narratives for the
React dashboard. Not used by any gate or entry decision.

Spec (Improvement_phasev1.md):
  Trigger: T-60s before 5-min bar close (bar minute 4:00)
  Output: scenario_narrative, expected_setup, key_levels
  Consumer: React dashboard ONLY — not any gate
  Timeout: 12s (non-blocking — missed = no advisory, not an error)
  Temperature: 0.3
  Max tokens: 80
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from quant.inference.prompt_builder import (
    build_advisory_prompt,
    parse_advisory_response,
)

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC, AMTResult
    from quant.inference.generative_ai import GenerativeAIService

logger = logging.getLogger(__name__)

# Advisory timeout per spec
ADVISORY_TIMEOUT = 12.0

# Advisory instruction — non-blocking, scenario-focused
ADVISORY_INSTRUCTION = (
    "You are a pre-candle market analyst following Fabio Valentini's AMT methodology. "
    "The 5-minute bar is about to close in 60 seconds. Provide a brief scenario "
    "narrative for the dashboard: what setup is forming, key levels to watch, "
    "and expected next-bar behavior. This is advisory only — not a trade signal.\n"
    "Respond with a JSON object: "
    '{"scenario": "...", "expected_setup": "...", "key_levels": "..."}. '
    "Be concise. Max 80 tokens."
)


@dataclass(frozen=True)
class AdvisoryResult:
    """Immutable result of pre-candle advisory."""

    symbol: str
    scenario: str
    expected_setup: str
    key_levels: str
    timestamp: float = field(default_factory=time.time)
    timed_out: bool = False


class PreCandleAdvisor:
    """Pre-candle advisory service — fires T-60s before bar close.

    Non-blocking, fire-and-forget. Results are pushed to the React dashboard
    via the provided callback. Missed advisories are silently dropped.
    """

    def __init__(
        self,
        gen_ai_service: GenerativeAIService,
        enabled: bool = True,
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._enabled = enabled
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        # Per-symbol last advisory timestamp (prevent duplicate fires per bar)
        self._last_fire: dict[str, float] = {}
        # Callback for dashboard push
        self._on_advisory: callable | None = None

    def set_callback(self, callback) -> None:
        """Set callback for advisory results (for dashboard push)."""
        self._on_advisory = callback

    def should_fire(self, symbol: str, bar_minute: int) -> bool:
        """Check if advisory should fire.

        Args:
            symbol: Trading symbol
            bar_minute: Current minute within the 5-min bar (0-4)

        Returns:
            True if advisory should fire (bar minute 4, not recently fired)
        """
        if not self._enabled:
            return False
        if not self._gen_ai_service.is_ready():
            return False
        if bar_minute != 4:  # T-60s before close (bar minute 4:00)
            return False

        # Debounce: don't fire more than once per bar (300s)
        last = self._last_fire.get(symbol, 0)
        if time.time() - last < 250:  # 250s safety margin
            return False

        return True

    def fire_advisory(
        self,
        symbol: str,
        tick: OHLC,
        amt_result: AMTResult,
    ) -> None:
        """Fire advisory asynchronously — non-blocking, 12s timeout.

        Args:
            symbol: Trading symbol
            tick: Current OHLC tick
            amt_result: Latest AMT analysis result
        """
        if not self._enabled:
            return

        self._last_fire[symbol] = time.time()

        future = self._executor.submit(self._do_advisory, symbol, tick, amt_result)
        # Don't wait — fire and forget
        future.add_done_callback(self._handle_result)

    def _do_advisory(
        self,
        symbol: str,
        tick: OHLC,
        amt_result: AMTResult,
    ) -> AdvisoryResult:
        """Execute advisory LLM call with timeout."""
        try:
            prompt = build_advisory_prompt(
                symbol=symbol,
                tick=tick,
                amt_result=amt_result,
            )

            raw_response = self._gen_ai_service.llm_adapter.predict(
                ADVISORY_INSTRUCTION,
                prompt,
            )

            parsed = parse_advisory_response(raw_response)

            return AdvisoryResult(
                symbol=symbol,
                scenario=parsed.get("scenario", ""),
                expected_setup=parsed.get("expected_setup", ""),
                key_levels=parsed.get("key_levels", ""),
            )

        except Exception as e:
            logger.debug("Advisory failed for %s: %s", symbol, e)
            return AdvisoryResult(
                symbol=symbol,
                scenario="",
                expected_setup="",
                key_levels="",
                timed_out=True,
            )

    def _handle_result(self, future: concurrent.futures.Future) -> None:
        """Handle completed advisory result."""
        try:
            result = future.result(timeout=ADVISORY_TIMEOUT)
            if result.scenario and not result.timed_out:
                logger.info(
                    "Advisory [%s]: %s | Setup: %s | Levels: %s",
                    result.symbol,
                    result.scenario,
                    result.expected_setup,
                    result.key_levels,
                )
                if self._on_advisory:
                    self._on_advisory(result)
        except concurrent.futures.TimeoutError:
            logger.debug("Advisory timed out (>%.0fs)", ADVISORY_TIMEOUT)
        except Exception as e:
            logger.debug("Advisory callback error: %s", e)

    def shutdown(self) -> None:
        """Shutdown the executor."""
        self._executor.shutdown(wait=False)
