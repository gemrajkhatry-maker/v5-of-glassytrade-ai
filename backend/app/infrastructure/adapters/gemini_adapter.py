"""Gemini AI adapter — implements AIModelPort using Google GenAI SDK.

Infrastructure adapter for processing natural language chart commands
through Google's Gemini API.
"""

from __future__ import annotations

import json
from typing import Any

from app.domain.trading.models.value_objects import AICommandResponse
from app.domain.ports.ai_model import AIModelPort


class GeminiAIAdapter(AIModelPort):
    """Google Gemini adapter for AI-powered chart commands."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def process_command(
        self, prompt: str, current_config: dict[str, Any]
    ) -> AICommandResponse:
        try:
            from google import genai

            client = genai.Client(api_key=self._api_key)

            system_instruction = f"""
You are an expert financial visualizer and 3D graphics controller.
Your goal is to interpret natural language commands to control a 3D candlestick chart application.

Current Chart Configuration:
{current_config}

The user can ask to:
1. Switch to live data for a crypto symbol (e.g., "Show me BTC", "ETH live").
   - Set 'dataSource' to 'BINANCE'.
   - Infer the symbol (e.g., "BTC" -> "BTCUSDT").
2. Change the timeframe/interval.
   - Valid: '1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w','1M'.
3. Simulate market trends.
   - Set 'dataSource' to 'SIMULATION'.
4. Change the visual theme.
5. Toggle predictions or volume profile.

Respond with JSON: {{"message": "...", "action": "UPDATE_CONFIG|GENERATE_DATA|RESET", "configUpdates": {{...}}}}
"""

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={"system_instruction": system_instruction},
            )

            text = response.text or ""
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]

            parsed = json.loads(text)
            return AICommandResponse(
                message=parsed.get("message", "Done"),
                action=parsed.get("action"),
                config_updates=parsed.get("configUpdates"),
            )

        except Exception as e:
            return AICommandResponse(
                message="Sorry, I had trouble processing that command. Please try again.",
                action="RESET",
            )
