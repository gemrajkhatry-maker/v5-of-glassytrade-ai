"""Paper fills can be restored without broker-specific identity."""

from quant.contracts.contracts import ContractRef
from quant.execution.paper_simulator import PaperExecutionSimulator


def _contract():
    return ContractRef(
        symbol="NIFTY 30 SEP 25000 CE",
        exchange="NFO",
        expiry="2026-09-30",
        strike=25000,
        option_type="CE",
        lot_size=65,
        tick_size=0.05,
    )


def test_paper_fill_can_be_exported_and_restored():
    original = PaperExecutionSimulator()
    fill = original.submit(
        order_id="paper-restart-1",
        contract=_contract(),
        side="BUY",
        quantity=65,
        reference_price=100.0,
    )

    restored = PaperExecutionSimulator.from_records(original.export_records())

    assert restored.fills == (fill,)
    assert restored.submit(
        order_id="paper-restart-1",
        contract=_contract(),
        side="BUY",
        quantity=65,
        reference_price=100.0,
    ) == fill
