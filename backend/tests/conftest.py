"""Shared test fixtures and configuration.

This conftest.py provides:
1. Mock shared module for tests that import from shared
2. Common fixtures for all test modules
3. Test environment setup
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock
import os

# Ensure parent directory is on sys.path for 'shared' module
_parent_dir = os.path.join(os.path.dirname(__file__), "..", "..")
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Mock the shared module before any imports that depend on it
if "shared" not in sys.modules:
    _shared = MagicMock()
    _shared.conversion.to_float = lambda v: float(v) if v is not None else 0.0
    _shared.conversion.to_decimal = lambda v: v
    sys.modules["shared"] = _shared
    sys.modules["shared.conversion"] = _shared.conversion
    sys.modules["shared.config"] = MagicMock()
    sys.modules["shared.resilience"] = MagicMock()
    sys.modules["shared.entities"] = MagicMock()
    sys.modules["shared.error_handling"] = MagicMock()
    sys.modules["shared.session_context"] = MagicMock()
