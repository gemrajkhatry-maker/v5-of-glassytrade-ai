"""Test configuration."""

import sys
from pathlib import Path

# Add project root to path for brokers import
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
