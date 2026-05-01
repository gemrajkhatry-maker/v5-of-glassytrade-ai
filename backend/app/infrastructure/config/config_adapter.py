"""Infrastructure adapter for configuration - implements domain ports.

This module provides the concrete implementation of configuration ports
that loads from YAML and provides it to the domain layer via injection.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)


class GlobalsImpl:
    """Implementation of IGlobals that loads from YAML."""
    
    def __init__(self, globals_dict: dict[str, Any] | None = None):
        self._data = globals_dict or {}
    
    @property
    def lvn_threshold(self) -> float:
        return float(self._data.get("lvn_threshold", 0.15))
    
    @property
    def hvn_threshold(self) -> float:
        return float(self._data.get("hvn_threshold", 2.00))
    
    @property
    def value_area_pct(self) -> float:
        return float(self._data.get("value_area_pct", 0.70))
    
    @property
    def lvn_smoothing(self) -> int:
        return int(self._data.get("lvn_smoothing", 3))
    
    @property
    def lvn_min_persistence_bars(self) -> int:
        return int(self._data.get("lvn_min_persistence_bars", 1))
    
    @property
    def lvn_removal_threshold(self) -> float:
        return float(self._data.get("lvn_removal_threshold", 0.50))
    
    @property
    def cvd_slope_window(self) -> int:
        return int(self._data.get("cvd_slope_window", 20))
    
    @property
    def cvd_strong_slope(self) -> float:
        return float(self._data.get("cvd_strong_slope", 2.0))
    
    @property
    def balance_ratio_threshold(self) -> float:
        return float(self._data.get("balance_ratio_threshold", 0.55))
    
    @property
    def displacement_multiplier(self) -> float:
        return float(self._data.get("displacement_multiplier", 1.5))
    
    @property
    def risk_per_trade_pct(self) -> float:
        return float(self._data.get("risk_per_trade_pct", 0.005))
    
    @property
    def max_daily_loss_pct(self) -> float:
        return float(self._data.get("max_daily_loss_pct", 0.020))
    
    @property
    def max_consecutive_losses(self) -> int:
        return int(self._data.get("max_consecutive_losses", 3))
    
    @property
    def ib_minutes(self) -> int:
        return int(self._data.get("ib_minutes", 10))
    
    @property
    def displacement_lookback(self) -> int:
        return int(self._data.get("displacement_lookback", 15))


class SymbolConfigImpl(BaseModel):
    """Implementation of ISymbolConfig for a specific symbol."""
    
    tick_size: float = 0.05
    lot_size: int = 1
    aggression_persistence_bars: int = 3
    min_aggression_score: float = 2.0
    pyramid_aggression_score: float = 3.0
    
    class Config:
        frozen = True


def load_globals_from_yaml() -> dict[str, Any]:
    """Load globals section from config/base.yaml.
    
    Returns:
        Dictionary with globals configuration values.
    """
    try:
        config_dir = Path(__file__).resolve().parent.parent.parent.parent / "config"
        base_path = config_dir / "base.yaml"
        if base_path.exists():
            with open(base_path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("globals", {})
    except Exception as e:
        logger.debug("Could not load globals from base.yaml: %s", e)
    return {}


# Singleton instance for backward compatibility
_globals_instance: GlobalsImpl | None = None


def get_globals() -> GlobalsImpl:
    """Get the singleton GlobalsImpl instance."""
    global _globals_instance
    if _globals_instance is None:
        _globals_instance = GlobalsImpl(load_globals_from_yaml())
    return _globals_instance