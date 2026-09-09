"""Policy for explicit strategy-mode transitions."""

from quant.modeling.contracts import ForecastStatus, StrategyMode


class ModeController:
    def __init__(self, configured_mode: StrategyMode) -> None:
        self.configured_mode = configured_mode

    def next_mode(self, status: ForecastStatus) -> StrategyMode:
        if status is ForecastStatus.AVAILABLE:
            return self.configured_mode
        if self.configured_mode is StrategyMode.TIMESFM_PRIMARY:
            return StrategyMode.SAFE_HALT
        if self.configured_mode is StrategyMode.TIMESFM_ASSISTED:
            return StrategyMode.DETERMINISTIC
        return self.configured_mode
