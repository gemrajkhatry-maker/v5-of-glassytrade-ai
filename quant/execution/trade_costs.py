"""Domain service helpers for trade cost and slippage calculations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradeCosts:
    """Breakdown of all costs for a single round-trip trade."""

    slippage: float
    stt: float
    exchange_fee: float
    brokerage: float
    gst: float
    sebi_charges: float
    total: float

    def breakdown_str(self) -> str:
        return (
            f"Slippage={self.slippage:.2f} "
            f"STT={self.stt:.2f} "
            f"Exchange={self.exchange_fee:.2f} "
            f"Brokerage={self.brokerage:.2f} "
            f"GST={self.gst:.2f} "
            f"SEBI={self.sebi_charges:.2f} "
            f"Total={self.total:.2f}"
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
    """Compute realistic trade costs for a single leg."""
    slippage = notional * slippage_bps / 10000.0
    stt = notional * stt_pct if is_sell else 0.0
    exchange_fee = notional * exchange_fee_pct * 2
    brokerage = brokerage_per_order * 2
    gst = brokerage * gst_pct
    sebi_charges = notional * sebi_pct * 2

    return TradeCosts(
        slippage=slippage,
        stt=stt,
        exchange_fee=exchange_fee,
        brokerage=brokerage,
        gst=gst,
        sebi_charges=sebi_charges,
        total=slippage + stt + exchange_fee + brokerage + gst + sebi_charges,
    )


def compute_fill_costs(
    notional: float,
    *,
    slippage_bps: float = 15.0,
    is_sell: bool = False,
    stt_pct: float = 0.000625,
    exchange_fee_pct: float = 0.000495,
    brokerage_per_order: float = 20.0,
    gst_pct: float = 0.18,
    sebi_pct: float = 0.000001,
) -> TradeCosts:
    """Compute costs for one actual fill/leg.

    ``compute_trade_costs`` is retained for the legacy round-trip API. Paper
    fills use this function so brokerage, exchange charges and SEBI charges
    are not accidentally doubled on each leg.
    """
    slippage = notional * slippage_bps / 10000.0
    stt = notional * stt_pct if is_sell else 0.0
    exchange_fee = notional * exchange_fee_pct
    brokerage = brokerage_per_order
    gst = brokerage * gst_pct
    sebi_charges = notional * sebi_pct
    return TradeCosts(
        slippage=slippage,
        stt=stt,
        exchange_fee=exchange_fee,
        brokerage=brokerage,
        gst=gst,
        sebi_charges=sebi_charges,
        total=slippage + stt + exchange_fee + brokerage + gst + sebi_charges,
    )
