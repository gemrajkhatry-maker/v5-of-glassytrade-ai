import pytest

from quant.decision.intent import TradeIntent
from quant.execution.risk_sizer import FixedRiskSizer


def test_fixed_risk_sizer_snaps_once_to_lot_size():
    intent = TradeIntent("NIFTY", "LONG", "MODEL", 100, 95, 110)
    signal = FixedRiskSizer(127).size(intent, lot_size=25)
    assert signal.quantity == 125
    assert signal.symbol == "NIFTY"


def test_fixed_risk_sizer_rejects_budget_below_one_lot():
    intent = TradeIntent("NIFTY", "LONG", "MODEL", 100, 95, 110)
    with pytest.raises(ValueError, match="quantity"):
        FixedRiskSizer(10).size(intent, lot_size=25)
