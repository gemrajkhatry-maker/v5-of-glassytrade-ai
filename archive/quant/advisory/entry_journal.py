import json
from dataclasses import dataclass

from quant.advisory.chat import ChatClient, ChatMessage
from quant.auction_state import AuctionState


@dataclass(frozen=True)
class JournalEntry:
    symbol: str
    state_time: str
    prompt: str
    response: str
    decision: str          # "LONG" | "SHORT" | "FLAT"
    confidence: float


class EntryJournal:
    def __init__(self, client: ChatClient, system_prompt: str = "You are an AMT scalper.") -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._entries: list[JournalEntry] = []

    def analyze(self, state: AuctionState, symbol: str = "") -> JournalEntry:
        prompt = self._build_prompt(state)
        messages = [
            ChatMessage(role="system", content=self._system_prompt),
            ChatMessage(role="user", content=prompt),
        ]
        response = self._client.complete(messages)
        decision, confidence = self._parse(response)
        entry = JournalEntry(
            symbol=symbol,
            state_time=state.time,
            prompt=prompt,
            response=response,
            decision=decision,
            confidence=confidence,
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

    def _build_prompt(self, state: AuctionState) -> str:
        absorption = state.absorption
        absorption_side = f", absorption_side={absorption.side}" if absorption is not None else ""
        return (
            f"Analyze this AMT auction state:\n"
            f"POC={state.volume_profile.poc}, VAH={state.volume_profile.vah}, VAL={state.volume_profile.val}\n"
            f"market_state={state.triple_a_phase}, triple_a_signal={state.triple_a_signal}{absorption_side}\n"
            f"VWAP={state.vwap.value}, close={state.close}\n"
            f"Respond in JSON with 'direction' (LONG|SHORT|FLAT) and 'confidence' (0..1)."
        )

    def _parse(self, response: str) -> tuple[str, float]:
        try:
            payload = json.loads(response)
            direction = str(payload["direction"]).upper()
            if direction not in ("LONG", "SHORT", "FLAT"):
                direction = "FLAT"
            confidence = max(0.0, min(1.0, float(payload["confidence"])))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return "FLAT", 0.0
        return direction, confidence
