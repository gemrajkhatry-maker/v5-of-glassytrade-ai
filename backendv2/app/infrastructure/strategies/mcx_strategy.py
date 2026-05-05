"""MCX exchange strategy."""

from __future__ import annotations

from datetime import datetime
from app.domain.models.exchange_config import ExchangeConfig
from app.domain.ports.exchange_strategy import IExchangeStrategy

_EIA_WEEKDAYS = {2, 3}
_EIA_HOUR = 21
_EIA_MINUTE = 0


class MCXExchangeStrategy(IExchangeStrategy):
    def __init__(self, config: ExchangeConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "MCX"

    @property
    def config(self) -> ExchangeConfig:
        return self._config

    def get_cvd_block_threshold(self) -> float:
        return self._config.cvd_block_threshold

    def get_warm_up_minutes(self) -> int:
        return self._config.warm_up_minutes

    def get_aggression_sigma(self) -> float:
        return self._config.aggression_sigma

    def get_displacement_multiplier(self) -> float:
        return self._config.displacement_multiplier

    def get_balance_ratio_threshold(self) -> float:
        return self._config.balance_ratio_threshold

    def get_big_trade_multiplier(self) -> float:
        return self._config.big_trade_multiplier

    def get_llm_instruction(self) -> str:
        return self._config.llm_instruction

    def is_eia_window(self, symbol: str, ist_dt: datetime) -> bool:
        clean = symbol.upper().replace("MCX:", "").strip()
        underlying = clean.split("-")[0].split(" ")[0]
        if underlying not in self._config.eia_symbols:
            return False
        if ist_dt.weekday() not in _EIA_WEEKDAYS:
            return False
        target = ist_dt.replace(
            hour=_EIA_HOUR, minute=_EIA_MINUTE, second=0, microsecond=0
        )
        delta = abs((ist_dt - target).total_seconds())
        return delta <= self._config.eia_suppression_minutes * 60

    def get_session_open_time(self) -> tuple[int, int]:
        return 9, 0

    def get_session_close_time(self) -> tuple[int, int]:
        return 23, 15

    def is_underlying(self, symbol: str) -> bool:
        return self._config.is_underlying(symbol)

