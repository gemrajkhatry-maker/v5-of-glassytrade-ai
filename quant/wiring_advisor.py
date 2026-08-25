"""F4 (block0): the ONLY place that turns MLX env vars into an LLMAdvisor.

QuantEngine used to read MLX_MODEL_PATH / MLX_ADAPTER_PATH inside its
constructor — environment sniffing in a deterministic replay engine breaks
backtest/replay determinism and spawns a daemon thread per construction.
The engine now takes ``advisor: LLMAdvisor | None = None``; this factory is
wired ONLY on the live path (quant/multi_engine._spawn_engine).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.llm.advisor import LLMAdvisor

logger = logging.getLogger(__name__)

# Seam for alternative wirings / tests: when set, called as factory(emit_fn)
# instead of constructing the env-driven LLMAdvisor. Production never sets it.
_ADVISOR_FACTORY = None


def build_live_advisor(emit_fn) -> "LLMAdvisor | None":
    """Build an LLMAdvisor from MLX_* env vars for LIVE trading.

    Returns a rule-based advisor (model_path=None) when the env vars are
    unset or their paths don't exist — identical to the previous in-constructor
    behaviour. Never raises: a missing/broken MLX install must not block
    engine startup.
    """
    if _ADVISOR_FACTORY is not None:
        return _ADVISOR_FACTORY(emit_fn)
    try:
        from quant.llm.advisor import LLMAdvisor

        m_path = os.getenv("MLX_MODEL_PATH")
        a_path = os.getenv("MLX_ADAPTER_PATH")
        return LLMAdvisor(
            emit_fn=emit_fn,
            model_path=m_path if (m_path and os.path.exists(m_path)) else None,
            adapter_path=a_path if (a_path and os.path.exists(a_path)) else None,
        )
    except Exception:
        logger.exception("build_live_advisor failed — continuing without advisor")
        return None
