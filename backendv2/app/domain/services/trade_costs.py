"""Domain helper for deterministic round-trip trade-cost estimates."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradeCosts:
    slippage: float
    stt: float
    exchange_fee: float
    brokerage: float
    gst: float
    sebi_charges: float
    total: float

    def breakdown_str(self) -> str:
        return (
            f"Slippage={self.slippage:.2f} STT={self.stt:.2f} "
            f"Exchange={self.exchange_fee:.2f} Brokerage={self.brokerage:.2f} "
            f"GST={self.gst:.2f} SEBI={self.sebi_charges:.2f} Total={self.total:.2f}"
        )


def compute_trade_costs(
    notional: float,
    slippage_bps: float = 15.0,
    is_sell: bool = False,
    stt_pct: float = 0.000625,
    exchange_fee_pct: float = 0.000495,
    brokerage_per_order: float = 20.0,
    gst_pct: float = 0.18,
    sebi_pct: float = 0.000001,
) -> TradeCosts:
    slippage = float(notional) * slippage_bps / 10000.0
    stt = float(notional) * stt_pct if is_sell else 0.0
    exchange_fee = float(notional) * exchange_fee_pct * 2
    brokerage = float(brokerage_per_order) * 2
    gst = brokerage * gst_pct
    sebi_charges = float(notional) * sebi_pct * 2

    return TradeCosts(
        slippage=slippage,
        stt=stt,
        exchange_fee=exchange_fee,
        brokerage=brokerage,
        gst=gst,
        sebi_charges=sebi_charges,
        total=slippage + stt + exchange_fee + brokerage + gst + sebi_charges,
    )

