"""Exchange Strategy port — abstract interface for exchange-specific behavior.

Encapsulates all NSE/MCX differences behind a clean boundary. Domain services
depend on this port, not on concrete exchange logic.

Adding a new exchange (e.g., BSE Futures) = implement this interface once.
No other file needs to change (OCP compliance).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.domain.models.exchange_config import ExchangeConfig
from app.domain.services.symbol_registry import SymbolRegistry


class IExchangeStrategy(ABC):
    """Encapsulates exchange-specific trading rules and thresholds.

    Domain services receive this via constructor injection.
    Infrastructure provides concrete implementations (NSEExchangeStrategy, MCXExchangeStrategy).
    """

    @property
    @abstractmethod
    def config(self) -> ExchangeConfig:
        """The immutable config backing this strategy."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Exchange name: "NSE" or "MCX"."""
        ...

    @abstractmethod
    def get_cvd_block_threshold(self) -> float:
        """CVD extreme threshold for this exchange.

        NSE: 5000 (high volume, wider threshold)
        MCX: 50   (thinner books, tighter threshold)
        """
        ...

    @abstractmethod
    def get_warm_up_minutes(self) -> int:
        """Minutes to skip at session open."""
        ...

    @abstractmethod
    def get_aggression_sigma(self) -> float:
        """Aggression sigma threshold for this exchange."""
        ...

    @abstractmethod
    def get_displacement_multiplier(self) -> float:
        """Displacement multiplier for this exchange."""
        ...

    @abstractmethod
    def get_balance_ratio_threshold(self) -> float:
        """Balance ratio threshold for this exchange."""
        ...

    @abstractmethod
    def get_big_trade_multiplier(self) -> float:
        """Big trade size multiplier relative to average."""
        ...

    @abstractmethod
    def get_llm_instruction(self) -> str:
        """Exchange-specific LLM system prompt."""
        ...

    @abstractmethod
    def is_eia_window(self, symbol: str, ist_dt: datetime) -> bool:
        """Check if we're in an EIA data release suppression window."""
        ...

    @abstractmethod
    def get_session_close_time(self) -> tuple[int, int]:
        """Get (hour, minute) of session close in IST."""
        ...

    @abstractmethod
    def get_session_open_time(self) -> tuple[int, int]:
        """Get (hour, minute) of session open in IST."""
        ...

    @abstractmethod
    def is_underlying(self, symbol: str) -> bool:
        """Check if a symbol belongs to this exchange."""
        ...

    def get_symbol_exchange(self, symbol: str, registry: SymbolRegistry) -> str:
        """Determine which exchange a symbol belongs to.

        Default implementation delegates to SymbolRegistry.
        """
        return registry.exchange_for(symbol)
