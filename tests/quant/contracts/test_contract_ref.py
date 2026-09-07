"""Broker-neutral contract identity tests.

The quant layer identifies instruments without carrying broker security IDs or
broker payload details across the adapter boundary.
"""

from dataclasses import asdict

import pytest

from quant.contracts.contracts import ContractRef


def test_option_contract_ref_contains_only_broker_neutral_identity():
    ref = ContractRef(
        symbol="NIFTY 30 SEP 25000 CE",
        exchange="NFO",
        expiry="2026-09-30",
        strike=25000,
        option_type="CE",
        lot_size=65,
        tick_size=0.05,
    )

    assert ref.symbol == "NIFTY 30 SEP 25000 CE"
    assert ref.exchange == "NFO"
    assert ref.lot_size == 65
    assert "security_id" not in asdict(ref)
    assert not any(key.lower().startswith("dhan") for key in asdict(ref))


def test_futures_contract_ref_allows_no_option_fields():
    ref = ContractRef(
        symbol="NIFTY SEP FUT",
        exchange="NFO",
        expiry="2026-09-30",
        lot_size=65,
        tick_size=0.05,
    )

    assert ref.option_type == ""
    assert ref.strike is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expiry": "", "lot_size": 65, "tick_size": 0.05},
        {"expiry": "2026-09-30", "lot_size": 0, "tick_size": 0.05},
        {"expiry": "2026-09-30", "lot_size": 65, "tick_size": 0},
        {
            "expiry": "2026-09-30",
            "strike": None,
            "option_type": "CE",
            "lot_size": 65,
            "tick_size": 0.05,
        },
    ],
)
def test_invalid_derivative_contract_ref_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ContractRef(symbol="NIFTY CONTRACT", exchange="NFO", **kwargs)


def test_option_type_is_canonicalized():
    ref = ContractRef(
        symbol="NIFTY 30 SEP 25000 CALL",
        exchange="NFO",
        expiry="2026-09-30",
        strike=25000,
        option_type="call",
        lot_size=65,
        tick_size=0.05,
    )

    assert ref.option_type == "CE"
