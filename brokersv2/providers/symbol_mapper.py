"""
Symbol mapper for normalizing symbols across providers.

Handles NSE symbol variations:
- RELIANCE, RELIANCE-EQ, RELIANCE EQ, nse:RELIANCE
- NIFTY 50, NIFTY, ^NSEI
- BANKNIFTY, NIFTY BANK, ^NSEBANK
"""

from __future__ import annotations

import re
from typing import Dict, Optional


class SymbolMapper:
    """
    Maps between internal canonical symbols and provider-specific formats.
    
    The application uses ONE unified internal symbol format.
    Each provider gets its preferred format.
    """
    
    # Symbol variations mapping
    SYMBOL_VARIATIONS: Dict[str, Dict[str, str]] = {
        "RELIANCE": {
            "canonical": "RELIANCE",
            "dhan": "RELIANCE",
            "opencart": "RELIANCE",
            "nse": "RELIANCE-EQ",
        },
        "NIFTY 50": {
            "canonical": "NIFTY 50",
            "dhan": "NIFTY",
            "opencart": "NIFTY 50",
            "nse": "NIFTY",
        },
        "BANKNIFTY": {
            "canonical": "BANKNIFTY",
            "dhan": "NIFTY BANK",
            "opencart": "BANKNIFTY",
            "nse": "NIFTY BANK",
        },
        "NIFTY FINANCIAL": {
            "canonical": "NIFTY FINANCIAL",
            "dhan": "NIFTY FIN SERVICE",
            "opencart": "NIFTY FINANCIAL",
            "nse": "NIFTY FIN SERVICE",
        },
    }
    
    # Common suffixes to strip
    _SUFFIXES_TO_STRIP = ["-EQ", " EQ", "-BE", " BE"]
    
    # Prefix patterns to strip
    _PREFIX_PATTERNS = [
        r"^nse:",
        r"^NSE:",
        r"^mcx:",
        r"^MCX:",
        r"^nfo:",
        r"^NFO:",
        r"^\^",  # Caret prefix (^NSEI, ^NSEBANK)
    ]
    
    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalize various symbol formats to canonical format.
        
        Examples:
            "RELIANCE-EQ" → "RELIANCE"
            "nse:RELIANCE" → "RELIANCE"
            "RELIANCE EQ" → "RELIANCE"
            "^NSEI" → "NIFTY 50"
        
        Args:
            symbol: Raw symbol from any source
        
        Returns:
            Normalized canonical symbol
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        
        normalized = symbol.strip().upper()
        
        # Remove prefixes
        for pattern in self._PREFIX_PATTERNS:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
        
        # Remove suffixes
        for suffix in self._SUFFIXES_TO_STRIP:
            if normalized.endswith(suffix.upper()):
                normalized = normalized[: -len(suffix)]
        
        # Handle special cases
        special_mappings = {
            "NSEI": "NIFTY 50",
            "NIFTY": "NIFTY 50",
            "NSEBANK": "BANKNIFTY",
            "NIFTY BANK": "BANKNIFTY",
            "FINNIFTY": "NIFTY FINANCIAL",
            "NIFTY FIN SERVICE": "NIFTY FINANCIAL",
        }
        
        if normalized in special_mappings:
            return special_mappings[normalized]
        
        return normalized
    
    def to_provider_symbol(self, canonical_symbol: str, provider: str) -> str:
        """
        Convert canonical symbol to provider-specific format.
        
        Args:
            canonical_symbol: Normalized canonical symbol
            provider: Provider name ("dhan", "opencart", "nse")
        
        Returns:
            Provider-specific symbol format
        """
        # First normalize the input
        normalized = self.normalize_symbol(canonical_symbol)
        
        # Check if we have a mapping
        if normalized in self.SYMBOL_VARIATIONS:
            mapping = self.SYMBOL_VARIATIONS[normalized]
            return mapping.get(provider, normalized)
        
        # For equities, add -EQ suffix for NSE provider
        if provider == "nse" and "-" not in normalized:
            return f"{normalized}-EQ"
        
        # Default: return as-is
        return normalized
    
    def from_provider_symbol(self, provider_symbol: str, provider: str) -> str:
        """
        Convert provider symbol back to canonical format.
        
        Args:
            provider_symbol: Symbol from provider
            provider: Provider name ("dhan", "opencart", "nse")
        
        Returns:
            Canonical symbol format
        """
        # Normalize first
        normalized = self.normalize_symbol(provider_symbol)
        
        # Reverse lookup in SYMBOL_VARIATIONS
        for canonical, mappings in self.SYMBOL_VARIATIONS.items():
            if mappings.get(provider) == normalized:
                return mappings["canonical"]
        
        # If not found, return normalized version
        return normalized
    
    def get_supported_symbols(self) -> list:
        """
        Get list of all supported canonical symbols.
        
        Returns:
            List of canonical symbol names
        """
        return list(self.SYMBOL_VARIATIONS.keys())
    
    def is_index(self, symbol: str) -> bool:
        """
        Check if symbol is an index.
        
        Args:
            symbol: Symbol to check
        
        Returns:
            True if symbol is an index
        """
        normalized = self.normalize_symbol(symbol)
        indices = ["NIFTY 50", "BANKNIFTY", "NIFTY FINANCIAL"]
        return normalized in indices
    
    def is_equity(self, symbol: str) -> bool:
        """
        Check if symbol is an equity.
        
        Args:
            symbol: Symbol to check
        
        Returns:
            True if symbol is an equity
        """
        return not self.is_index(symbol)
