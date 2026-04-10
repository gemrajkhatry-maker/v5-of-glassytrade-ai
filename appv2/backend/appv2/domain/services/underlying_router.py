"""Underlying Router — routes AMT analysis to underlying futures.

When trading options, AMT analysis runs on underlying futures data:
- NIFTY options → NIFTY futures
- BANKNIFTY options → BANKNIFTY futures
- CRUDEOIL options → CRUDEOIL futures
"""

from __future__ import annotations

from dataclasses import dataclass

# Mapping of underlying to its futures symbol (Dhan format)
_UNDERLYING_TO_FUTURES: dict[str, str] = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
    "CRUDEOIL": "CRUDEOIL",
    "CRUDEOILM": "CRUDEOILM",
    "GOLD": "GOLD",
    "GOLDM": "GOLDM",
    "SILVER": "SILVER",
    "NATURALGAS": "NATURALGAS",
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
}


@dataclass(frozen=True)
class UnderlyingMapping:
    option_symbol: str
    underlying: str
    futures_symbol: str
    is_option: bool


class UnderlyingRouter:
    """Routes option symbols to underlying futures for AMT analysis."""

    def __init__(self, custom_mapping: dict[str, str] | None = None):
        self._mapping = {**_UNDERLYING_TO_FUTURES}
        if custom_mapping:
            self._mapping.update(custom_mapping)

    def resolve(self, symbol: str) -> UnderlyingMapping:
        """Resolve symbol to underlying futures.

        Args:
            symbol: Option contract or futures symbol
                   e.g., "NIFTY 20 MAR 23400 CE" or "CRUDEOIL 16 APR 7200 CALL"

        Returns:
            UnderlyingMapping with option/futures routing info
        """
        symbol_upper = symbol.upper()

        # Check if it's an option (contains CE/CALL/PE/PUT)
        is_option = any(
            kw in symbol_upper for kw in ["CE", "CALL", "PE", "PUT"]
        )

        # Extract underlying (first word)
        parts = symbol_upper.split()
        underlying = parts[0] if parts else symbol_upper

        # Look up futures symbol
        futures_symbol = self._mapping.get(underlying, underlying)

        return UnderlyingMapping(
            option_symbol=symbol,
            underlying=underlying,
            futures_symbol=futures_symbol,
            is_option=is_option,
        )

    def get_futures_symbol(self, underlying: str) -> str:
        """Get futures symbol for an underlying."""
        return self._mapping.get(underlying, underlying)

    def is_option(self, symbol: str) -> bool:
        """Check if symbol is an option contract."""
        symbol_upper = symbol.upper()
        return any(kw in symbol_upper for kw in ["CE", "CALL", "PE", "PUT"])
