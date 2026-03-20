"""Shared test fixtures and configuration.

This conftest.py provides:
1. Mock shared module for tests that import from shared
2. Common fixtures for all test modules
3. Test environment setup
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Mock the shared module before any imports that depend on it
# This fixes the pre-existing AMTAnalyzer import error
if 'shared' not in sys.modules:
    sys.modules['shared'] = MagicMock()
    sys.modules['shared.config'] = MagicMock()
    sys.modules['shared.config'].SharedSettings = MagicMock
    sys.modules['shared.resilience'] = MagicMock()
    sys.modules['shared.resilience'].PerEntityCircuitBreaker = MagicMock
    sys.modules['shared.entities'] = MagicMock()