"""LLM context building - extracted from llm_entry_handler.py.

Builds market context and prompt data for LLM inference.
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.trading.models.enums import SignalType
from app.shared.parsing import resolve_session_market

logger = logging.getLogger(__name__)


def build_session_phase_block_result(session_info: dict, symbol: str, market_state_str: str, amt_result: Any, tick: Any) -> dict:
    """Build session phase block result for LLM gates."""
    return {
        "symbol": symbol,
        "market_state": market_state_str,
        "session_name": session_info.get("session_name", "UNKNOWN"),
        "allow_entry": True,  # Default to allow
    }


def build_strategy_hint(amt_result: Any, session_info: dict, symbol: str, session: Any = None) -> str:
    """Build strategy hint from AMT result and session info."""
    parts = []
    
    regime = getattr(amt_result, 'market_state', 'BALANCED')
    if regime == 'IMBALANCED':
        parts.append("Regime: IMBALANCED - favor trend continuation")
    else:
        parts.append("Regime: BALANCED - favor mean reversion")
    
    session_name = session_info.get('session_name', 'UNKNOWN')
    parts.append(f"Session: {session_name}")
    
    if session:
        fav = getattr(session, 'favor_strategy', None)
        if fav:
            parts.append(f"Favor: {fav}")
    
    return " | ".join(parts)


def build_profile_description(amt_result: Any) -> str:
    """Build volume profile description."""
    profile_shape = getattr(amt_result, 'profile_shape', 'D')
    shapes = {
        'P': 'P-profile: Distribution at highs (sellers active)',
        'b': 'b-profile: Accumulation at lows (buyers active)',
        'D': 'D-profile: Balanced session',
        'N': 'N-profile: Normal distribution',
    }
    return shapes.get(profile_shape, f'Profile: {profile_shape}')


def build_volume_bubble_summary(amt_result: Any, tick: Any) -> str:
    """Build volume bubble summary from tick data."""
    bubbles = getattr(amt_result, 'aggressive_prints', [])
    if not bubbles:
        return "No aggressive prints detected."
    
    total_vol = sum(getattr(b, 'volume', 0) for b in bubbles[-5:])
    return f"Recent aggressive prints: {len(bubbles)} events, {total_vol} contracts"


def get_amt_time_window(ist_now) -> dict:
    """Get AMT analysis time window."""
    hour = ist_now.hour
    if 9 <= hour < 12:
        return {'label': 'MORNING', 'window': 'first_half'}
    elif 12 <= hour < 15:
        return {'label': 'MIDDAY', 'window': 'second_half'}
    elif 15 <= hour < 18:
        return {'label': 'AFTERNOON', 'window': 'close'}
    else:
        return {'label': 'CLOSE', 'window': 'eod'}


def build_imbalance_summary(session: Any) -> str:
    """Build imbalance summary from session context."""
    if not session:
        return ""
    
    gap = getattr(session, 'gap_type', '')
    bias = getattr(session, 'opening_bias', '')
    
    parts = []
    if gap:
        parts.append(f"Gap: {gap}")
    if bias and bias not in ('NEUTRAL', 'IN_BALANCE'):
        parts.append(f"Bias: {bias}")
    
    return " | ".join(parts)


def build_institutional_context(amt_result: Any) -> str:
    """Build institutional activity context."""
    delta = getattr(amt_result, 'delta', 0)
    cvd_slope = getattr(amt_result, 'cvd_slope', 0)
    
    parts = []
    if delta > 0:
        parts.append(f"Delta: +{delta:.0f} (buying pressure)")
    elif delta < 0:
        parts.append(f"Delta: {delta:.0f} (selling pressure)")
    
    if abs(cvd_slope) > 50:
        direction = "up" if cvd_slope > 0 else "down"
        parts.append(f"CVD slope: {cvd_slope:.0f} ({direction}ward momentum)")
    
    return " | ".join(parts)


def build_gate_context(amt_result: Any, tick: Any, session: Any, session_info: dict, agg_levels: list, fp_domain: Any) -> str:
    """Build gate context for LLM prompt."""
    context_parts = []
    
    # Add institutional context
    inst_ctx = build_institutional_context(amt_result)
    if inst_ctx:
        context_parts.append(inst_ctx)
    
    # Add volume profile
    profile = build_profile_description(amt_result)
    context_parts.append(profile)
    
    # Add volume bubbles
    bubbles = build_volume_bubble_summary(amt_result, tick)
    context_parts.append(bubbles)
    
    return " | ".join(context_parts)


def resolve_fallback_direction(session: Any, amt_result: Any) -> str:
    """Determine fallback direction when LLM is bypassed or times out."""
    _ml_dir = getattr(session, "_agent_decision", None)
    if _ml_dir and getattr(_ml_dir, "direction", "FLAT") != "FLAT":
        return _ml_dir.direction
    if getattr(amt_result, "signal", None):
        if amt_result.signal.type == SignalType.BUY:
            return "LONG"
        else:
            return "SHORT"
    return "FLAT"


def compute_journal_attribution(agent: Any, direction: str) -> str:
    """Determine attribution string for journaling (LLM vs Quant agreement)."""
    if not agent:
        return "llm_only"
    if agent.direction == direction and direction != "FLAT":
        return "llm_plus_quant_agree"
    if agent.direction not in ("", "FLAT", direction):
        return "llm_override_quant"
    return "llm_only"


def is_extreme_volatility(amt_result: Any) -> bool:
    """Check if market conditions warrant LLM bypass."""
    return (
        getattr(amt_result, "market_structure", "") == "EXPANSION"
        or getattr(amt_result, "price_velocity", 0) > 5.0
    )