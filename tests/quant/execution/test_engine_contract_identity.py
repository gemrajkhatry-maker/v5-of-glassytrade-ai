"""Engine-owned contract identity tests."""
from __future__ import annotations

import pytest

from quant.contracts.contracts import ContractRef
from quant.execution.execution_model import ExecutionModel
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def _contract(symbol: str) -> ContractRef:
    return ContractRef(
        symbol=symbol,
        exchange="NFO",
        expiry="2026-09-30",
        strike=25000,
        option_type="CE",
        lot_size=65,
        tick_size=0.05,
    )


def test_engine_owns_validated_contract_identity():
    symbol = "NIFTY 30 SEP 25000 CE"
    ref = _contract(symbol)
    engine = QuantEngine(
        SyntheticGateway([]),
        symbol,
        market="NSE",
        contract=ref,
        execution_model=ExecutionModel.INDEPENDENT,
    )
    assert engine._contract is ref
    assert engine._contract.exchange == "NFO"
    assert engine._contract.option_type == "CE"


def test_engine_rejects_contract_for_another_symbol():
    with pytest.raises(ValueError, match="contract symbol"):
        QuantEngine(
            SyntheticGateway([]),
            "NIFTY 30 SEP 25000 CE",
            contract=_contract("NIFTY 30 SEP 25100 CE"),
        )


def test_direct_legacy_replay_can_omit_contract_identity():
    """Compatibility for synthetic unit/replay engines during migration."""
    engine = QuantEngine(SyntheticGateway([]), "TEST", interval_seconds=1)
    assert engine._contract is None
