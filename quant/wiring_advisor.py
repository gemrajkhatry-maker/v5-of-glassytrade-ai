"""Wiring advisor factory — no-op after LLM layer removal.

The LLM layer (quant.llm.*) was deleted in Phase 4 of the money-path
wiring. The advisor parameter on QuantEngine remains for API compatibility
but always receives None in production.

The _ADVISOR_FACTORY seam is preserved for tests that inject fake advisors.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Seam for tests: when set, called as factory(emit_fn) instead of returning None.
_ADVISOR_FACTORY = None


def build_live_advisor(emit_fn) -> None:
    """No-op: LLM layer has been removed. Always returns None.

    Preserves _ADVISOR_FACTORY seam so tests can inject fake advisors.
    """
    if _ADVISOR_FACTORY is not None:
        return _ADVISOR_FACTORY(emit_fn)
    return None
