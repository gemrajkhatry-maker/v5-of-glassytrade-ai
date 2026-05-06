"""Fabio AI entry-gates module set.

Pure, stateless quant primitives split into focused modules:
- three_align.py
- confirmation_bundle.py
- detectors.py
- grading.py
- signal_builder.py
- gate_runner.py
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
    check_vwap_bias,
    check_imbalance_alignment,
    compute_grade_score,
)
from app.domain.fabio_ai.services.entry_gates.gate_runner import (
    run_gate_pipeline,
    calculate_position_size,
)
from app.domain.fabio_ai.services.entry_gates.detectors import detect_momentum_fade

__all__ = [
    "min_candles_gate",
    "full_body_close_gate",
    "nearest_round_number",
    "cluster_aggressive_prints",
    "extract_bubble_levels_from_footprint",
    "three_align_check",
    "check_confirmation_bundle",
    "check_momentum_fade",
    "compute_atr",
    "build_entry_signal",
    "sl_from_aggressive_print",
    "check_vwap_bias",
    "check_imbalance_alignment",
    "compute_grade_score",
    "run_gate_pipeline",
    "calculate_position_size",
    "detect_momentum_fade",
]

