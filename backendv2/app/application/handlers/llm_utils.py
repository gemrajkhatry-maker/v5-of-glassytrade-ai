"""LLM entry utilities used by application handlers.

Contains helper functions for prompt construction and response sanitation.
"""

from __future__ import annotations

import re
from datetime import datetime

_UNCLOSED_JSON_RE = re.compile(r"\{[^}]{0,100}$")
_ORPHANED_BRACE_RE = re.compile(r"\}[^{]{0,50}")
_TRAILING_JSON_RE = re.compile(r'[{}\[\]"]\s*$')
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_rationale(raw_rationale: str, direction: str) -> str:
    """Sanitize LLM rationale to remove malformed JSON fragments."""
    if not raw_rationale:
        return f"No rationale provided for {direction} entry."
    rationale = raw_rationale.strip()
    rationale = _UNCLOSED_JSON_RE.sub("", rationale)
    rationale = _ORPHANED_BRACE_RE.sub("", rationale)
    rationale = _TRAILING_JSON_RE.sub("", rationale)
    rationale = _WHITESPACE_RE.sub(" ", rationale)
    return rationale.strip() or f"No rationale provided for {direction} entry."


def build_strategy_hint(amt_result, session_info: dict, symbol: str, session) -> str:
    """Build strategy hint from AMT result and session context."""
    parts: list[str] = []
    regime = getattr(amt_result, "market_state", "BALANCED")
    if regime == "IMBALANCED":
        parts.append("Regime: IMBALANCED - favor trend continuation")
    else:
        parts.append("Regime: BALANCED - favor mean reversion")
    parts.append(f"Session: {session_info.get('session_name', 'UNKNOWN')}")
    fav = getattr(session, "favor_strategy", None) if session else None
    if fav:
        parts.append(f"Favor: {fav}")
    return " | ".join(parts)


def build_profile_description(amt_result) -> str:
    """Build profile description from shape."""
    profile_shape = getattr(amt_result, "profile_shape", "D")
    shapes = {
        "P": "P-profile: Distribution at highs (sellers active)",
        "B": "B-profile: Accumulation at lows (buyers active)",
        "D": "D-profile: Balanced session",
        "N": "N-profile: Normal distribution",
    }
    return shapes.get(profile_shape, f"Profile: {profile_shape}")


def build_volume_bubble_summary(amt_result, tick) -> str:
    bubbles = getattr(amt_result, "aggressive_prints", [])
    if not bubbles:
        return "No aggressive prints detected."
    total_vol = sum(getattr(b, "volume", 0) for b in bubbles[-5:])
    return f"Recent aggressive prints: {len(bubbles)} events, {total_vol} contracts"


def get_amt_time_window(ist_now: datetime) -> dict[str, str]:
    hour = ist_now.hour
    if 9 <= hour < 12:
        return {"label": "MORNING", "window": "first_half"}
    if 12 <= hour < 15:
        return {"label": "MIDDAY", "window": "second_half"}
    if 15 <= hour < 18:
        return {"label": "AFTERNOON", "window": "close"}
    return {"label": "CLOSE", "window": "eod"}


def build_imbalance_summary(session) -> str:
    if not session:
        return ""
    gap = getattr(session, "gap_type", "")
    bias = getattr(session, "opening_bias", "")
    parts: list[str] = []
    if gap:
        parts.append(f"Gap: {gap}")
    if bias and bias not in ("NEUTRAL", "IN_BALANCE"):
        parts.append(f"Bias: {bias}")
    return " | ".join(parts)


def compute_journal_attribution(agent: str, direction: str) -> str:
    parts = [agent.upper()]
    if direction == "LONG":
        parts.append("BULL")
    elif direction == "SHORT":
        parts.append("BEAR")
    else:
        parts.append("FLAT")
    return "|".join(parts)


def is_extreme_volatility(amt_result) -> bool:
    atr5 = float(getattr(amt_result, "atr_5", 0))
    atr20 = float(getattr(amt_result, "atr_20", 0))
    return atr20 > 0 and (atr5 / atr20) > 3.0
