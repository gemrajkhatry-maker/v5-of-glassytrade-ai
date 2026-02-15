import logging
from typing import Dict, Any
from app.infrastructure.adapters.llm_inference_adapter import LLMInferenceAdapter

logger = logging.getLogger(__name__)


class GenerativeAIService:
    """Fabio Logic LLM service — entry decisions ONLY.

    The instruction and prompt format are aligned exactly to the training
    data in ``training_data_fabio.jsonl``.  The model was trained on:
      - Instruction: "Analyze the trading scenario based on Fabio Valentini's
        methodology (Orderflow, Auction Market Theory)."
      - Input:  natural-language market scenario with VAH/VAL/POC/Delta
      - Output: structured "Market State / Logic / Trigger" block
    """

    # The EXACT instruction used during fine-tuning
    INSTRUCTION = (
        "Analyze the trading scenario based on Fabio Valentini's "
        "methodology (Orderflow, Auction Market Theory)."
    )

    def __init__(self):
        self.llm_adapter = LLMInferenceAdapter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_market(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze current market data for an *entry* decision.

        Returns
        -------
        dict with keys:
            direction : "LONG" | "SHORT" | "FLAT"
            rationale : full model output text
            raw_output, input_prompt, market_state, aggression
        """
        prompt_input = self._build_prompt(market_data)

        try:
            raw_response = self.llm_adapter.predict(self.INSTRUCTION, prompt_input)
            parsed = self._parse_response(raw_response)
            parsed["input_prompt"] = prompt_input
            parsed["market_state"] = market_data.get("market_state", "Unknown")
            parsed["aggression"] = market_data.get("aggression", "0.00")
            return parsed
        except Exception as e:
            logger.error(f"Error during AI analysis: {e}")
            return {"direction": "FLAT", "rationale": f"Error: {e}"}

    # ------------------------------------------------------------------
    # Prompt builder — mirrors training data format
    # ------------------------------------------------------------------

    def _build_prompt(self, data: Dict[str, Any]) -> str:
        """Convert structured market data into the natural-language format
        the model was fine-tuned on.

        Training examples look like:
          "New York Open. Price is testing Value Area Low (VAL) at 15050.
           Sellers are aggressive with -500 Delta but price is not moving
           down. Big buy orders are hitting the bid."
        """
        price = data.get("ltp", 0)
        vah = data.get("vah", 0)
        val = data.get("val", 0)
        poc = data.get("poc", 0)
        delta = data.get("delta", 0)
        market_state = data.get("market_state", "Balanced")
        aggression = data.get("aggression", "")

        parts: list[str] = []

        # Market regime
        if "Balanced" in str(market_state):
            parts.append("Market is inside the Value Area (Balance).")
        else:
            parts.append("Market is trending outside the Value Area (Imbalanced).")

        # Price relative to VA — the core of every training example
        parts.append(
            f"Current price is {price:.2f}. "
            f"Value Area High (VAH) at {vah:.2f}. "
            f"Value Area Low (VAL) at {val:.2f}. "
            f"POC at {poc:.2f}."
        )

        # Delta — present in every training example
        delta_int = int(round(delta))
        if delta_int > 0:
            parts.append(
                f"Buyers are aggressive with +{delta_int} Delta."
            )
        elif delta_int < 0:
            parts.append(
                f"Sellers are aggressive with {delta_int} Delta."
            )
        else:
            parts.append("Delta is neutral.")

        # Location context
        if val > 0 and price > 0:
            if price <= val * 1.001:
                parts.append(
                    "Price is testing Value Area Low (VAL). "
                    "Watching for absorption or breakdown."
                )
            elif price >= vah * 0.999:
                parts.append(
                    "Price is testing Value Area High (VAH). "
                    "Watching for breakout or failed auction."
                )
            elif poc > 0 and abs(price - poc) / poc < 0.002:
                parts.append("Price is at the Point of Control (POC).")

        # Aggression / orderflow colour
        if aggression:
            parts.append(f"Orderflow: {aggression}.")

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Response parser — matches training output patterns ONLY
    # ------------------------------------------------------------------

    def _parse_response(self, text: str) -> Dict[str, Any]:
        """Parse model output into a direction.

        Training outputs contain one of:
          Trigger: **Enter Long**
          Trigger: **Enter Short** / **Short**
          Trigger: **Long** / **Add to Longs**
          **Bank Profit** / **Walk away** / **Stay Flat**
        """
        direction = "FLAT"
        lower = text.lower()

        # --- LONG signals ---
        if any(kw in lower for kw in [
            "enter long", "**long**", "trigger: **long",
            "add to longs", "trigger: long",
        ]):
            direction = "LONG"
        # --- SHORT signals ---
        elif any(kw in lower for kw in [
            "enter short", "**short**", "trigger: **short",
            "trigger: short",
        ]):
            direction = "SHORT"
        # Everything else (bank profit, walk away, stay flat, etc.) → FLAT

        return {
            "direction": direction,
            "rationale": text,
            "raw_output": text,
        }
