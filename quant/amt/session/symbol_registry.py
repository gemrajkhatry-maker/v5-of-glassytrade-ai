"""Symbol Registry — single source of truth for exchange↔symbol mapping.

Eliminates the duplicated _MCX_UNDERLYINGS frozenset that appeared in:
  - app/infrastructure/adapters/dhan_adapter.py
  - app/domain/fabio_ai/services/session_context_factory.py
  - app/domain/fabio_ai/services/option_scanner.py

All exchange-detection logic now lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet

from quant.contracts.exchange_config import ExchangeConfig


@dataclass(frozen=True)
class SymbolRegistry:
    """Registry mapping symbols to exchanges.

    Thread-safe, immutable, injectable via constructor.
    """

    mcx_underlyings: FrozenSet[str] = frozenset(
        {
            "CRUDEOIL",
            "GOLD",
            "SILVER",
            "NATURALGAS",
            "COPPER",
            "GOLDM",
            "SILVERM",
            "CRUDEOILM",
            "ZINC",
            "ALUMINIUM",
            "LEAD",
            "NICKEL",
            "COTTONCANDY",
        }
    )
    nse_underlyings: FrozenSet[str] = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY"})

    def exchange_for(self, symbol: str) -> str:
        """Determine exchange from a trading symbol.

        Args:
            symbol: e.g. "CRUDEOIL 17 MAR 6100 CALL" or "NIFTY 27 FEB 25500 CE"

        Returns:
            "MCX" or "NSE"
        """
        underlying = self._extract_underlying(symbol)
        if underlying in self.mcx_underlyings:
            return "MCX"
        if underlying in self.nse_underlyings:
            return "NSE"
        return "MCX"  # safe default

    def is_mcx(self, symbol: str) -> bool:
        return self.exchange_for(symbol) == "MCX"

    def is_nse(self, symbol: str) -> bool:
        return self.exchange_for(symbol) == "NSE"

    def is_option(self, symbol: str) -> bool:
        upper = symbol.upper()
        return "CALL" in upper or "PUT" in upper

    def all_underlyings(self) -> FrozenSet[str]:
        return self.mcx_underlyings | self.nse_underlyings

    @staticmethod
    def _extract_underlying(symbol: str) -> str:
        clean = symbol.replace("NSE:", "").replace("MCX:", "").strip()
        return clean.split("-")[0].split(" ")[0].upper()

    @classmethod
    def from_exchange_configs(
        cls, configs: dict[str, ExchangeConfig]
    ) -> SymbolRegistry:
        """Build from ExchangeConfig instances.

        Args:
            configs: {"NSE": ExchangeConfig, "MCX": ExchangeConfig}
        """
        nse = configs.get("NSE")
        mcx = configs.get("MCX")
        return cls(
            mcx_underlyings=mcx.underlyings if mcx else frozenset(),
            nse_underlyings=nse.underlyings if nse else frozenset(),
        )
