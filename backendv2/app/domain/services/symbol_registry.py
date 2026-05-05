"""Simple symbol-to-exchange resolver."""

from __future__ import annotations


class SymbolRegistry:
    """Resolve exchange family from trading symbol names."""

    _mcx_prefixes = frozenset({"CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER"})

    def exchange_for(self, symbol: str) -> str:
        clean = symbol.upper().replace("NSE:", "").replace("MCX:", "").strip()
        underlying = clean.split("-")[0].split(" ")[0]
        return "MCX" if underlying in self._mcx_prefixes else "NSE"

