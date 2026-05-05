"""Test configuration for pytest."""
import sys
from pathlib import Path

# Add backendv2 to path
backendv2_path = Path(__file__).parent.parent
sys.path.insert(0, str(backendv2_path))