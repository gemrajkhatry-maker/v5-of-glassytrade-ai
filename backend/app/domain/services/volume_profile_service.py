from typing import List, Dict, Any
from app.domain.ports.market_data import IMarketData
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.llm_inference import ILLMInference
from app.domain.ports.probability_inference import IProbabilityInference
from config.config import Configuration


class VolumeProfileService:
    """Service for computing and managing volume profiles."""

    def __init__(
        self,
        config: Configuration,
        market_data: IMarketData,
        storage: IStorage,
    ):
        self.config = config
        self.market_data = market_data
        self.storage = storage

    def compute_profile(
        self,
        candles: List[Dict[str, Any]],
        session: str = "RTH",
    ) -> Dict[str, Any]:
        """Compute volume profile from candles."""
        if not candles:
            return {}

        # Determine optimal bucket count
        prices = [c["close"] for c in candles]
        if not prices:
            return {}

        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price

        # Use 200 buckets as default
        num_buckets = 200

        # Create histogram
        histogram = [0.0] * num_buckets
        bucket_size = price_range / num_buckets

        for candle in candles:
            # Distribute volume across candle range
            start_bucket = int((candle["low"] - min_price) / bucket_size)
            end_bucket = int((candle["high"] - min_price) / bucket_size)

            for i in range(start_bucket, end_bucket + 1):
                if 0 <= i < num_buckets:
                    histogram[i] += candle["volume"]

        # Find POC (Point of Control)
        max_volume = max(histogram) if histogram else 0
        poc_index = histogram.index(max_volume) if histogram else 0

        # Compute Value Area using Two-Row Pairs Method
        poc_price = min_price + (poc_index * bucket_size) + (bucket_size / 2)
        vah, val = self._compute_value_area(
            histogram, poc_index, min_price, bucket_size
        )

        return {
            "poc": poc_price,
            "vah": vah,
            "val": val,
            "total_volume": sum(histogram),
            "histogram": histogram,
            "min_price": min_price,
            "max_price": max_price,
            "bucket_size": bucket_size,
        }

    def _compute_value_area(
        self,
        histogram: List[float],
        poc_index: int,
        min_price: float,
        bucket_size: float,
    ) -> tuple[float, float]:
        """Compute Value Area High/Low using CME Two-Row Pairs Method."""
        if not histogram:
            return 0.0, 0.0

        total_volume = sum(histogram)
        target_volume = total_volume * 0.70  # 70% Value Area

        current_volume = histogram[poc_index]
        upper_idx = poc_index
        lower_idx = poc_index

        while current_volume < target_volume:
            # Sum next two rows above
            up_pair = 0.0
            up_count = 0
            for k in range(1, 3):
                if upper_idx + k < len(histogram):
                    up_pair += histogram[upper_idx + k]
                    up_count += 1

            # Sum next two rows below
            down_pair = 0.0
            down_count = 0
            for k in range(1, 3):
                if lower_idx - k >= 0:
                    down_pair += histogram[lower_idx - k]
                    down_count += 1

            can_go_up = up_count > 0
            can_go_down = down_count > 0

            if not can_go_up and not can_go_down:
                break

            if can_go_up and (not can_go_down or up_pair >= down_pair):
                # Expand upward
                for k in range(1, up_count + 1):
                    if upper_idx + k < len(histogram):
                        upper_idx += 1
                        current_volume += histogram[upper_idx]
            elif can_go_down:
                # Expand downward
                for k in range(1, down_count + 1):
                    if lower_idx - k >= 0:
                        lower_idx -= 1
                        current_volume += histogram[lower_idx]

        # Calculate VAH and VAL
        vah = min_price + (upper_idx * bucket_size) + (bucket_size / 2)
        val = min_price + (lower_idx * bucket_size) - (bucket_size / 2)

        return vah, val
