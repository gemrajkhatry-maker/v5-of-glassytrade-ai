"""Contract-boundary tests for independent futures/options execution."""
from __future__ import annotations

import pytest

from quant.brokers.gateway import Tick
from quant.execution.execution_model import (
    ExecutionModel,
    signal_matches_contract,
)
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


@pytest.mark.parametrize(
    ("symbol", "market"),
    [
        ("NIFTY SEP FUT", "NSE"),
        ("NIFTY 30 SEP 25000 CE", "NSE"),
        ("CRUDEOIL SEP FUT", "MCX"),
        ("CRUDEOIL 30 SEP 7000 CE", "MCX"),
    ],
)
def test_independent_engine_is_contract_local(symbol: str, market: str):
    engine = QuantEngine(
        SyntheticGateway([Tick("1700000000", 100.0, 1.0, 0.5, 0.5)]),
        symbol,
        market=market,
        execution_model=ExecutionModel.INDEPENDENT,
    )
    assert engine._execution_model is ExecutionModel.INDEPENDENT
    assert engine._underlying_gateway is None
    assert signal_matches_contract(symbol, engine.symbol)


def test_independent_engine_rejects_underlying_gateway():
    with pytest.raises(ValueError, match="underlying_gateway"):
        QuantEngine(
            SyntheticGateway([]),
            "NIFTY 30 SEP 25000 CE",
            market="NSE",
            underlying_gateway=SyntheticGateway([]),
            execution_model=ExecutionModel.INDEPENDENT,
        )


def test_signal_contract_guard_rejects_cross_instrument_intent():
    assert not signal_matches_contract("NIFTY SEP FUT", "NIFTY 30 SEP 25000 CE")
    assert not signal_matches_contract("CRUDEOIL 30 SEP 7000 PE", "CRUDEOIL SEP FUT")
    assert signal_matches_contract("CRUDEOIL SEP FUT", "CRUDEOIL SEP FUT")
    assert not signal_matches_contract(None, "NIFTY SEP FUT")
