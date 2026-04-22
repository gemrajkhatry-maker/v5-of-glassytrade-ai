from typing import List, Dict, Any, Optional
from app.domain.ports.market_data import IMarketData
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.llm_inference import ILLMInference
from app.domain.ports.probability_inference import IProbabilityInference
from config.config import Configuration


class AggressionScorer:
    """Scores aggression based on volume, delta, and order flow."""

    def __init__(
        self,
        config: Configuration,
        market_data: IMarketData,
        storage: IStorage,
    ):
        self.config = config
        self.market_data = market_data
        self.storage = storage

    def score(
        self,
        tick: Dict[str, Any],
        cvd_slope: float,
        order_book: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Score aggression level."""
        if not tick or "volume" not in tick or "delta" not in tick:
            return 0.0

        volume = float(tick["volume"])
        delta = float(tick["delta"])

        if volume <= 0:
            return 0.0

        # Calculate delta ratio
        delta_ratio = abs(delta) / volume

        # Base score from delta ratio
        score = min(delta_ratio / 0.15, 1.0)  # Normalize to 0-1

        # Adjust for CVD slope
        if cvd_slope > 0.5:
            score *= 1.2  # Increase score for strong buy pressure
        elif cvd_slope < -0.5:
            score *= 1.2  # Increase score for strong sell pressure

        # Check for order book imbalance
        if order_book:
            bid_size = order_book.get("bid_size", 0)
            ask_size = order_book.get("ask_size", 0)
            if bid_size > 0 and ask_size > 0:
                imbalance = abs(bid_size - ask_size) / max(bid_size, ask_size)
                if imbalance > 0.3:
                    score *= 1.1  # Increase score for significant imbalance

        return min(score, 1.0)  # Cap at 1.0
