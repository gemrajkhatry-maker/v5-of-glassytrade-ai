"""LVNDetector — detect and maintain LVN/HVN list.

Single job: detect Low Volume Nodes and High Volume Nodes from volume profile,
track persistence across bars, compute strength scores.

Inputs: VolumeProfileSnapshot; SymbolConfig
Outputs: list[LVNLevel], list[HVNLevel]

LVN strength score formula:
    LVN_strength = 1 - H_smooth[i] / mean(H_smooth)
    Range: 0 (weakest — barely qualifies) → 1 (perfect — zero volume in bucket)

Detection strategy (percentile-based):
    LVN candidates = local minima whose smoothed volume falls in the bottom
    ``lvn_percentile`` (default 25th) of the distribution.
    HVN candidates = local maxima whose smoothed volume falls in the top
    ``hvn_percentile`` (default 75th, i.e. 100 - 25) of the distribution.
    After detection, nearby nodes within ``min_separation`` price distance are
    clustered and only the strongest node per cluster is kept.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from quant.contracts.value_objects import VolumeProfileLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LVNLevel:
    """A detected Low Volume Node."""

    price: float
    strength: float  # 0 (weakest) to 1 (strongest)
    bucket_index: int


@dataclass(frozen=True)
class HVNLevel:
    """A detected High Volume Node (support/resistance zone)."""

    price: float
    strength: float  # Normalized: H_smooth[i] / mean(H_smooth)
    bucket_index: int


def _smooth_array(data: list[float], window: int) -> list[float]:
    """Centered simple moving average smoothing."""
    if window <= 1 or len(data) < 3:
        return list(data)
    half = window // 2
    result = []
    for i in range(len(data)):
        start = max(0, i - half)
        end = min(len(data), i + half + 1)
        result.append(sum(data[start:end]) / (end - start))
    return result


def _percentile(values: list[float], pct: float) -> float:
    """Return the ``pct``-th percentile (0–100) of *values* using linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (n - 1)
    lo = int(rank)
    hi = lo + 1
    if hi >= n:
        return sorted_vals[-1]
    frac = rank - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


_NodeT = TypeVar("_NodeT", LVNLevel, HVNLevel)


def _cluster_nodes(
    nodes: list,
    min_separation: float,
    *,
    keep_highest: bool,
) -> list:
    """Merge nodes that are closer than ``min_separation`` in price.

    Within each cluster keep only:
    - the node with the *highest* volume strength (for HVNs, keep_highest=True)
    - the node with the *lowest* volume strength  (for LVNs, keep_highest=False)

    Args:
        nodes: Sorted (by price) list of LVNLevel or HVNLevel.
        min_separation: Minimum price gap required between distinct nodes.
        keep_highest: True → keep max-strength node per cluster (HVN).
                      False → keep min-strength node per cluster (LVN —
                      lowest strength == lowest volume == best LVN).

    Returns:
        Filtered list with at most one representative per cluster.
    """
    if not nodes:
        return []

    sorted_nodes = sorted(nodes, key=lambda n: n.price)
    clusters: list[list] = []
    current_cluster: list = [sorted_nodes[0]]

    for node in sorted_nodes[1:]:
        if node.price - current_cluster[-1].price < min_separation:
            current_cluster.append(node)
        else:
            clusters.append(current_cluster)
            current_cluster = [node]
    clusters.append(current_cluster)

    result = []
    for cluster in clusters:
        if keep_highest:
            result.append(max(cluster, key=lambda n: n.strength))
        else:
            result.append(min(cluster, key=lambda n: n.strength))

    return sorted(result, key=lambda n: n.price)


def find_lvns(
    profile: list[VolumeProfileLevel],
    lvn_threshold: float = 0.15,  # kept for API compatibility (unused)
    smoothing_window: int = 3,
    smooth_fn: Callable | None = None,
    *,
    lvn_percentile: float = 25.0,
    min_separation: float = 0.0,
) -> list[LVNLevel]:
    """Detect Low Volume Nodes using percentile-based thresholds.

    Candidate = bucket i where ALL:
      H_smooth[i] <= percentile(lvn_percentile) of the smoothed distribution
      H_smooth[i] < H_smooth[i-1]    (local minimum — lower than neighbor above)
      H_smooth[i] < H_smooth[i+1]    (local minimum — lower than neighbor below)

    After finding raw candidates, nearby nodes within ``min_separation`` price
    distance are clustered; only the weakest-volume node per cluster is kept.

    Args:
        profile: Volume profile buckets sorted by price.
        lvn_threshold: Legacy parameter — no longer used for filtering.
        smoothing_window: Width of centered SMA smoothing kernel.
        smooth_fn: Optional custom smoothing callable (raw, window) -> smoothed.
        lvn_percentile: Bottom N-th percentile cutoff (default 25).
        min_separation: Minimum price gap between distinct LVN nodes.  When
            0.0 (default) no clustering is applied.

    Returns:
        List of LVNLevel sorted by price.
    """
    if len(profile) < 3:
        return []

    raw = [p.volume for p in profile]
    sm = (
        smooth_fn(raw, smoothing_window)
        if smooth_fn
        else _smooth_array(raw, smoothing_window)
    )
    mean_vol = sum(sm) / len(sm) if sm else 0.0
    if mean_vol <= 0:
        return []

    pct_threshold = _percentile(sm, lvn_percentile)
    lvns: list[LVNLevel] = []

    for i in range(1, len(sm) - 1):
        if sm[i] < sm[i - 1] and sm[i] < sm[i + 1] and sm[i] <= pct_threshold:
            strength = 1.0 - (sm[i] / mean_vol)
            strength = max(0.0, min(1.0, strength))
            lvns.append(
                LVNLevel(
                    price=profile[i].price,
                    strength=strength,
                    bucket_index=i,
                )
            )

    if min_separation > 0 and len(lvns) > 1:
        lvns = _cluster_nodes(lvns, min_separation, keep_highest=False)

    return lvns


def find_hvns(
    profile: list[VolumeProfileLevel],
    hvn_threshold: float = 2.00,  # kept for API compatibility (unused)
    smoothing_window: int = 3,
    smooth_fn: Callable | None = None,
    *,
    hvn_percentile: float = 75.0,
    min_separation: float = 0.0,
) -> list[HVNLevel]:
    """Detect High Volume Nodes using percentile-based thresholds.

    HVN = local maximum whose smoothed volume >= percentile(hvn_percentile).
    HVN strength = H_smooth[i] / mean(H_smooth) (normalized).

    After finding raw candidates, nearby nodes within ``min_separation`` price
    distance are clustered; only the strongest-volume node per cluster is kept.

    Args:
        profile: Volume profile buckets sorted by price.
        hvn_threshold: Legacy parameter — no longer used for filtering.
        smoothing_window: Width of centered SMA smoothing kernel.
        smooth_fn: Optional custom smoothing callable (raw, window) -> smoothed.
        hvn_percentile: Top N-th percentile cutoff (default 75, i.e. top 25%).
        min_separation: Minimum price gap between distinct HVN nodes.  When
            0.0 (default) no clustering is applied.

    Returns:
        List of HVNLevel sorted by price.
    """
    if len(profile) < 3:
        return []

    raw = [p.volume for p in profile]
    sm = (
        smooth_fn(raw, smoothing_window)
        if smooth_fn
        else _smooth_array(raw, smoothing_window)
    )
    mean_vol = sum(sm) / len(sm) if sm else 0.0
    if mean_vol <= 0:
        return []

    pct_threshold = _percentile(sm, hvn_percentile)
    hvns: list[HVNLevel] = []

    for i in range(1, len(sm) - 1):
        if (
            sm[i] > sm[i - 1]
            and sm[i] > sm[i + 1]
            and sm[i] >= pct_threshold
        ):
            strength = sm[i] / mean_vol
            hvns.append(
                HVNLevel(
                    price=profile[i].price,
                    strength=strength,
                    bucket_index=i,
                )
            )

    if min_separation > 0 and len(hvns) > 1:
        hvns = _cluster_nodes(hvns, min_separation, keep_highest=True)

    return hvns


class LVNPersistenceTracker:
    """Tracks LVN persistence across bars to prevent appearing/disappearing.

    Anti-flicker rule: candidate must appear in N consecutive bar updates
    (lvn_persistence_bars = 3) before being emitted as a confirmed LVN.

    Removal rule: remove confirmed LVN when
      H_smooth[i] > lvn_removal_threshold × mean(H_smooth)
    → Volume filled in the gap — LVN no longer valid
    """

    def __init__(
        self,
        min_bars: int = 3,
        lvn_threshold: float = 0.15,
        removal_threshold: float = 0.50,
        smoothing_window: int = 3,
        smooth_fn: Callable | None = None,
    ) -> None:
        self._min_bars = min_bars
        self._lvn_threshold = lvn_threshold
        self._removal_threshold = removal_threshold
        self._smoothing_window = smoothing_window
        self._smooth_fn = smooth_fn
        # price -> (birth_bar_index, emitted)
        self._candidates: dict[float, tuple[int, bool]] = {}
        self._bar_index: int = 0
        self._emitted_lvns: dict[float, int] = {}

    def reset(self) -> None:
        """Reset at session boundary."""
        self._candidates.clear()
        self._emitted_lvns.clear()
        self._bar_index = 0

    def update(
        self,
        raw_lvns: list[float],
        profile: list[VolumeProfileLevel],
    ) -> list[float]:
        """Process new raw LVNs and return stable (persisted) LVNs.

        Args:
            raw_lvns: LVN prices detected this bar from find_lvns().
            profile: Current volume profile (for removal threshold check).

        Returns:
            List of stable LVN prices.
        """
        self._bar_index += 1
        tick_size = profile[1].price - profile[0].price if len(profile) > 1 else 1.0
        snap = tick_size * 2

        # 1. Update candidates: add new, refresh existing
        matched_raw: set[float] = set()

        for price in list(self._candidates.keys()):
            found_match = False
            for rlvn in raw_lvns:
                if abs(rlvn - price) < snap:
                    found_match = True
                    matched_raw.add(rlvn)
                    break
            if not found_match and price not in self._emitted_lvns:
                del self._candidates[price]

        # Add new candidates
        for rlvn in raw_lvns:
            if rlvn not in matched_raw:
                is_new = all(abs(rlvn - p) >= snap for p in self._candidates)
                if is_new:
                    self._candidates[rlvn] = (self._bar_index, False)

        # 2. Promote candidates that have persisted long enough
        for price, (birth, emitted) in list(self._candidates.items()):
            age = self._bar_index - birth + 1
            if not emitted and age >= self._min_bars:
                self._candidates[price] = (birth, True)
                self._emitted_lvns[price] = self._bar_index

        # 3. Check removal of emitted LVNs
        if profile:
            mean_vol = sum(p.volume for p in profile) / len(profile)
            removal_threshold = mean_vol * self._removal_threshold
            for price in list(self._emitted_lvns):
                nearest_idx = min(
                    range(len(profile)),
                    key=lambda i: abs(profile[i].price - price),
                )
                if profile[nearest_idx].volume > removal_threshold:
                    del self._emitted_lvns[price]
                    self._candidates.pop(price, None)

        # 4. Return all emitted LVNs sorted by price
        return sorted(self._emitted_lvns.keys())

    def get_confirmed_lvns_with_strength(
        self,
        profile: list[VolumeProfileLevel],
    ) -> list[LVNLevel]:
        """Get all confirmed LVNs with their current strength scores."""
        if not profile or not self._emitted_lvns:
            return []

        result = []
        raw = [p.volume for p in profile]
        sm = (
            self._smooth_fn(raw, self._smoothing_window)
            if self._smooth_fn
            else _smooth_array(raw, self._smoothing_window)
        )
        mean_vol = sum(sm) / len(sm) if sm else 0.0
        if mean_vol <= 0:
            return []

        for price in self._emitted_lvns:
            nearest_idx = min(
                range(len(profile)),
                key=lambda i: abs(profile[i].price - price),
            )
            strength = 1.0 - (sm[nearest_idx] / mean_vol)
            strength = max(0.0, min(1.0, strength))
            result.append(
                LVNLevel(
                    price=price,
                    strength=strength,
                    bucket_index=nearest_idx,
                )
            )

        return sorted(result, key=lambda x: x.price)
