"""Entry gates — pure, stateless quant functions for Fabio Playbook entry evaluation.

All functions are side-effect-free: receive data, return decisions.

Extraction from entry_gate.py (was 1,105 lines) into 5 focused modules:
- three_align.py       — Three-Align Gate helpers & main check
- confirmation_bundle.py — Volume/Delta/Spread confirmation + momentum fade
- signal_builder.py     — SL/TP construction & aggressive print clustering
- grading.py            — A/B/C setup grade scoring
- gate_runner.py        — 12-gate pipeline runner & position sizing

Moved to quant/decision/gates — delete in Phase 3.
"""

from quant.decision.gates.confirmation_bundle import *  # noqa: F401,F403
from quant.decision.gates.grading import *  # noqa: F401,F403
from quant.decision.gates.three_align import *  # noqa: F401,F403
from quant.decision.gates.signal_builder import *  # noqa: F401,F403
from quant.decision.gates.gate_runner import *  # noqa: F401,F403

