"""Backward-compatibility shim for config.config.

Configuration is now ConsolidatedConfig in config/consolidated.py.
All new code should import directly from config.consolidated.
"""

from config.consolidated import ConsolidatedConfig as Configuration

__all__ = ["Configuration"]
