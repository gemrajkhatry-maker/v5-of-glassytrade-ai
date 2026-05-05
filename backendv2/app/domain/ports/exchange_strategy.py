"""Exchange strategy port — abstraction for exchange-specific behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class IExchangeStrategy(ABC):
    """Encapsulates exchange-specific trading rules and thresholds."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Exchange name (for example, NSE / MCX)."""

    @abstractmethod
    def get_cvd_block_threshold(self) -> float:
        """CVD block threshold for this exchange."""

    @abstractmethod
    def get_warm_up_minutes(self) -> int:
        """Warm-up minutes after market open."""

    @abstractmethod
    def get_aggression_sigma(self) -> float:
        """Aggression sigma threshold."""

    @abstractmethod
    def get_displacement_multiplier(self) -> float:
        """Displacement threshold multiplier."""

    @abstractmethod
    def get_balance_ratio_threshold(self) -> float:
        """Balance ratio threshold."""

    @abstractmethod
    def get_big_trade_multiplier(self) -> float:
        """Big trade size multiplier."""

    @abstractmethod
    def get_llm_instruction(self) -> str:
        """System instruction text for LLM sessions."""

    @abstractmethod
    def is_eia_window(self, symbol: str, ist_dt: datetime) -> bool:
        """Whether symbol is in EIA suppression window."""

    @abstractmethod
    def get_session_open_time(self) -> tuple[int, int]:
        """Session opening time as (hour, minute)."""

    @abstractmethod
    def get_session_close_time(self) -> tuple[int, int]:
        """Session close time as (hour, minute)."""

    @abstractmethod
    def is_underlying(self, symbol: str) -> bool:
        """Whether symbol belongs to this exchange."""

