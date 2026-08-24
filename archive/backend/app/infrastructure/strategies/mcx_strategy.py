"""MCX Exchange Strategy — encapsulates all MCX-specific behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant.contracts.exchange_config import ExchangeConfig
from quant.contracts.ports.exchange_strategy import IExchangeStrategy as ExchangeStrategy
from quant.contracts.timezones import IST



# EIA release times in IST (Wednesday/Thursday 10:30 AM ET = 21:00 IST)
_EIA_WEEKDAYS = {2, 3}  # Wednesday=2, Thursday=3
_EIA_HOUR = 21
_EIA_MINUTE = 0


class MCXExchangeStrategy(ExchangeStrategy):
    """MCX Commodity exchange strategy.

    All MCX-specific thresholds, session times, EIA windows, and rules
    live here. Domain services receive this via constructor injection.
    """

    def __init__(self, config: ExchangeConfig) -> None:
        self._config = config

    @property
    def config(self) -> ExchangeConfig:
        return self._config

    @property
    def name(self) -> str:
        return "MCX"

    def get_cvd_block_threshold(self) -> float:
        return self._config.cvd_block_threshold  # 50

    def get_warm_up_minutes(self) -> int:
        return self._config.warm_up_minutes  # 15

    def get_aggression_sigma(self) -> float:
        return self._config.aggression_sigma  # 2.0

    def get_displacement_multiplier(self) -> float:
        return self._config.displacement_multiplier  # 1.2

    def get_balance_ratio_threshold(self) -> float:
        return self._config.balance_ratio_threshold  # 0.55

    def get_big_trade_multiplier(self) -> float:
        return self._config.big_trade_multiplier  # 5.0

    def get_llm_instruction(self) -> str:
        return self._config.llm_instruction

    def is_eia_window(self, symbol: str, ist_dt: datetime) -> bool:
        """Check if symbol is in EIA suppression window.

        CRUDEOIL: Wednesday 21:00 IST
        NATURALGAS: Thursday 21:00 IST
        Suppression: +/- eia_suppression_minutes around release.
        """
        if not self._config.eia_symbols:
            return False

        # Extract underlying from symbol
        clean = symbol.upper().replace("MCX:", "").strip()
        underlying = clean.split("-")[0].split(" ")[0]

        if underlying not in self._config.eia_symbols:
            return False

        if ist_dt.weekday() not in _EIA_WEEKDAYS:
            return False

        # Check if within suppression window
        eia_time = ist_dt.replace(
            hour=_EIA_HOUR, minute=_EIA_MINUTE, second=0, microsecond=0
        )
        delta = abs((ist_dt - eia_time).total_seconds())
        return delta <= self._config.eia_suppression_minutes * 60

    def get_session_close_time(self) -> tuple[int, int]:
        return (23, 15)

    def get_session_open_time(self) -> tuple[int, int]:
        return (9, 0)

    def is_underlying(self, symbol: str) -> bool:
        return self._config.is_underlying(symbol)
