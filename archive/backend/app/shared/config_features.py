"""Feature flag registry for consistent feature management.

This module provides a centralized, type-safe way to access feature flags
throughout the application, eliminating scattered getattr() patterns.

Usage:
    from app.shared.config_features import Feature, feature_enabled, get_feature_flag
    
    if feature_enabled(settings, Feature.SHORT_SIGNALS):
        # ... short signal logic
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Feature(str, Enum):
    """Centralized feature flag definitions."""
    
    # Trading features
    SHORT_SIGNALS = "short_signals_enabled"
    ALLOW_SHORT = "allow_short"
    SCALP_ENGINE = "scalp_engine_enabled"
    SCALP_IB_BREAKOUT = "scalp_ib_breakout"
    RISK_TIER_ENGINE = "risk_tier_engine"
    
    # LLM features
    LLM_EXECUTION = "llm_execution_enabled"
    LLM_PRE_CANDLE_ADVISORY = "llm_pre_candle_advisory"
    LLM_POST_TRADE = "llm_post_trade"
    
    # Cost model features
    REALISTIC_COST_MODEL = "realistic_cost_model"


@dataclass(frozen=True)
class FeatureSpec:
    """Specification for a feature flag."""
    
    feature: Feature
    default: Any
    description: str
    requires_restart: bool = False


# Feature registry - single source of truth for all feature flags
FEATURE_REGISTRY: dict[Feature, FeatureSpec] = {
    Feature.SHORT_SIGNALS: FeatureSpec(
        feature=Feature.SHORT_SIGNALS,
        default=True,
        description="Enable short signal generation for options trading"
    ),
    Feature.ALLOW_SHORT: FeatureSpec(
        feature=Feature.ALLOW_SHORT,
        default=True,
        description="Allow short positions in trading"
    ),
    Feature.SCALP_ENGINE: FeatureSpec(
        feature=Feature.SCALP_ENGINE,
        default=False,
        description="Enable scalping engine for quick entries/exits"
    ),
    Feature.SCALP_IB_BREAKOUT: FeatureSpec(
        feature=Feature.SCALP_IB_BREAKOUT,
        default=False,
        description="Enable IB breakout scalping strategy"
    ),
    Feature.RISK_TIER_ENGINE: FeatureSpec(
        feature=Feature.RISK_TIER_ENGINE,
        default=True,
        description="Use risk tier engine for position sizing"
    ),
    Feature.LLM_EXECUTION: FeatureSpec(
        feature=Feature.LLM_EXECUTION,
        default=True,
        description="Enable LLM-driven execution (disable for safety)"
    ),
    Feature.LLM_PRE_CANDLE_ADVISORY: FeatureSpec(
        feature=Feature.LLM_PRE_CANDLE_ADVISORY,
        default=True,
        description="Run LLM pre-candle advisory for dashboard"
    ),
    Feature.LLM_POST_TRADE: FeatureSpec(
        feature=Feature.LLM_POST_TRADE,
        default=True,
        description="Run LLM post-trade analysis"
    ),
    Feature.REALISTIC_COST_MODEL: FeatureSpec(
        feature=Feature.REALISTIC_COST_MODEL,
        default=True,
        description="Use realistic transaction cost model"
    ),
}


def get_feature_value(settings: Any, feature: Feature) -> Any:
    """Get feature flag value from settings with proper default.
    
    Args:
        settings: Settings object (from app.config import settings)
        feature: Feature enum value
        
    Returns:
        Feature value from settings or default
    """
    spec = FEATURE_REGISTRY.get(feature)
    if not spec:
        raise ValueError(f"Unknown feature: {feature}")
    
    # Try to get from settings first
    value = getattr(settings, feature.value.upper(), None)
    if value is not None:
        return value
    
    # Fall back to default
    return spec.default


def feature_enabled(settings: Any, feature: Feature) -> bool:
    """Check if a feature is enabled.
    
    Args:
        settings: Settings object (from app.config import settings)
        feature: Feature enum value
        
    Returns:
        True if feature is enabled, False otherwise
    """
    return bool(get_feature_value(settings, feature))


def get_feature_spec(feature: Feature) -> FeatureSpec | None:
    """Get the specification for a feature.
    
    Args:
        feature: Feature enum value
        
    Returns:
        FeatureSpec if found, None otherwise
    """
    return FEATURE_REGISTRY.get(feature)