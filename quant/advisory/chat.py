from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str   # "system" | "user" | "assistant"
    content: str


class ChatClient(Protocol):
    def complete(self, messages: list[ChatMessage], max_tokens: int = 200) -> str:
        ...
