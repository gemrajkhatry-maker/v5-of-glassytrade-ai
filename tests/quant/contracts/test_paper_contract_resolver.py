"""Paper contract resolution stays broker-neutral."""

import pytest

from quant.contracts.contracts import ContractRef
from quant.execution.paper_contracts import PaperContract, PaperContractResolver


def _ref():
    return ContractRef(
        symbol="NIFTY 30 SEP 25000 CE",
        exchange="NFO",
        expiry="2026-09-30",
        strike=25000,
        option_type="CE",
        lot_size=65,
        tick_size=0.05,
    )


def test_paper_resolver_returns_deterministic_internal_contract():
    resolver = PaperContractResolver()

    first = resolver.resolve(_ref())
    second = resolver.resolve(_ref())

    assert isinstance(first, PaperContract)
    assert first == second
    assert first.instrument_key == "NFO:NIFTY 30 SEP 25000 CE:2026-09-30:25000:CE"
    assert not hasattr(first, "security_id")


def test_paper_resolver_rejects_unknown_contract():
    with pytest.raises(ValueError, match="ContractRef"):
        PaperContractResolver().resolve(
            ContractRef(
                symbol="NIFTY FUT",
                exchange="NFO",
                expiry="2026-09-30",
                lot_size=0,
                tick_size=0.05,
            )
        )
