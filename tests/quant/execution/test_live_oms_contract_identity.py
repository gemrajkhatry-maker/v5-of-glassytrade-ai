from unittest.mock import MagicMock

import pytest

from quant.contracts.aggregates import Portfolio
from quant.contracts.contracts import ContractRef
from quant.decision.signal_builder import Signal
from quant.execution.live_oms import LiveOMS


def _contract(symbol="NIFTY 30 SEP 25000 CE"):
    return ContractRef(symbol=symbol, exchange="NFO", expiry="2026-09-30", lot_size=65, tick_size=0.05, strike=25000, option_type="CE")


def _signal(symbol):
    return Signal(type="LONG", reason="test", entry=100, sl=95, tp=110, rr=2, model_label="test", symbol=symbol, timestamp="t0")


def test_live_oms_rejects_signal_for_different_contract():
    oms = LiveOMS(MagicMock(), MagicMock(spec=Portfolio), contract=_contract())
    with pytest.raises(ValueError, match="signal symbol"):
        oms.submit(_signal("NIFTY 30 SEP 25000 PE"), 65)


def test_live_oms_rejects_close_for_different_contract():
    oms = LiveOMS(MagicMock(), MagicMock(spec=Portfolio), contract=_contract())
    position = MagicMock()
    position.size = 65
    position.order.signal.symbol = "NIFTY 30 SEP 25000 PE"
    with pytest.raises(ValueError, match="position symbol"):
        oms.close(position, 100, "t1", "TP")
