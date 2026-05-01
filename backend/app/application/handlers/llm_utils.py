"""LLM entry utilities - extracted from llm_entry_handler.py.

Contains helper functions for building prompts and processing LLM responses.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

# Compiled regex patterns for _sanitize_rationale (avoid per-call compilation)
_UNCLOSED_JSON_RE = re.compile(r'\{[^}]{0,100}$')
_ORPHANED_BRACE_RE = re.compile(r'\}[^{]{0,50}')
_TRAILING_JSON_RE = re.compile(r'[\[{}\]"]\s*$')
_WHITESPACE_RE = re.compile(r'\s+')


def sanitize_rationale(raw_rationale: str, direction: str) -> str:
    """Sanitize LLM rationale to remove malformed JSON and ensure clean text."""
    if not raw_rationale:
        return f"No rationale provided for {direction} entry."
    
    rationale = raw_rationale.strip()
    
    # Remove unclosed JSON fragments
    rationale = _UNCLOSED_JSON_RE.sub('', rationale)
    rationale = _ORPHANED_BRACE_RE.sub('', rationale)
    rationale = _TRAILING_JSON_RE.sub('', rationale)
    
    # Normalize whitespace
    rationale = _WHITESPACE_RE.sub(' ', rationale)
    
    return rationale.strip() or f"No rationale provided for {direction} entry."


def build_strategy_hint(amt_result: dict, session_info: dict, symbol: str, session: Any) -> str:
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


def build_profile_description(amt_result: dict) -> str:
    """Build volume profile description."""
    profile_shape = getattr(amt_result, 'profile_shape', 'D')
    shapes = {
        'P': 'P-profile: Distribution at highs (sellers active)',
        'b': 'b-profile: Accumulation at lows (buyers active)',
        'D': 'D-profile: Balanced session',
        'N': 'N-profile: Normal distribution',
    }
    return shapes.get(profile_shape, f'Profile: {profile_shape}')


def build_volume_bubble_summary(amt_result: dict, tick: Any) -> str:
    """Build volume bubble summary from tick data."""
    bubbles = getattr(amt_result, 'aggressive_prints', [])
    if not bubbles:
        return "No aggressive prints detected."
    
    total_vol = sum(getattr(b, 'volume', 0) for b in bubbles[-5:])
    return f"Recent aggressive prints: {len(bubbles)} events, {total_vol} contracts"


def get_amt_time_window(ist_now: datetime) -> dict:
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


def compute_journal_attribution(agent: str, direction: str) -> str:
    """Compute journal attribution string."""
    parts = [agent.upper()]
    if direction == 'LONG':
        parts.append('BULL')
    elif direction == 'SHORT':
        parts.append('BEAR')
    else:
        parts.append('FLAT')
    return '|'.join(parts)


def is_extreme_volatility(amt_result: dict) -> bool:
    """Check for extreme volatility conditions."""
    atr5 = getattr(amt_result, 'atr_5', 0)
    atr20 = getattr(amt_result, 'atr_20', 0)
    
    if atr20 > 0 and atr5 / atr20 > 3.0:
        return True
    return False