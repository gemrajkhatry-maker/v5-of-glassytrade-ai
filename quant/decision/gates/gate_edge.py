"""Gate 3 — Structural edge (Fabio Valentini AMT).

Single import surface for the canonical Gate 3 implementation, which lives in
``quant.decision.gates_edge`` (setup paths, guards and the 1-minute
full-body-candle acceptance rule).
"""

from __future__ import annotations

from quant.decision.gates_edge import gate_triple_a_edge

gate_edge = gate_triple_a_edge

__all__ = [
    "gate_edge",
    "gate_triple_a_edge",
]
