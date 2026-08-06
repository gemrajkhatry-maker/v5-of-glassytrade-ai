"""Phase 4 tests — MarketState enum usage."""
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import AMTResult


class TestMarketStateEnum:
    def test_amt_result_accepts_enum(self):
        result = AMTResult(
            market_state=MarketState.BALANCED,
            poc=100.0,
            value_area_high=105.0,
            value_area_low=95.0,
        )
        assert result.market_state == MarketState.BALANCED
        assert result.market_state == "BALANCED"  # str comparison still works

    def test_amt_result_accepts_imbalanced(self):
        result = AMTResult(
            market_state=MarketState.IMBALANCED,
            poc=100.0,
            value_area_high=105.0,
            value_area_low=95.0,
        )
        assert result.market_state == "IMBALANCED"
