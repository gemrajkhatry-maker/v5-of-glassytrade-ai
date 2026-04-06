"""NSE Exchange Strategy — encapsulates all NSE-specific behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models.exchange_config import ExchangeConfig
from app.domain.ports.exchange_strategy import ExchangeStrategy
from app.shared.timezones import IST




class NSEExchangeStrategy(ExchangeStrategy):
    """NSE Index Options exchange strategy.

    All NSE-specific thresholds, session times, and rules live here.
    Domain services receive this via constructor injection.
    """

    def __init__(self, config: ExchangeConfig) -> None:
        self._config = config

    @property
    def config(self) -> ExchangeConfig:
        return self._config

    @property
    def name(self) -> str:
        return "NSE"

    def get_cvd_block_threshold(self) -> float:
        return self._config.cvd_block_threshold  # 5000

    def get_warm_up_minutes(self) -> int:
        return self._config.warm_up_minutes  # 15

    def get_aggression_sigma(self) -> float:
        return self._config.aggression_sigma  # 2.5

    def get_displacement_multiplier(self) -> float:
        return self._config.displacement_multiplier  # 1.5

    def get_balance_ratio_threshold(self) -> float:
        return self._config.balance_ratio_threshold  # 0.70

    def get_big_trade_multiplier(self) -> float:
        return self._config.big_trade_multiplier  # 3.0

    def get_llm_instruction(self) -> str:
        return self._config.llm_instruction

    def is_eia_window(self, symbol: str, ist_dt: datetime) -> bool:
        # NSE has no EIA data releases
        return False

    def get_session_close_time(self) -> tuple[int, int]:
        return (15, 15)

    def get_session_open_time(self) -> tuple[int, int]:
        return (9, 15)

    def is_underlying(self, symbol: str) -> bool:
        return self._config.is_underlying(symbol)
