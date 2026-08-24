"""Shared timezone constants.

All timezone-aware datetime operations should use constants from this module
rather than creating inline `timezone(timedelta(...))` objects.

This ensures consistency across the codebase and makes it trivial to adjust
for different market hours if the system is ever deployed to other regions.
"""

from __future__ import annotations

from datetime import timezone, timedelta

IST: timezone = timezone(timedelta(hours=5, minutes=30))
"""Indian Standard Time — used by all NSE/MCX/IST timestamps."""
