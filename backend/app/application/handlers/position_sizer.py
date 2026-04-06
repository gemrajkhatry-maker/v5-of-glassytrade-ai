"""PositionSizer — imported by LLMEntryHandler.

This module lives in the domain layer (app.domain.fabio_ai.services.position_sizer)
but is imported from the application layer for backwards compatibility.
"""

from app.domain.fabio_ai.services.position_sizer import PositionSizer  # noqa: F401

__all__ = ["PositionSizer"]
