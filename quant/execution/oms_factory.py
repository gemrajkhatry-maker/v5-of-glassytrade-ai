"""Composition-root factory for cost-aware paper execution.

Direct ``PaperOMS`` construction remains useful for isolated unit tests.  The
runtime coordinator must use this factory so paper execution always has a
validated broker-neutral contract and an explicit cost/fill policy.
"""

from __future__ import annotations

from collections.abc import Callable

from quant.contracts.contracts import ContractRef
from quant.execution.oms import PaperOMS
from quant.execution.paper_simulator import PaperExecutionSimulator

_REQUIRED_COST_KEYS = (
    "slippage_bps",
    "stt_pct",
    "exchange_fee_pct",
    "brokerage_per_order",
    "gst_on_brokerage_pct",
    "sebi_charges_pct",
)


def make_paper_oms(
    *,
    contract: ContractRef,
    cost_profile: dict | None,
    quote_provider: Callable[[], tuple[float, float] | None] | None = None,
) -> PaperOMS:
    """Build the only paper OMS permitted by the production composition path.

    ``bid_ask`` is deliberately the runtime default.  If the quote provider
    cannot supply a valid executable quote, the simulator rejects the order
    rather than silently converting it into a mid/reference-price fill.
    """
    if not isinstance(contract, ContractRef):
        raise ValueError("paper OMS requires a validated ContractRef")
    if not cost_profile:
        raise ValueError("paper OMS requires an explicit cost_profile")
    missing = [key for key in _REQUIRED_COST_KEYS if key not in cost_profile]
    if missing:
        raise ValueError(
            f"cost_profile missing keys {missing}; refusing costless paper fills"
        )
    fill_mode = str(cost_profile.get("fill_mode", "bid_ask")).strip().lower()
    simulator = PaperExecutionSimulator(
        fill_mode=fill_mode,
        slippage_bps=float(cost_profile["slippage_bps"]),
        stt_pct=float(cost_profile["stt_pct"]),
        exchange_fee_pct=float(cost_profile["exchange_fee_pct"]),
        brokerage_per_order=float(cost_profile["brokerage_per_order"]),
        gst_pct=float(cost_profile["gst_on_brokerage_pct"]),
        sebi_pct=float(cost_profile["sebi_charges_pct"]),
    )
    return PaperOMS(
        lot_size=float(contract.lot_size),
        simulator=simulator,
        contract=contract,
        quote_provider=quote_provider,
    )
