"""State transition pure reducer facade (quant/transition.py).

Alias/bridge for quant/transitions.py to satisfy target v6.0 layout.
"""

from __future__ import annotations

from quant.transitions import apply_event

__all__ = [
    "apply_event",
]
