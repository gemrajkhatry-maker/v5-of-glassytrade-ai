"""Throttled LLM overseer: cooldown + bounded drop-if-busy queue.

The overseer wraps a ChatClient and asks it whether an open position should
be held, have its stop tightened, be partially closed, or fully closed. It
never gates execution (advisory only) and drops evaluations when busy rather
than blocking the hot path.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass

from quant.advisory.chat import ChatClient, ChatMessage
from quant.auction_state import AuctionState
from quant.execution.order import Position

ACTIONS = ("HOLD", "TIGHTEN_SL", "PARTIAL_EXIT", "FULL_EXIT")


@dataclass(frozen=True)
class OverseerAction:
    action: str          # "HOLD" | "TIGHTEN_SL" | "PARTIAL_EXIT" | "FULL_EXIT"
    rationale: str
    tightened_sl: float | None = None


class Overseer:
    def __init__(self, client: ChatClient, cooldown_seconds: float = 15.0,
                 queue_size: int = 2) -> None:
        self._client = client
        self._cooldown_seconds = cooldown_seconds
        self._queue_size = queue_size
        self._recent_runs: deque[float] = deque(maxlen=queue_size)
        self._last_run: float | None = None

    def should_run(self, last_run_time: float, running: bool) -> bool:
        if running:
            return False
        if self._last_run is None:
            self._last_run = last_run_time
            return True
        if time.time() - last_run_time < self._cooldown_seconds:
            return False
        self._last_run = last_run_time
        return True

    def evaluate(self, state: AuctionState, position: Position) -> OverseerAction | None:
        """Returns None when throttled or queue full."""
        now = time.time()
        if self._cooldown_seconds > 0:
            while self._recent_runs and now - self._recent_runs[0] >= self._cooldown_seconds:
                self._recent_runs.popleft()
        if len(self._recent_runs) >= self._queue_size:
            return None

        prompt = self._build_prompt(state, position)
        try:
            raw = self._client.complete(
                [ChatMessage(role="user", content=prompt)], max_tokens=200
            )
        except Exception:
            return None

        self._recent_runs.append(now)

        action, rationale = self._parse(raw)
        return OverseerAction(action=action, rationale=rationale)

    @staticmethod
    def _build_prompt(state: AuctionState, position: Position) -> str:
        sig = position.order.signal
        return (
            f"Overseer position review.\n"
            f"signal={sig.type} entry={sig.entry} sl={sig.sl} tp={sig.tp} "
            f"open_price={position.open_price} size={position.size} "
            f"open_time={position.open_time} realized_pnl={position.realized_pnl}\n"
            f"state time={state.time} close={state.close} "
            f"vwap={state.vwap.value} vwap_dev={state.vwap.deviation_sigmas}\n"
            f"location zone={state.location.zone} "
            f"poc={state.volume_profile.poc} vah={state.volume_profile.vah} "
            f"val={state.volume_profile.val}\n"
            f"Respond with JSON: {{\"action\": \"HOLD|TIGHTEN_SL|PARTIAL_EXIT|FULL_EXIT\", "
            f"\"rationale\": \"...\"}}"
        )

    @staticmethod
    def _parse(raw: str) -> tuple[str, str]:
        try:
            data = json.loads(raw)
            action = str(data.get("action", "")).upper()
            rationale = str(data.get("rationale", ""))
            if action not in ACTIONS:
                return "HOLD", rationale
            return action, rationale
        except Exception:
            return "HOLD", ""
