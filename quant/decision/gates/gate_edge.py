"""Gate 3 — Structural edge & 1-minute acceptance (Fabio Valentini AMT).

Validates structural patterns:
- Triple-A Breakout (Absorption -> Base -> Initiative Drive)
- LVN Sniper (Retest and spring off impulse profile Low Volume Node)
- Value Area Fade (Rejection probe outside Value Area targeting VPOC)
Enforces Fabio Valentini 1-Minute Full-Body Candle Close Rule:
Entries on wicks or mid-candle probes are strictly rejected.
"""

from __future__ import annotations

from quant.decision.gates_edge import (
    gate_triple_a_edge,
    _candle_acceptance,
    _check_guards,
    _check_setup_paths,
)

gate_edge = gate_triple_a_edge

__all__ = [
    "gate_edge",
    "gate_triple_a_edge",
]
