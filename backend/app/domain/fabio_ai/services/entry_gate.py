"""Pure quant functions for Fabio Playbook entry gates.

DEPRECATED: This module is a backward-compatibility wrapper.
All functions have been extracted into focused sub-modules under
``app.domain.fabio_ai.services.entry_gates``:

- ``entry_gates.three_align``        — Three-Align Gate + helpers
- ``entry_gates.confirmation_bundle`` — Volume/Delta/Spread check + momentum fade
- ``entry_gates.signal_builder``      — SL/TP construction + aggressive prints
- ``entry_gates.grading``             — A/B/C setup grade scoring
- ``entry_gates.gate_runner``         — 12-gate pipeline + position sizing

New code should import from the sub-modules directly.  This wrapper will be
removed once all consumers migrate (tracked in MASTER_ARCHITECTURE_PLAN.md).

All functions remain stateless and side-effect-free.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Re-exports from extracted modules — every public name from the original
# entry_gate.py is still available here for backward compatibility.
# ---------------------------------------------------------------------------

from app.domain.fabio_ai.services.entry_gates.three_align import (
    min_candles_gate,
    full_body_close_gate,
    nearest_round_number,
    cluster_aggressive_prints,
    extract_bubble_levels_from_footprint,
    three_align_check,
)
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import (
    check_confirmation_bundle,
    check_momentum_fade,
    compute_atr,
)
from app.domain.fabio_ai.services.entry_gates.signal_builder import (
    build_entry_signal,
    sl_from_aggressive_print,
)
from app.domain.fabio_ai.services.entry_gates.grading import (
    compute_grade_score,
    check_vwap_bias,
    check_imbalance_alignment,
)
from app.domain.fabio_ai.services.entry_gates.gate_runner import (
    run_gate_pipeline,
    calculate_position_size,
)

# Re-export enums that were originally visible through this module
from app.domain.trading.models.enums import SetupType, SignalType, Source

__all__ = [
    # enums
    "SetupType",
    "SignalType",
    "Source",
    # three_align
    "min_candles_gate",
    "full_body_close_gate",
    "nearest_round_number",
    "cluster_aggressive_prints",
    "extract_bubble_levels_from_footprint",
    "three_align_check",
    # confirmation_bundle
    "check_confirmation_bundle",
    "check_momentum_fade",
    "compute_atr",
    # signal_builder
    "build_entry_signal",
    "sl_from_aggressive_print",
    # grading
    "compute_grade_score",
    "check_vwap_bias",
    "check_imbalance_alignment",
    # gate_runner
    "run_gate_pipeline",
    "calculate_position_size",
]
