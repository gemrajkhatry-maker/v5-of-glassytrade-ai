"""Unified configuration loading utilities.

Consolidates config loading logic previously duplicated across
config_adapter.py and settings.py.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

_ENV_ALIASES: dict[str, str] = {
    "dev": "development",
    "development": "development",
    "paper": "paper",
    "live": "live",
    "prod": "production",
    "production": "production",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read YAML file safely, returning empty dict on any error."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def resolve_environment() -> str:
    """Resolve environment from GLASSYTRADE_ENV, with aliases."""
    env = (
        str(os.getenv("GLASSYTRADE_ENV", "development"))
        .strip()
        .lower()
    )
    return _ENV_ALIASES.get(env, "development")


def load_settings_from_yaml(
    base_dir: Path | None = None,
    env: str | None = None,
) -> dict[str, Any]:
    """Load settings from base.yaml + environment-specific override.

    Args:
        base_dir: Directory containing base.yaml and environments/ subdir.
                  Defaults to project config/ directory.
        env: Environment name (development, paper, live).
             Defaults to GLASSYTRADE_ENV or 'development'.

    Returns:
        Merged dict of base + environment settings.
    """
    base_dir = base_dir or _DEFAULT_CONFIG_DIR
    env = env or resolve_environment()

    base = _read_yaml(base_dir / "base.yaml")
    override = _read_yaml(base_dir / "environments" / f"{env}.yaml")
    return _deep_merge(base, override)
