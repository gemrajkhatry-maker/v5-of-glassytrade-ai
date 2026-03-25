"""LVNDetector — detect and maintain LVN/HVN list.

Single job: detect Low Volume Nodes and High Volume Nodes from volume profile,
track persistence across bars, compute strength scores.

Inputs: VolumeProfileSnapshot; SymbolConfig
Outputs: list[LVNLevel], list[HVNLevel]

LVN strength score formula:
    LVN_strength = 1 - H_smooth[i] / mean(H_smooth)
    Range: 0 (weakest — barely qualifies) → 1 (perfect — zero volume in bucket)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from app.domain.trading.models.value_objects import VolumeProfileLevel

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


def find_lvns(
    profile: list[VolumeProfileLevel],
    lvn_threshold: float = 0.15,
    smoothing_window: int = 3,
    smooth_fn: Callable | None = None,
) -> list[LVNLevel]:
    """Detect Low Volume Nodes using smoothing + mean-threshold method.

    Candidate = bucket i where ALL:
      H_smooth[i] < lvn_threshold × mean(H_smooth)
      H_smooth[i] < H_smooth[i-1]    (local minimum — lower than neighbor above)
      H_smooth[i] < H_smooth[i+1]    (local minimum — lower than neighbor below)

    Returns LVNLevel with strength score computed per spec.
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

    threshold = mean_vol * lvn_threshold
    lvns: list[LVNLevel] = []

    for i in range(1, len(sm) - 1):
        if sm[i] < sm[i - 1] and sm[i] < sm[i + 1] and sm[i] <= threshold:
            strength = 1.0 - (sm[i] / mean_vol)
            strength = max(0.0, min(1.0, strength))
            lvns.append(
                LVNLevel(
                    price=profile[i].price,
                    strength=strength,
                    bucket_index=i,
                )
            )

    return lvns


def find_hvns(
    profile: list[VolumeProfileLevel],
    hvn_threshold: float = 2.00,
    smoothing_window: int = 3,
    smooth_fn: Callable | None = None,
) -> list[HVNLevel]:
    """Detect High Volume Nodes using smoothing + mean-threshold method.

    HVN = bucket i where H_smooth[i] > hvn_threshold × mean(H_smooth)
    HVN strength = H_smooth[i] / mean(H_smooth) (normalized)
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

    hvns: list[HVNLevel] = []

    for i in range(1, len(sm) - 1):
        if (
            sm[i] > sm[i - 1]
            and sm[i] > sm[i + 1]
            and sm[i] >= hvn_threshold * mean_vol
        ):
            strength = sm[i] / mean_vol
            hvns.append(
                HVNLevel(
                    price=profile[i].price,
                    strength=strength,
                    bucket_index=i,
                )
            )

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
        removal_threshold: float = 0.30,
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
