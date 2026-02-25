"""
Tests for Canonical Symbol Matching.
"""

import pytest

from brokers.broker.symbol_matcher import SymbolMatcher


class TestSymbolMatcher:
    """Test symbol matching functionality."""

    def test_canonicalize_basic(self):
        """Test basic canonicalization."""
        assert SymbolMatcher.canonicalize("RELIANCE") == "RELIANCE"
        assert SymbolMatcher.canonicalize("reliance") == "RELIANCE"
        assert SymbolMatcher.canonicalize("  RELIANCE  ") == "RELIANCE"

    def test_canonicalize_removes_special_chars(self):
        """Test removal of special characters."""
        assert SymbolMatcher.canonicalize("NIFTY 50") == "NIFTY50"
        assert SymbolMatcher.canonicalize("NIFTY-50") == "NIFTY50"
        assert SymbolMatcher.canonicalize("NIFTY_50") == "NIFTY50"
        assert SymbolMatcher.canonicalize("NIFTY-50 INDEX") == "NIFTY50INDEX"

    def test_canonicalize_empty(self):
        """Test canonicalization of empty string."""
        assert SymbolMatcher.canonicalize("") == ""
        assert SymbolMatcher.canonicalize(None) == ""

    def test_match_exact(self):
        """Test exact matching."""
        candidates = ["RELIANCE", "TCS", "INFY", "HDFCBANK"]
        result = SymbolMatcher.match("RELIANCE", candidates)
        assert result == "RELIANCE"

    def test_match_case_insensitive(self):
        """Test case-insensitive matching."""
        candidates = ["RELIANCE", "TCS", "INFY"]
        result = SymbolMatcher.match("reliance", candidates)
        assert result == "RELIANCE"

    def test_match_prefix(self):
        """Test prefix matching."""
        candidates = ["RELIANCE", "TCS", "INFY"]
        result = SymbolMatcher.match("REL", candidates)
        assert result == "RELIANCE"

    def test_match_contains(self):
        """Test contains matching."""
        candidates = ["RELIANCE", "TCS", "INFY"]
        result = SymbolMatcher.match("LIANCE", candidates)
        assert result == "RELIANCE"

    def test_match_similarity(self):
        """Test similarity matching for typos."""
        candidates = ["RELIANCE", "TCS", "INFY"]
        result = SymbolMatcher.match("RELIENCE", candidates)  # Typo
        assert result == "RELIANCE"

    def test_match_no_result(self):
        """Test when no match found."""
        candidates = ["RELIANCE", "TCS", "INFY"]
        result = SymbolMatcher.match("XYZ123", candidates, min_similarity=0.9)
        assert result is None

    def test_search_basic(self):
        """Test basic search functionality."""
        candidates = ["RELIANCE", "TCS", "INFY", "HDFCBANK"]
        results = SymbolMatcher.search("REL", candidates)
        assert "RELIANCE" in results

    def test_search_ranked_results(self):
        """Test that results are ranked by relevance."""
        candidates = ["RELIANCE", "RELAXO", "RELIGARE", "TCS"]
        results = SymbolMatcher.search("REL", candidates)
        # Exact prefix matches should come first
        assert len(results) > 0
        assert results[0] in ["RELIANCE", "RELAXO", "RELIGARE"]

    def test_search_limit(self):
        """Test search result limit."""
        candidates = ["RELIANCE", "RELAXO", "RELIGARE", "RELCAPITAL"]
        results = SymbolMatcher.search("REL", candidates, limit=2)
        assert len(results) <= 2

    def test_search_min_similarity(self):
        """Test minimum similarity threshold."""
        candidates = ["RELIANCE", "TCS", "INFY"]
        results = SymbolMatcher.search("XYZ", candidates, min_similarity=0.9)
        assert len(results) == 0

    def test_similarity_calculation(self):
        """Test similarity calculation."""
        # Same strings
        assert SymbolMatcher._similarity("TEST", "TEST") == 1.0
        # Empty strings
        assert SymbolMatcher._similarity("", "") == 1.0
        # One empty
        assert SymbolMatcher._similarity("TEST", "") == 0.0
        assert SymbolMatcher._similarity("", "TEST") == 0.0
        # Different strings
        assert SymbolMatcher._similarity("TEST", "TENT") > 0.0
        assert SymbolMatcher._similarity("TEST", "TENT") < 1.0

    def test_levenshtein_distance(self):
        """Test Levenshtein distance calculation."""
        # Same strings
        assert SymbolMatcher._levenshtein_distance("TEST", "TEST") == 0
        # One character different
        assert SymbolMatcher._levenshtein_distance("TEST", "TENT") == 1
        # Empty string
        assert SymbolMatcher._levenshtein_distance("TEST", "") == 4
        # Totally different
        assert SymbolMatcher._levenshtein_distance("ABC", "XYZ") == 3

    def test_extract_base_symbol_equity(self):
        """Test extracting base symbol from equity."""
        assert SymbolMatcher.extract_base_symbol("RELIANCE-EQ") == "RELIANCE"
        assert SymbolMatcher.extract_base_symbol("TCS") == "TCS"

    def test_extract_base_symbol_option(self):
        """Test extracting base symbol from option."""
        assert SymbolMatcher.extract_base_symbol("NIFTY26FEB25CE25000") == "NIFTY"
        assert (
            SymbolMatcher.extract_base_symbol("BANKNIFTY26FEB25PE40000") == "BANKNIFTY"
        )

    def test_extract_base_symbol_futures(self):
        """Test extracting base symbol from futures."""
        assert SymbolMatcher.extract_base_symbol("GOLD26FEB25FUT") == "GOLD"
        assert SymbolMatcher.extract_base_symbol("SILVER26MAR25FUT") == "SILVER"

    def test_extract_base_symbol_empty(self):
        """Test extracting base symbol from empty string."""
        assert SymbolMatcher.extract_base_symbol("") == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
