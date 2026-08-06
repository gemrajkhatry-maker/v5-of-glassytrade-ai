"""IncrementalProfileFactory — Factory for creating per-underlying profile engines.

Factory pattern: creates IncrementalVolumeProfile instances with consistent
configuration. Each underlying gets its own isolated profile engine.

Usage:
    factory = IncrementalProfileFactory(bucket_size=0.05)
    engine = factory.create("CRUDEOIL")
    engine.update(candle)
"""

from __future__ import annotations

import logging

# TODO(migration): switch to quant.amt.analyzer once Track A5 lands
from app.domain.fabio_ai.services.amt_analyzer import IncrementalVolumeProfile

logger = logging.getLogger(__name__)


class IncrementalProfileFactory:
    """Creates IncrementalVolumeProfile instances with consistent bucket configuration.

    DI pattern: Factory -> Router -> DIContainer injection.
    All profiles share the same bucket_size but maintain independent state.

    Args:
        bucket_size: Price range per bucket. Computed from underlying tick_size.
        buckets: Number of histogram buckets (default 200).
    """

    def __init__(self, bucket_size: float = 0.05, buckets: int = 200) -> None:
        self._bucket_size = bucket_size
        self._buckets = buckets
        self._creation_count: int = 0

    def create(self, underlying: str) -> IncrementalVolumeProfile:
        """Create a new IncrementalVolumeProfile for the given underlying.

        Args:
            underlying: The underlying asset symbol (e.g., "CRUDEOIL", "GOLD").

        Returns:
            A fresh IncrementalVolumeProfile configured for this underlying.
        """
        self._creation_count += 1
        logger.info(
            "ProfileFactory: created engine #%d for underlying=%s (buckets=%d, bucket_size=%.4f)",
            self._creation_count,
            underlying,
            self._buckets,
            self._bucket_size,
        )
        return IncrementalVolumeProfile(buckets=self._buckets)

    @property
    def bucket_size(self) -> float:
        return self._bucket_size

    @property
    def buckets(self) -> int:
        return self._buckets

    @property
    def total_engines_created(self) -> int:
        return self._creation_count
