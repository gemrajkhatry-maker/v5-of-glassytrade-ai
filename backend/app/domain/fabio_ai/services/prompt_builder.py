"""Re-export shim — moved to quant/inference/prompt_builder.py. Delete in Phase 3."""
from quant.inference.prompt_builder import *  # noqa: F401,F403
from quant.inference.prompt_builder import (  # noqa: F401
    _build_narrative_session_context,
    _build_narrative_market_state,
    _build_narrative_order_flow,
    _build_core_amt_narrative,
)
