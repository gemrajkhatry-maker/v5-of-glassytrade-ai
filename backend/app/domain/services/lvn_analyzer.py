from typing import List, Dict, Any
from app.domain.ports.market_data import IMarketData
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.llm_inference import ILLMInference
from app.domain.ports.probability_inference import IProbabilityInference
from config.config import Configuration


class LVNAnalyzer:
    """Analyzes volume profile to detect Low Volume Nodes (LVNs) and High Volume Nodes (HVNs)."""

    def __init__(
        self,
        config: Configuration,
        market_data: IMarketData,
        storage: IStorage,
    ):
        self.config = config
        self.market_data = market_data
        self.storage = storage

    def detect_lvns_hvns(
        self,
        profile: Dict[str, Any],
        threshold: float = 0.05,
    ) -> tuple[List[float], List[float]]:
        """Detect LVNs and HVNs from volume profile histogram."""
        lvns = []
        hvns = []

        if not profile or not profile.get("histogram"):
            return lvns, hvns

        histogram = profile["histogram"]
        total_volume = profile["total_volume"]

        # Calculate average volume per bucket
        avg_bucket_volume = total_volume / len(histogram)

        # Find LVNs (significantly below average)
        for i, volume in enumerate(histogram):
            if volume < avg_bucket_volume * (1 - threshold):
                price = (
                    profile["min_price"]
                    + i * profile["bucket_size"]
                    + profile["bucket_size"] / 2
                )
                lvns.append(price)

        # Find HVNs (significantly above average)
        for i, volume in enumerate(histogram):
            if volume > avg_bucket_volume * (1 + threshold):
                price = (
                    profile["min_price"]
                    + i * profile["bucket_size"]
                    + profile["bucket_size"] / 2
                )
                hvns.append(price)

        return lvns, hvns
