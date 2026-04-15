from typing import List, Dict, Any
from app.domain.ports.market_data import IMarketData
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.llm_inference import ILLMInference
from app.domain.ports.probability_inference import IProbabilityInference
from config.config import Configuration


class MarketStateClassifier:
    """Classifies market structure based on price action and volume."""

    def __init__(
        self,
        config: Configuration,
        market_data: IMarketData,
        storage: IStorage,
    ):
        self.config = config
        self.market_data = market_data
        self.storage = storage

    def classify(
        self,
        candles: List[Dict[str, Any]],
        volume_profile: Dict[str, Any],
        vwap_history: List[float],
    ) -> str:
        """Classify market state as BALANCED, IMBALANCED, TRENDING, etc."""
        if not candles or not volume_profile:
            return "UNKNOWN"

        # Get current price
        current_price = candles[-1]["close"]

        # Calculate value area boundaries
        vah = volume_profile.get("vah", 0)
        val = volume_profile.get("val", 0)

        # Check if price is inside value area
        inside_va = val <= current_price <= vah

        # Check for trend conditions
        if self._is_trending(candles, vwap_history):
            return "TRENDING"

        # Check for imbalance
        if not inside_va:
            return "IMBALANCED"

        # Check for balance
        if self._is_balanced(candles, volume_profile):
            return "BALANCED"

        return "UNKNOWN"

    def _is_trending(
        self, candles: List[Dict[str, Any]], vwap_history: List[float]
    ) -> bool:
        """Determine if market is in a trend."""
        if len(candles) < 20:
            return False

        # Simple trend detection: consecutive closes above/below VWAP
        recent = candles[-10:]
        above_vwap_count = sum(1 for c in recent if c["close"] > c.get("vwap", 0))
        below_vwap_count = sum(1 for c in recent if c["close"] < c.get("vwap", 0))

        return above_vwap_count >= 8 or below_vwap_count >= 8

    def _is_balanced(
        self, candles: List[Dict[str, Any]], profile: Dict[str, Any]
    ) -> bool:
        """Determine if market is balanced."""
        if not candles or not profile:
            return False

        current_price = candles[-1]["close"]
        vah = profile.get("vah", 0)
        val = profile.get("val", 0)

        # Price should be within value area
        if not (val <= current_price <= vah):
            return False

        # Check for balanced profile shape
        histogram = profile.get("histogram", [])
        if not histogram:
            return False

        # Price should be near POC
        poc = profile.get("poc", 0)
        if abs(current_price - poc) > (vah - val) * 0.25:
            return False

        return True
