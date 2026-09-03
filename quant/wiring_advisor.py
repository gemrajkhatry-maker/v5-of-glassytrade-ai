"""Wiring advisor factory — builds the LLM market-reasoning advisor.

Constructs an ``LLMAdvisor`` for LIVE/Paper trading from the ``MLX_*`` env
vars. When a real MLX model is configured it is used for deep reasoning
(lazy-loaded in the advisor's worker thread); otherwise the advisor degrades
to the deterministic rule-based narrative. The advisor is advisory-only: it
never blocks ticks and never changes the deterministic 4-gate decision.

The _ADVISOR_FACTORY seam is preserved for tests that inject fake advisors.
"""

from __future__ import annotations

import logging

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.llm.advisor import LLMAdvisor

logger = logging.getLogger(__name__)

# Repo root (this file lives in quant/). Used to resolve relative MLX_* paths
# regardless of the process CWD — start.sh launches the backend from backend/,
# while .env ships repo-root-relative model paths.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Seam for alternative wirings / tests: when set, called as factory(emit_fn)
# instead of constructing the env-driven LLMAdvisor.
_ADVISOR_FACTORY = None


def _resolve_model_path(raw: str | None) -> str | None:
    """Resolve an MLX_* env value to an existing path, or None.

    Accepts absolute paths, CWD-relative paths, and repo-root-relative paths.
    Returns None when the value is empty or points nowhere, which makes the
    advisor fall back to its rule-based narrative.
    """
    if not raw:
        return None
    p = Path(raw)
    if p.exists():
        return str(p)
    if not p.is_absolute():
        candidate = _REPO_ROOT / raw
        if candidate.exists():
            return str(candidate)
    # Support HuggingFace model repo IDs (e.g. keXjos/Qwen3.8-9B-mlx-4Bit)
    if "/" in raw and not raw.startswith("."):
        return raw
    return None


def build_live_advisor(emit_fn) -> "LLMAdvisor | None":
    """Build an LLMAdvisor from MLX_* env vars for LIVE/Paper trading.

    Returns None when LLM_ADVISOR_ENABLED is false/0 or when disabled,
    completely bypassing model loading and background worker threads.
    """
    if _ADVISOR_FACTORY is not None:
        return _ADVISOR_FACTORY(emit_fn)

    # Check if advisor is explicitly disabled
    enabled_val = os.getenv("LLM_ADVISOR_ENABLED", "false").strip().lower()
    if enabled_val in ("0", "false", "no", "disable", "disabled"):
        logger.info("LLM advisor is DISABLED (LLM_ADVISOR_ENABLED=%s)", enabled_val)
        return None

    try:
        from quant.llm.advisor import LLMAdvisor

        m_path = _resolve_model_path(os.getenv("MLX_MODEL_PATH"))
        a_path = _resolve_model_path(os.getenv("MLX_ADAPTER_PATH"))
        if m_path:
            logger.info("LLM advisor using MLX model: %s", m_path)
        else:
            logger.info("LLM advisor in rule-based mode (no MLX model resolved)")
        return LLMAdvisor(
            emit_fn=emit_fn,
            model_path=m_path,
            adapter_path=a_path,
        )
    except Exception:
        logger.exception("build_live_advisor failed — continuing without advisor")
        return None
