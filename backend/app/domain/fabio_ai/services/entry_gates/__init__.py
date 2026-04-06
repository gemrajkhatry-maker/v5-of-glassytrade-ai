"""Entry gates — pure, stateless quant functions for Fabio Playbook entry evaluation.

All functions are side-effect-free: receive data, return decisions.

Extraction from entry_gate.py (was 1,105 lines) into 5 focused modules:
- three_align.py       — Three-Align Gate helpers & main check
- confirmation_bundle.py — Volume/Delta/Spread confirmation + momentum fade
- signal_builder.py     — SL/TP construction & aggressive print clustering
- grading.py            — A/B/C setup grade scoring
- gate_runner.py        — 12-gate pipeline runner & position sizing
"""

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

__all__ = [
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
