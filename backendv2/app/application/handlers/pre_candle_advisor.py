"""Pre-candle advisory — fires T-60 s before 5-min bar close.

Non-blocking.  Results are pushed to the React dashboard via a callback.
This service is dashboard-only; it never feeds a gate or entry decision.

Spec:
  Trigger : T-60 s before 5-min bar close (bar minute 4)
  Output  : scenario_narrative, expected_setup, key_levels
  Consumer: React dashboard ONLY
  Timeout : 12 s (missed = no advisory, not an error)
  Temp    : 0.3 / max_tokens 80
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.domain.shared.port.llm_inference import ILLMInference
    from app.domain.trading.model.value_objects import AMTResult, OHLC

logger = logging.getLogger(__name__)

ADVISORY_TIMEOUT: float = 12.0
_DEBOUNCE_SECONDS: float = 250.0

_INSTRUCTION = (
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
    """Immutable pre-candle advisory."""

    symbol: str
    scenario: str
    expected_setup: str
    key_levels: str
    timestamp: float = field(default_factory=time.time)
    timed_out: bool = False


# ---------------------------------------------------------------------------
# Prompt / parsing helpers (self-contained so no cross-module import needed)
# ---------------------------------------------------------------------------

def _build_advisory_prompt(
    symbol: str,
    tick: "OHLC",
    amt: "AMTResult",
) -> str:
    bar_time = getattr(tick, "time", "")
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(bar_time))
        section_1 = dt.strftime("%A, %B %d, %Y %H:%M IST")
    except Exception:
        section_1 = str(bar_time)

    section_2 = (
        f"O={tick.open} H={tick.high} L={tick.low} C={tick.close} V={tick.volume}"
    )
    market_state = getattr(amt, "market_state", "UNKNOWN")
    poc = getattr(amt, "poc", 0)
    vah = getattr(amt, "value_area_high", 0)
    val = getattr(amt, "value_area_low", 0)
    section_3 = f"State={market_state} POC={poc} VAH={vah} VAL={val}"

    aggression = getattr(amt, "aggression", 0)
    cvd_slope = float(getattr(amt, "cvd_slope", 0))
    section_4 = f"Aggression={aggression} CVD_slope={cvd_slope:.1f}"

    lines = [
        f"=== PRE-CANDLE ADVISORY: {symbol} ===",
        f"[Date+Timeline] {section_1}",
        f"[Current Bar] {section_2}",
        f"[Market State] {section_3}",
        f"[Aggression] {section_4}",
    ]
    lvns = getattr(amt, "lvns", None)
    if lvns:
        lines.append(f"LVNs: {list(lvns)[:3]}")
    hvns = getattr(amt, "hvns", None)
    if hvns:
        lines.append(f"HVNs: {list(hvns)[:3]}")
    lines.append("[Instruction] Scenario narrative for dashboard only. Not a trade signal.")
    return "\n".join(lines)


def _parse_advisory_response(raw: str) -> dict[str, str]:
    try:
        match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return {
                "scenario": parsed.get("scenario", ""),
                "expected_setup": parsed.get("expected_setup", ""),
                "key_levels": parsed.get("key_levels", ""),
            }
    except (json.JSONDecodeError, ValueError):
        pass
    return {
        "scenario": (raw or "").strip()[:200],
        "expected_setup": "",
        "key_levels": "",
    }


# ---------------------------------------------------------------------------
# PreCandleAdvisor
# ---------------------------------------------------------------------------

class PreCandleAdvisor:
    """Fire-and-forget pre-candle advisory service.

    Call :meth:`fire_advisory` each tick.  The service debounces itself so
    it fires at most once per 5-minute bar (when bar_minute == 4).
    """

    def __init__(
        self,
        llm: "ILLMInference",
        enabled: bool = True,
    ) -> None:
        self._llm = llm
        self._enabled = enabled
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="pre_candle_advisor"
        )
        self._last_fire: dict[str, float] = {}
        self._on_advisory: Callable[[AdvisoryResult], None] | None = None

    def set_callback(self, callback: Callable[[AdvisoryResult], None]) -> None:
        """Register a callback that receives advisory results (dashboard push)."""
        self._on_advisory = callback

    def should_fire(self, symbol: str, bar_minute: int) -> bool:
        """Return True when the advisory should fire for this bar."""
        if not self._enabled or not self._llm.is_ready():
            return False
        if bar_minute != 4:
            return False
        return time.time() - self._last_fire.get(symbol, 0) >= _DEBOUNCE_SECONDS

    def fire_advisory(
        self,
        symbol: str,
        tick: "OHLC",
        amt_result: "AMTResult",
    ) -> None:
        """Submit advisory task — non-blocking, fire-and-forget."""
        if not self._enabled:
            return
        self._last_fire[symbol] = time.time()
        future = self._executor.submit(self._run, symbol, tick, amt_result)
        future.add_done_callback(self._on_done)

    def _run(
        self,
        symbol: str,
        tick: "OHLC",
        amt_result: "AMTResult",
    ) -> AdvisoryResult:
        try:
            prompt = _build_advisory_prompt(symbol, tick, amt_result)
            raw = self._llm.predict(
                _INSTRUCTION,
                prompt,
                temperature=0.3,
                max_tokens=80,
            )
            parsed = _parse_advisory_response(raw)
            return AdvisoryResult(
                symbol=symbol,
                scenario=parsed.get("scenario", ""),
                expected_setup=parsed.get("expected_setup", ""),
                key_levels=parsed.get("key_levels", ""),
            )
        except Exception as exc:
            logger.debug("Advisory failed for %s: %s", symbol, exc)
            return AdvisoryResult(
                symbol=symbol,
                scenario="",
                expected_setup="",
                key_levels="",
                timed_out=True,
            )

    def _on_done(self, future: concurrent.futures.Future) -> None:
        try:
            result: AdvisoryResult = future.result(timeout=ADVISORY_TIMEOUT)
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
            logger.debug("Advisory timed out (>%.0f s)", ADVISORY_TIMEOUT)
        except Exception as exc:
            logger.debug("Advisory callback error: %s", exc)

    def shutdown(self) -> None:
        """Graceful shutdown (non-blocking)."""
        self._executor.shutdown(wait=False)
