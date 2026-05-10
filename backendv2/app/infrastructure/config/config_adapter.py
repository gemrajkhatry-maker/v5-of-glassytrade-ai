"""Config adapter for backendv2 with YAML + env merge strategy."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .loader import _deep_merge, _read_yaml, resolve_environment, load_settings_from_yaml
from .settings import AppSettings, SettingsMode

logger = logging.getLogger(__name__)


_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def load_yaml(path: str | os.PathLike[str]) -> dict[str, Any]:
    return _read_yaml(Path(path))


def _safe_str(value: Any, fallback: str = "") -> str:
    return str(value or "").strip().lower()


def load_environment_config(environment: str | None = None) -> dict[str, Any]:
    return load_settings_from_yaml(_CONFIG_DIR, env=environment)


def load_strategy_config(name: str | None = None) -> dict[str, Any]:
    if not name:
        return {}
    return _read_yaml(_CONFIG_DIR / "strategies" / f"{name}.yaml")


def load_runtime_config(environment: str | None = None, strategy: str | None = None) -> dict[str, Any]:
    merged = load_environment_config(environment)
    strategy_data = load_strategy_config(strategy)
    if strategy_data:
        merged = _deep_merge(merged, strategy_data)
    return merged


def load_settings(
    environment: str | None = None,
    strategy: str | None = None,
) -> AppSettings:
    payload = load_runtime_config(environment=environment, strategy=strategy)
    payload["broker_mode"] = payload.get("broker_mode") or _safe_str(os.getenv("BROKER_MODE"), "paper")
    payload["environment"] = payload.get("environment") or resolve_environment()
    if payload.get("broker"):
        payload["broker_mode"] = payload["broker"].get("mode", payload["broker_mode"])
    return AppSettings.from_dict(payload)


class _default_globals_dict:
    lvn_threshold: float = 0.15
    hvn_threshold: float = 2.0
    value_area_pct: float = 0.70
    lvn_smoothing: int = 3
    lvn_min_persistence_bars: int = 3
    lvn_removal_threshold: float = 0.50
    cvd_slope_window: int = 20
    cvd_strong_slope: float = 2.0
    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.020
    max_consecutive_losses: int = 3
    ib_minutes: int = 10
    displacement_lookback: int = 15


@dataclass
class GlobalsImpl:
    """Global config facade used by domain services."""

    _data: dict[str, Any]

    @property
    def lvn_threshold(self) -> float:
        return float(self._data.get("lvn_threshold", _default_globals_dict.lvn_threshold))

    @property
    def hvn_threshold(self) -> float:
        return float(self._data.get("hvn_threshold", _default_globals_dict.hvn_threshold))

    @property
    def value_area_pct(self) -> float:
        return float(self._data.get("value_area_pct", _default_globals_dict.value_area_pct))

    @property
    def lvn_smoothing(self) -> int:
        return int(self._data.get("lvn_smoothing", _default_globals_dict.lvn_smoothing))

    @property
    def lvn_min_persistence_bars(self) -> int:
        return int(
            self._data.get(
                "lvn_min_persistence_bars", _default_globals_dict.lvn_min_persistence_bars
            )
        )

    @property
    def lvn_removal_threshold(self) -> float:
        return float(
            self._data.get(
                "lvn_removal_threshold", _default_globals_dict.lvn_removal_threshold
            )
        )

    @property
    def cvd_slope_window(self) -> int:
        return int(self._data.get("cvd_slope_window", _default_globals_dict.cvd_slope_window))

    @property
    def cvd_strong_slope(self) -> float:
        return float(self._data.get("cvd_strong_slope", _default_globals_dict.cvd_strong_slope))

    @property
    def risk_per_trade_pct(self) -> float:
        return float(self._data.get("risk_per_trade_pct", _default_globals_dict.risk_per_trade_pct))

    @property
    def max_daily_loss_pct(self) -> float:
        return float(self._data.get("max_daily_loss_pct", _default_globals_dict.max_daily_loss_pct))

    @property
    def max_consecutive_losses(self) -> int:
        return int(self._data.get("max_consecutive_losses", _default_globals_dict.max_consecutive_losses))

    @property
    def ib_minutes(self) -> int:
        return int(self._data.get("ib_minutes", _default_globals_dict.ib_minutes))

    @property
    def displacement_lookback(self) -> int:
        return int(self._data.get("displacement_lookback", _default_globals_dict.displacement_lookback))


_globals_singleton: GlobalsImpl | None = None


def get_globals() -> GlobalsImpl:
    global _globals_singleton
    if _globals_singleton is None:
        payload = load_environment_config()
        _globals_singleton = GlobalsImpl(payload.get("globals", {}))
    return _globals_singleton


def reset_config_cache() -> None:
    global _globals_singleton
    _globals_singleton = None

