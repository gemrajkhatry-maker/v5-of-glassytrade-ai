"""Tests for SpreadNormalizer."""

from __future__ import annotations

import pytest

from app.domain.fabio_ai.services.spread_normalizer import SpreadNormalizer, SpreadNormalizationResult


def test_spread_normalizer_initial_state():
    """SpreadNormalizer starts with uninitialized EMA."""
    normalizer = SpreadNormalizer()
    assert normalizer._ema_spread == 0.0
    assert normalizer._initialized is False


def test_spread_normalizer_update_initializes():
    """First update initializes EMA."""
    normalizer = SpreadNormalizer()
    normalizer.update(0.5)
    assert normalizer._ema_spread == 0.5
    assert normalizer._initialized is True


def test_spread_normalizer_ema_updates():
    """EMA updates correctly with new spreads."""
    normalizer = SpreadNormalizer(ema_period=10)
    normalizer.update(0.5)
    normalizer.update(1.0)
    # EMA = alpha * new + (1-alpha) * old
    # alpha = 2/11 = 0.1818
    # EMA = 0.1818 * 1.0 + 0.8182 * 0.5 = 0.609
    assert normalizer._ema_spread > 0.5
    assert normalizer._ema_spread < 1.0


def test_spread_normalizer_normalize_before_update():
    """normalize() returns default when not initialized."""
    normalizer = SpreadNormalizer()
    result = normalizer.normalize(0.5)
    assert result.spread_ratio == 1.0
    assert result.is_wide is False
    assert result.penalty == 0.0


def test_spread_normalizer_is_wide_spread():
    """is_wide_spread detects wide spreads."""
    normalizer = SpreadNormalizer(ema_period=10)
    normalizer.update(0.5)
    # 1.0 / 0.5 = 2.0, > 1.5 threshold
    assert normalizer.is_wide_spread(1.0) is True
    # 0.5 / 0.5 = 1.0, < 1.5 threshold
    assert normalizer.is_wide_spread(0.5) is False


def test_spread_normalizer_get_penalty():
    """get_penalty returns correct penalty."""
    normalizer = SpreadNormalizer(ema_period=10)
    normalizer.update(0.5)
    # Wide spread penalty
    penalty = normalizer.get_penalty(1.0)
    assert penalty > 0.0
    assert penalty <= 0.5


def test_spread_normalizer_reset():
    """reset() clears state."""
    normalizer = SpreadNormalizer()
    normalizer.update(0.5)
    normalizer.reset()
    assert normalizer._initialized is False
    assert normalizer._ema_spread == 0.0


def test_spread_normalizer_ignores_zero_spread():
    """Zero or negative spreads are ignored."""
    normalizer = SpreadNormalizer()
    normalizer.update(0.0)  # Should be ignored
    assert normalizer._initialized is False
    normalizer.update(-0.5)  # Should be ignored
    assert normalizer._initialized is False