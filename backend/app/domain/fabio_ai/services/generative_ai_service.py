import hashlib
import logging
import re
from collections import OrderedDict
from typing import Dict, Any

from app.config import settings
from app.domain.ports.llm_inference import LLMInferencePort

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

    # The EXACT instruction used during fine-tuning (from config for consistency)
    INSTRUCTION = settings.LLM_INSTRUCTION

    _CACHE_SIZE = 8

    def __init__(self, llm_adapter: LLMInferencePort):
        self.llm_adapter = llm_adapter
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        """Check if the underlying LLM adapter is ready for inference."""
        return self.llm_adapter.is_ready()

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

        # Check cache (avoids redundant inference for identical market state)
        cache_key = hashlib.md5(prompt_input.encode()).hexdigest()
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        try:
            raw_response = self.llm_adapter.predict(self.INSTRUCTION, prompt_input)
            parsed = self._parse_response(raw_response)
            parsed["input_prompt"] = prompt_input
            parsed["market_state"] = market_data.get("market_state", "Unknown")
            parsed["aggression"] = market_data.get("aggression", "0.00")

            # Cache result
            self._cache[cache_key] = parsed
            if len(self._cache) > self._CACHE_SIZE:
                self._cache.popitem(last=False)

            return parsed
        except Exception as e:
            logger.error(f"Error during AI analysis: {e}")
            return {"direction": "FLAT", "rationale": f"Error: {e}"}

    # ------------------------------------------------------------------
    # Prompt builder — mirrors training data format
    # ------------------------------------------------------------------

    def _build_prompt(self, data: Dict[str, Any]) -> str:
        """Convert structured market data into the concise narrative format
        the model was fine-tuned on.

        Training examples are short narratives like:
          "VAL test at 14927. Aggressive selling with -1532 Delta.
           Footprint shows iceberg buyers. Price refuses to break lower."
          "At POC 3422, delta flipped from negative to +402. Buyers stepping in."
          "Market is rotational. We are at the top of the distribution (15120)."
        """
        price = data.get("ltp", 0)
        vah = data.get("vah", 0)
        val = data.get("val", 0)
        poc = data.get("poc", 0)
        delta = data.get("delta", 0)
        market_state = data.get("market_state", "Balanced")

        parts: list[str] = []
        delta_int = int(round(delta))

        # Location-based narrative (matches training data style)
        if val > 0 and price > 0:
            if price <= val * 1.002:
                if delta_int < 0:
                    parts.append(f"VAL test at {val:.0f}. Aggressive selling with {delta_int} Delta.")
                else:
                    parts.append(f"Price at VAL {val:.0f} with +{delta_int} Delta. Buyers defending.")
            elif price >= vah * 0.998:
                if delta_int > 0:
                    parts.append(f"Price broke above Value Area High {vah:.0f} with strong +{delta_int} Delta.")
                else:
                    parts.append(f"Failed breakout above {vah:.0f}. Delta turned to {delta_int}.")
            elif poc > 0 and abs(price - poc) / poc < 0.003:
                if delta_int > 0:
                    parts.append(f"At POC {poc:.0f}, delta is +{delta_int}. Buyers stepping in.")
                elif delta_int < 0:
                    parts.append(f"Price at POC {poc:.0f} with aggressive sellers. Delta {delta_int}.")
                else:
                    parts.append(f"Price at POC {poc:.0f}. Delta is neutral.")
            else:
                if "Balanced" in str(market_state):
                    parts.append(f"Market is rotational. Price at {price:.0f}.")
                else:
                    parts.append(f"Price at {price:.0f}. Market trending outside value area.")
                if delta_int > 0:
                    parts.append(f"Aggressive buyers with +{delta_int} Delta.")
                elif delta_int < 0:
                    parts.append(f"Aggressive sellers pushing. Delta {delta_int}.")
        else:
            parts.append(f"Price at {price:.0f}. Delta {delta_int:+d}.")

        # Profile shape (brief, matches training style)
        profile_shape = data.get("profile_shape", "")
        if profile_shape and "P-Shape" in profile_shape:
            parts.append("A 'P-Shape' profile is forming. Short covering in progress.")
        elif profile_shape and "b-Shape" in profile_shape:
            parts.append("A 'b-Shape' profile is forming. Long liquidation visible.")

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Response parser — two-stage extraction from model output
    # ------------------------------------------------------------------

    # Regex to extract the Trigger: line content
    _RE_TRIGGER = re.compile(r'trigger:\s*(.+?)(?:\.\s|$)', re.IGNORECASE)
    # Regex to extract the Logic: line content
    _RE_LOGIC = re.compile(r'logic:\s*(.+?)(?:\.\s|trigger)', re.IGNORECASE)

    # LONG keywords found in Trigger content (from vocabulary mapping)
    _TRIGGER_LONG = [
        "enter long", "long with size", "long on pullback", "long on any dip",
        "long on re-entry", "long into", "add to longs", "re-enter long",
        "long with target", "long with full", "long hold", "buy on dip",
    ]
    # SHORT keywords found in Trigger content
    _TRIGGER_SHORT = [
        "enter short", "short on confirmation", "short with target",
        "short or", "short with", "short on rotation", "short with size",
        "buyers exhausted", "buyers are trapped", "failed breakout",
    ]
    # FLAT keywords (explicit no-trade)
    _FLAT_KEYWORDS = [
        "walk away", "stay flat", "bank profit", "stop trading",
        "reduce size", "take profit", "exit long", "rebalance",
        "risk management", "discipline", "we are done",
        "no short", "no long", "no trade", "no clear",
    ]
    # High confidence indicators
    _HIGH_CONFIDENCE = ["with size", "squeeze", "asymmetrical", "full allocation", "full market protection"]
    # Low confidence indicators
    _LOW_CONFIDENCE = ["watching", "wait for", "wait for break", "wait for passive"]

    def _parse_response(self, text: str) -> Dict[str, Any]:
        """Parse model output into a direction using two-stage extraction.

        Stage 1: Extract Trigger: line and match directional keywords.
        Stage 2: Fall back to Logic: line for setup-based direction.
        Stage 3: Broad keyword scan as last resort.
        """
        lower = text.lower()
        direction = None
        confidence = "Medium"

        # --- Stage 1: Trigger line extraction ---
        trigger_match = self._RE_TRIGGER.search(lower)
        if trigger_match:
            trigger = trigger_match.group(1).strip()
            direction = self._match_direction_in_text(trigger)
            if direction:
                confidence = self._extract_confidence(trigger)

        # --- Stage 2: Logic line fallback ---
        if direction is None:
            logic_match = self._RE_LOGIC.search(lower)
            if logic_match:
                logic = logic_match.group(1).strip()
                if any(kw in logic for kw in ["aaa setup", "momentum", "buy on dip", "short covering"]):
                    direction = "LONG"
                elif any(kw in logic for kw in ["breakout failed", "buyers exhausted", "buyers are trapped"]):
                    direction = "SHORT"

        # --- Stage 3: Broad keyword scan ---
        if direction is None:
            direction = self._match_direction_in_text(lower)

        # --- Explicit FLAT detection ---
        if direction is None:
            if any(kw in lower for kw in self._FLAT_KEYWORDS):
                direction = "FLAT"

        # --- Default to FLAT with warning ---
        if direction is None:
            direction = "FLAT"
            if not any(kw in lower for kw in self._FLAT_KEYWORDS):
                logger.warning("Unparsed model output (defaulting FLAT): %s", text[:200])

        return {
            "direction": direction,
            "rationale": text,
            "raw_output": text,
            "confidence": confidence,
        }

    def _match_direction_in_text(self, text: str) -> str | None:
        """Match directional keywords in text, checking SHORT before LONG
        to avoid false positives from 'short covering' → LONG patterns."""
        # Check SHORT first (more specific patterns)
        for kw in self._TRIGGER_SHORT:
            if kw in text:
                return "SHORT"
        # Check LONG
        for kw in self._TRIGGER_LONG:
            if kw in text:
                return "LONG"
        # Fallback: standalone word match via regex
        if re.search(r'\*\*long\*\*', text):
            return "LONG"
        if re.search(r'\*\*short\*\*', text):
            return "SHORT"
        return None

    def _extract_confidence(self, trigger_text: str) -> str:
        """Extract confidence level from trigger content."""
        if any(kw in trigger_text for kw in self._HIGH_CONFIDENCE):
            return "High"
        if any(kw in trigger_text for kw in self._LOW_CONFIDENCE):
            return "Low"
        return "Medium"
