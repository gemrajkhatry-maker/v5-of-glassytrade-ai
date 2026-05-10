"""
brokersv2 - Institutional-grade trading platform.

A clean architecture implementation with:
- Hexagonal architecture
- Event-driven design
- Institutional OMS
- Robust market data pipeline
"""

# Auto-load .env from project root so credentials are available without
# the caller having to call load_dotenv() themselves.
import pathlib as _pathlib

try:
    from dotenv import load_dotenv as _load_dotenv
    _env_file = _pathlib.Path(__file__).resolve().parent.parent / ".env"
    if _env_file.exists():
        _load_dotenv(_env_file, override=False)  # override=False: real env vars take precedence
except ImportError:
    pass  # python-dotenv not installed; rely on env vars being set externally

__version__ = "2.0.0"