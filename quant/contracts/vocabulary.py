"""Canonical domain vocabulary.

These mappings were re-derived at five to six sites each, and had already begun
to drift: the session-phase "opening" set omitted PRE_MARKET in one copy, and
the option-kind test was not gated on ``is_option_contract`` in another. One
owner, one meaning.
"""

from __future__ import annotations

from quant.contracts.instrument_registry import is_option_contract

# Absorption semantics (Fabio AMT): absorbed sellers are bullish, absorbed
# buyers are bearish.
_SELL_ABSORBED = ("SELL_ABSORBED", "SELL")
_BUY_ABSORBED = ("BUY_ABSORBED", "BUY")

# Session phases. Opening noise and close protection are DISJOINT: membership in
# one must never imply the other.
_OPENING_PHASES = ("OPENING", "PRE_OPEN", "PRE_MARKET")
_CLOSING_PHASES = ("CLOSE", "POST_MARKET", "EOD")


def absorption_direction(absorption_side: str) -> str | None:
    """Direction implied by an absorption print, or None when unrecognised."""
    text = str(absorption_side or "").upper()
    if not text:
        return None
    if any(tag in text for tag in _SELL_ABSORBED):
        return "LONG"
    if any(tag in text for tag in _BUY_ABSORBED):
        return "SHORT"
    return None


def is_call_symbol(symbol) -> bool:
    """True only for a CALL/CE option instrument (never a bare futures root)."""
    text = str(symbol or "").upper().rstrip()
    return is_option_contract(symbol) and text.endswith(("CALL", "CE", "-CE"))


def is_put_symbol(symbol) -> bool:
    """True only for a PUT/PE option instrument."""
    text = str(symbol or "").upper().rstrip()
    return is_option_contract(symbol) and text.endswith(("PUT", "PE", "-PE"))


def is_opening_phase(phase) -> bool:
    """True during opening-noise phases (no fresh entries)."""
    return any(tag in str(phase or "").upper() for tag in _OPENING_PHASES)


def is_closing_phase(phase) -> bool:
    """True during close-protection phases (flatten, no fresh entries)."""
    return any(tag in str(phase or "").upper() for tag in _CLOSING_PHASES)
