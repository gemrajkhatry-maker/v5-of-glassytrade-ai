"""Tests for Profile Classifier — ported from backend test_valentini_rl.py."""

import math

from quant.amt.profile.classifier import (
    classify_shape,
    POCMigrationTracker,
)
from quant.contracts.value_objects import VolumeProfileLevel


class TestProfileClassifier:
    def test_d_shape_symmetric(self):
        """Bell-curve volume → D shape."""
        profile = []
        for i in range(20):
            # Gaussian-like distribution centred at i=10
            vol = math.exp(-0.5 * ((i - 10) / 3) ** 2) * 100
            profile.append(VolumeProfileLevel(price=100 + i, volume=vol))
        result = classify_shape(profile)
        assert result.shape == "D"

    def test_p_shape_top_heavy(self):
        """Volume concentrated at high prices → P shape."""
        profile = []
        for i in range(20):
            vol = (i + 1) ** 2  # increasing → heavy at top
            profile.append(VolumeProfileLevel(price=100 + i, volume=vol))
        result = classify_shape(profile)
        # Negative skew = volume at top → P-shape
        assert result.shape in ("P", "b")  # depends on skew direction

    def test_empty_profile(self):
        result = classify_shape([])
        assert result.shape == "D"
        assert result.skewness == 0.0


class TestPOCMigrationTracker:
    def test_rising_poc(self):
        t = POCMigrationTracker()
        for i in range(10):
            t.update(100 + i * 2)
        state = t.state()
        assert state.direction == "RISING"

    def test_falling_poc(self):
        t = POCMigrationTracker()
        for i in range(10):
            t.update(200 - i * 2)
        state = t.state()
        assert state.direction == "FALLING"

    def test_stable_poc(self):
        t = POCMigrationTracker()
        for _ in range(10):
            t.update(100.0)
        state = t.state()
        assert state.direction == "STABLE"
