"""Base class for LLM inference adapters.

Extracts shared logic from MLXInferenceAdapter and GGUFInferenceAdapter
to eliminate duplication.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

ENTRY_JSON_RUNTIME_REMINDER = (
    "Return ONLY a JSON object with 'direction' and 'confidence'."
)


class SingletonMixin:
    """Thread-safe singleton mixin for adapter classes."""

    _instance: Any | None = None
    _init_lock: threading.Lock | None = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            if cls._init_lock is None:
                cls._init_lock = threading.Lock()
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance


class BaseLLMInferenceAdapter(ABC, SingletonMixin):
    """Base adapter with shared LLM inference utilities.

    Subclasses must implement:
    - is_ready() -> bool
    - predict(prompt: str, **kwargs) -> str
    """

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True if the adapter is ready to serve requests."""
        ...

    @abstractmethod
    def predict(self, prompt: str, **kwargs: Any) -> str:
        """Run inference on a prompt and return the response text."""
        ...

    @staticmethod
    def _extract_json_candidate(text: str) -> dict[str, Any] | None:
        """Extract the first JSON object from text.

        Handles responses with markdown fences, extra text, etc.
        """
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            return None

    def wait_until_ready(self, timeout: float = 120.0, poll_interval: float = 1.0) -> bool:
        """Poll until the adapter is ready or timeout expires.

        Args:
            timeout: Maximum seconds to wait.
            poll_interval: Seconds between polls.

        Returns:
            True if ready, False if timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_ready():
                return True
            time.sleep(poll_interval)
        return False
