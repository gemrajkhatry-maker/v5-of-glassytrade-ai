"""FeatureFlags — feature toggle system for trading system.

Extracted from core_components.py to enable dependency injection and testing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Feature(str, Enum):
    """Feature flags for trading system capabilities."""
    TRADING_ENABLED = "trading_enabled"
    PAPER_TRADING = "paper_trading"
    RISK_MANAGEMENT = "risk_management"
    AI_ANALYSIS = "ai_analysis"


@dataclass
class FeatureFlags:
    """Feature flag manager for enabling/disabling system capabilities.
    
    Thread-unsafe by design (assumes single-threaded access or external sync).
    """
    features: dict[Feature, bool] = field(default_factory=dict)
    
    def is_enabled(self, feature: Feature) -> bool:
        """Check if a feature is enabled.
        
        Args:
            feature: Feature to check
            
        Returns:
            True if enabled, False otherwise (default)
        """
        return self.features.get(feature, False)
    
    def enable(self, feature: Feature) -> None:
        """Enable a feature."""
        self.features[feature] = True
    
    def disable(self, feature: Feature) -> None:
        """Disable a feature."""
        self.features[feature] = False
