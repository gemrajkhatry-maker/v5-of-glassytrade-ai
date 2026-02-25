"""
Canonical Symbol Matching

Provides fuzzy symbol matching for various symbol formats.
Normalizes symbols to a canonical form for deterministic matching.
"""

import re
from typing import List, Optional, Dict, Any


class SymbolMatcher:
    """
    Provides canonical symbol normalization and fuzzy matching.

    Converts various symbol formats to a canonical form:
    - RELIANCE, Reliance, reliance -> RELIANCE
    - NIFTY 50, NIFTY-50, NIFTY_50 -> NIFTY50
    - Removes spaces, dashes, underscores
    - Strips non-alphanumeric characters
    """

    @staticmethod
    def canonicalize(symbol: str) -> str:
        """
        Convert symbol to canonical form for deterministic matching.

        Args:
            symbol: Raw symbol string

        Returns:
            Canonical symbol (uppercase, no spaces/special chars)

        Examples:
            >>> SymbolMatcher.canonicalize("RELIANCE")
            'RELIANCE'
            >>> SymbolMatcher.canonicalize("NIFTY 50")
            'NIFTY50'
            >>> SymbolMatcher.canonicalize("NIFTY-50")
            'NIFTY50'
            >>> SymbolMatcher.canonicalize("nifty_50")
            'NIFTY50'
        """
        if not symbol:
            return ""

        # Convert to uppercase
        canonical = str(symbol).upper().strip()

        # Remove spaces, dashes, underscores
        canonical = canonical.replace(" ", "").replace("-", "").replace("_", "")

        # Remove non-alphanumeric characters
        canonical = "".join(c for c in canonical if c.isalnum())

        return canonical

    @staticmethod
    def match(
        query: str, candidates: List[str], min_similarity: float = 0.6
    ) -> Optional[str]:
        """
        Find best matching symbol from candidates.

        Args:
            query: Symbol to match
            candidates: List of available symbols
            min_similarity: Minimum similarity threshold (0.0-1.0)

        Returns:
            Best matching symbol or None if no good match

        Examples:
            >>> SymbolMatcher.match("REL", ["RELIANCE", "TCS", "INFY"])
            'RELIANCE'
        """
        query_canonical = SymbolMatcher.canonicalize(query)

        if not query_canonical:
            return None

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            candidate_canonical = SymbolMatcher.canonicalize(candidate)

            # Exact canonical match
            if query_canonical == candidate_canonical:
                return candidate

            # Prefix match (e.g., "REL" matches "RELIANCE")
            if candidate_canonical.startswith(query_canonical):
                # Strong bonus for prefix matches
                score = max(0.9, len(query_canonical) / len(candidate_canonical))
                if score > best_score:
                    best_score = score
                    best_match = candidate

            # Contains match (e.g., "LIANCE" matches "RELIANCE")
            elif query_canonical in candidate_canonical:
                score = max(0.7, len(query_canonical) / len(candidate_canonical) * 0.6)
                if score > best_score:
                    best_score = score
                    best_match = candidate

            # Levenshtein distance for typos
            else:
                similarity = SymbolMatcher._similarity(
                    query_canonical, candidate_canonical
                )
                if similarity > best_score and similarity >= min_similarity:
                    best_score = similarity
                    best_match = candidate

        return best_match if best_score >= min_similarity else None

    @staticmethod
    def search(
        query: str, candidates: List[str], limit: int = 10, min_similarity: float = 0.3
    ) -> List[str]:
        """
        Search for matching symbols, returns ranked list.

        Args:
            query: Search query
            candidates: List of available symbols
            limit: Maximum number of results
            min_similarity: Minimum similarity threshold

        Returns:
            List of matching symbols sorted by relevance
        """
        query_canonical = SymbolMatcher.canonicalize(query)

        if not query_canonical:
            return []

        matches = []

        for candidate in candidates:
            candidate_canonical = SymbolMatcher.canonicalize(candidate)
            score = 0.0

            # Exact match
            if query_canonical == candidate_canonical:
                score = 1.0

            # Prefix match (always include, high score)
            elif candidate_canonical.startswith(query_canonical):
                score = max(0.8, len(query_canonical) / len(candidate_canonical))

            # Contains match
            elif query_canonical in candidate_canonical:
                score = 0.5 * (len(query_canonical) / len(candidate_canonical))

            # Similarity match
            else:
                score = SymbolMatcher._similarity(query_canonical, candidate_canonical)

            if score >= min_similarity:
                matches.append((candidate, score))

        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)

        return [symbol for symbol, _ in matches[:limit]]

    @staticmethod
    def _similarity(s1: str, s2: str) -> float:
        """
        Calculate similarity between two strings using Levenshtein distance.

        Returns similarity ratio between 0.0 and 1.0.
        """
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0

        distance = SymbolMatcher._levenshtein_distance(s1, s2)
        max_len = max(len(s1), len(s2))

        return 1.0 - (distance / max_len)

    @staticmethod
    def _levenshtein_distance(s1: str, s2: str) -> int:
        """
        Calculate Levenshtein distance between two strings.

        This is the minimum number of single-character edits
        (insertions, deletions, substitutions) required to change
        one string into the other.
        """
        if len(s1) < len(s2):
            return SymbolMatcher._levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Cost is 0 if characters match, 1 otherwise
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    @staticmethod
    def extract_base_symbol(symbol: str) -> str:
        """
        Extract base symbol from option/futures symbol.

        Examples:
            >>> SymbolMatcher.extract_base_symbol("NIFTY26FEB25CE25000")
            'NIFTY'
            >>> SymbolMatcher.extract_base_symbol("RELIANCE-EQ")
            'RELIANCE'
        """
        if not symbol:
            return ""

        # Remove exchange suffixes
        base = symbol.split("-")[0]

        # Remove option/futures expiry info (simple heuristic)
        # Match patterns like: NIFTY26FEB25CE25000, GOLD26FEB25FUT
        match = re.match(r"^([A-Z]+)\d+[A-Z]{3}\d{2,4}", base)
        if match:
            return match.group(1)

        return base
