"""Tests for FeatureFlags — feature toggle system.

Behavior: FeatureFlags enables/disables features and defaults to disabled.
"""
from __future__ import annotations

import pytest

from app.core.feature_flags import FeatureFlags, Feature


class TestFeatureFlags:
    """Tests for FeatureFlags behavior through public interface."""

    def test_default_disabled(self):
        """Features should be disabled by default."""
        flags = FeatureFlags()
        
        assert not flags.is_enabled(Feature.TRADING_ENABLED)
        assert not flags.is_enabled(Feature.PAPER_TRADING)
        assert not flags.is_enabled(Feature.RISK_MANAGEMENT)
        assert not flags.is_enabled(Feature.AI_ANALYSIS)

    def test_enable_disable(self):
        """Should be able to enable and disable features."""
        flags = FeatureFlags()
        
        flags.enable(Feature.TRADING_ENABLED)
        assert flags.is_enabled(Feature.TRADING_ENABLED)
        
        flags.disable(Feature.TRADING_ENABLED)
        assert not flags.is_enabled(Feature.TRADING_ENABLED)

    def test_unknown_feature_returns_false(self):
        """Unknown features should return False (not raise error)."""
        flags = FeatureFlags()
        
        # Create a custom feature not in the enum
        class CustomFeature:
            pass
        
        # Should handle gracefully (type: ignore for test)
        assert flags.is_enabled(CustomFeature) is False  # type: ignore

    def test_multiple_features_independent(self):
        """Different features should be independent."""
        flags = FeatureFlags()
        
        flags.enable(Feature.TRADING_ENABLED)
        flags.enable(Feature.AI_ANALYSIS)
        
        assert flags.is_enabled(Feature.TRADING_ENABLED)
        assert flags.is_enabled(Feature.AI_ANALYSIS)
        assert not flags.is_enabled(Feature.PAPER_TRADING)

    def test_enable_twice_still_enabled(self):
        """Enabling an already-enabled feature should be idempotent."""
        flags = FeatureFlags()
        
        flags.enable(Feature.TRADING_ENABLED)
        flags.enable(Feature.TRADING_ENABLED)  # No error
        
        assert flags.is_enabled(Feature.TRADING_ENABLED)

    def test_disable_twice_still_disabled(self):
        """Disabling an already-disabled feature should be idempotent."""
        flags = FeatureFlags()
        
        flags.disable(Feature.TRADING_ENABLED)
        flags.disable(Feature.TRADING_ENABLED)  # No error
        
        assert not flags.is_enabled(Feature.TRADING_ENABLED)

    def test_feature_enum_values(self):
        """Feature enum should have expected string values."""
        assert Feature.TRADING_ENABLED == "trading_enabled"
        assert Feature.PAPER_TRADING == "paper_trading"
        assert Feature.RISK_MANAGEMENT == "risk_management"
        assert Feature.AI_ANALYSIS == "ai_analysis"

    def test_feature_is_string(self):
        """Feature enum should be string-based for serialization."""
        assert isinstance(Feature.TRADING_ENABLED, str)
        assert Feature.TRADING_ENABLED.value == "trading_enabled"
