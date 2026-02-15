"""AI Model port — abstract interface for AI-powered commands."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.domain.trading.models.value_objects import AICommandResponse


class AIModelPort(ABC):
    """Abstract AI model for processing natural language commands."""

    @abstractmethod
    async def process_command(
        self, prompt: str, current_config: dict[str, Any]
    ) -> AICommandResponse:
        """Interpret a user command and return configuration updates."""
        ...
