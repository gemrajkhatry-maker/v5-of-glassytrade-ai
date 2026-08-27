"""
Symbol Canonicalization Utilities

Provides fuzzy symbol matching for various input formats.
This ensures that "NIFTY 25700 CALL", "NIFTY-25700-CALL", and "nifty_25700_call"
all resolve to the same instrument.
"""

import re
from typing import Optional


def canonicalize_symbol(symbol: str) -> str:
    """
    Convert symbol to canonical form for deterministic matching.

    CRITICAL: This function ensures all format variations resolve to the SAME instrument.

    Normalization Rules:
    1. Convert to uppercase
    2. Remove ALL spaces
    3. Remove ALL dashes (-)
    4. Remove ALL underscores (_)
    5. Keep only alphanumeric characters

    Examples:
        "nifty 25700 call"     → "NIFTY25700CALL"
        "NIFTY-25700-CALL"     → "NIFTY25700CALL"
        "Nifty_25700_Call"     → "NIFTY25700CALL"
        "NiFtY 25-700 CaLl"    → "NIFTY25700CALL"

    Args:
        symbol: Input symbol in any format

    Returns:
        Canonical symbol (uppercase, alphanumeric only)
    """
    if not symbol:
        return ""

    # Step 1: Uppercase
    canonical = str(symbol).upper()

    # Step 1.5: Normalize single-digit days to 2 digits (e.g. " 1 SEP " -> " 01 SEP ")
    canonical = re.sub(
        r'(\b|\D)(\d)\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b',
        r'\g<1>0\2 \3',
        canonical,
    )

    # Step 2-4: Remove spaces, dashes, underscores
    canonical = canonical.replace(" ", "").replace("-", "").replace("_", "")

    # Step 5: Keep only alphanumeric (handles any edge cases)
    canonical = "".join(c for c in canonical if c.isalnum())

    return canonical


def normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol for display purposes.

    Less aggressive than canonicalize - keeps some formatting.

    Args:
        symbol: Input symbol

    Returns:
        Normalized symbol (uppercase, trimmed)
    """
    if not symbol:
        return ""

    return str(symbol).upper().strip()


def extract_underlying(symbol: str) -> str:
    """
    Extract underlying symbol from option/futures symbol.

    Examples:
        "NIFTY23FEB25000CE" → "NIFTY"
        "BANKNIFTY23MAR45000PE" → "BANKNIFTY"
        "RELIANCE23FEB2500CE" → "RELIANCE"

    Args:
        symbol: Trading symbol

    Returns:
        Underlying symbol
    """
    if not symbol:
        return ""

    # Remove option type suffix (CE/PE)
    symbol = re.sub(r"(CE|PE)$", "", symbol.upper())

    # Extract letters at the start (underlying name)
    match = re.match(r"^([A-Z]+)", symbol)
    if match:
        return match.group(1)

    return symbol


def is_option_symbol(symbol: str) -> bool:
    """
    Check if symbol is an option contract.

    Args:
        symbol: Trading symbol

    Returns:
        True if it's an option symbol
    """
    if not symbol:
        return False

    symbol_upper = str(symbol).upper()
    # Must end with CE or PE and have digits before (for strike price)
    if symbol_upper.endswith("CE") or symbol_upper.endswith("PE"):
        # Check that there are digits before CE/PE (indicating strike price)
        # e.g., NIFTY23FEB25000CE - has digits before CE
        # e.g., RELIANCE - no digits, not an option
        import re

        return bool(re.search(r"\d+(CE|PE)$", symbol_upper))
    return False


def is_futures_symbol(symbol: str) -> bool:
    """
    Check if symbol is a futures contract.

    Args:
        symbol: Trading symbol

    Returns:
        True if it's a futures symbol
    """
    if not symbol:
        return False

    # Futures typically don't have CE/PE suffix
    # and often have numeric expiry codes
    symbol_upper = str(symbol).upper()

    # Check for option suffix first
    if is_option_symbol(symbol):
        return False

    # Check for futures patterns (e.g., NIFTY23FEBFUT, GOLD23FEB)
    # Contains month abbreviation followed by digits or FUT
    if re.search(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)", symbol_upper):
        return True

    return False


def fuzzy_match_score(query: str, target: str) -> float:
    """
    Calculate fuzzy match score between query and target.

    Returns score from 0.0 (no match) to 1.0 (exact match).

    Args:
        query: Search query
        target: Target string to match against

    Returns:
        Match score between 0.0 and 1.0
    """
    if not query or not target:
        return 0.0

    query_canon = canonicalize_symbol(query)
    target_canon = canonicalize_symbol(target)

    # Exact match
    if query_canon == target_canon:
        return 1.0

    # Check if query is substring of target
    if query_canon in target_canon:
        return 0.8 + (0.2 * len(query_canon) / len(target_canon))

    # Check if target is substring of query
    if target_canon in query_canon:
        return 0.6 + (0.2 * len(target_canon) / len(query_canon))

    # Calculate character overlap
    query_chars = set(query_canon)
    target_chars = set(target_canon)

    if not query_chars or not target_chars:
        return 0.0

    intersection = query_chars & target_chars
    union = query_chars | target_chars

    jaccard_score = len(intersection) / len(union)

    return jaccard_score * 0.5  # Scale down for partial matches


class SymbolMatcher:
    """
    Symbol matcher with fuzzy matching capabilities.

    Provides both exact and fuzzy matching for symbols with various formats.
    """

    def __init__(self):
        """Initialize the symbol matcher."""
        self._symbols: dict = {}
        self._canonical_map: dict = {}

    def add_symbol(self, symbol: str, data: any) -> None:
        """
        Add a symbol to the matcher.

        Args:
            symbol: Original symbol
            data: Associated data
        """
        self._symbols[symbol] = data

        # Add canonical mapping
        canonical = canonicalize_symbol(symbol)
        if canonical not in self._canonical_map:
            self._canonical_map[canonical] = []
        self._canonical_map[canonical].append((symbol, data))

    def find_exact(self, symbol: str) -> Optional[any]:
        """
        Find exact match for symbol.

        Args:
            symbol: Symbol to find

        Returns:
            Associated data if found, None otherwise
        """
        # Try exact match first
        if symbol in self._symbols:
            return self._symbols[symbol]

        # Try canonical match
        canonical = canonicalize_symbol(symbol)
        if canonical in self._canonical_map:
            matches = self._canonical_map[canonical]
            return matches[0][1] if matches else None

        return None

    def find_fuzzy(self, query: str, min_score: float = 0.6) -> list:
        """
        Find fuzzy matches for query.

        Args:
            query: Search query
            min_score: Minimum match score (0.0 to 1.0)

        Returns:
            List of tuples (symbol, data, score) sorted by score
        """
        results = []

        for symbol, data in self._symbols.items():
            score = fuzzy_match_score(query, symbol)
            if score >= min_score:
                results.append((symbol, data, score))

        # Sort by score descending
        results.sort(key=lambda x: x[2], reverse=True)

        return results

    def clear(self) -> None:
        """Clear all symbols."""
        self._symbols.clear()
        self._canonical_map.clear()
