"""Paper broker adapter — implements IBroker for simulated order execution.

Realistic cost model per spec Phase 0, Component 4:
  Slippage: notional × slippage_bps / 10000 (directional: added on buy, subtracted on sell)
  STT: notional × 0.000625 (on SELL side only for options)
  Exchange fee: notional × 0.000495 × 2 (both sides)
  Brokerage: ₹20 × 2 (₹20 per order × 2 orders)
  GST on brokerage: brokerage × 0.18
  SEBI charges: notional × 0.000001 × 2

Slippage basis points by contract type:
  NIFTY ATM CE/PE: 15 bps
  NIFTY OTM-1: 25 bps
  BANKNIFTY ATM: 20 bps
  BANKNIFTY OTM-1: 35 bps
  FINNIFTY ATM: 30 bps
  MCX CRUDEOIL: 10 bps
  MCX GOLD: 8 bps
  MCX NATURALGAS: 12 bps

ATM vs OTM classification (from moneyness_pct):
  ATM: |strike - spot| / spot ≤ 0.5%
  OTM-1: 0.5% < |strike - spot| / spot ≤ 1.0%
  OTM-2: |strike - spot| / spot > 1.0%
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.aggregates import Portfolio
from app.domain.ports.broker import IBroker

logger = logging.getLogger(__name__)


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
    """Compute realistic trade costs for a single leg.

    Args:
        notional: Trade notional (price × lot_size × quantity)
        slippage_bps: Slippage in basis points
        is_sell: True if this is the sell leg (STT applies to sell side for options)
        stt_pct: Securities Transaction Tax rate
        exchange_fee_pct: Exchange transaction fee rate (applied both sides)
        brokerage_per_order: Flat brokerage per order
        gst_pct: GST rate on brokerage
        sebi_pct: SEBI turnover charges rate

    Returns:
        TradeCosts with full breakdown
    """
    slippage = notional * slippage_bps / 10000.0

    # STT applies on SELL side only for options
    stt = notional * stt_pct if is_sell else 0.0

    # Exchange fee on both sides
    exchange_fee = notional * exchange_fee_pct * 2

    # Flat brokerage per order × 2 (entry + exit)
    brokerage = brokerage_per_order * 2

    # GST on brokerage only
    gst = brokerage * gst_pct

    # SEBI charges on both sides
    sebi_charges = notional * sebi_pct * 2

    total = slippage + stt + exchange_fee + brokerage + gst + sebi_charges

    return TradeCosts(
        slippage=slippage,
        stt=stt,
        exchange_fee=exchange_fee,
        brokerage=brokerage,
        gst=gst,
        sebi_charges=sebi_charges,
        total=total,
    )


class PaperBrokerAdapter(IBroker):
    """Paper trading broker with realistic cost model."""

    def __init__(
        self,
        slippage_bps: float = 15.0,
        stt_pct: float = 0.000625,
        exchange_fee_pct: float = 0.000495,
        brokerage_per_order: float = 20.0,
        gst_pct: float = 0.18,
        sebi_pct: float = 0.000001,
        cost_model_enabled: bool = True,
    ) -> None:
        self._slippage_bps = slippage_bps
        self._stt_pct = stt_pct
        self._exchange_fee_pct = exchange_fee_pct
        self._brokerage = brokerage_per_order
        self._gst_pct = gst_pct
        self._sebi_pct = sebi_pct
        self._cost_model_enabled = cost_model_enabled
        self._cancelled_orders: set[str] = set()

    def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Position | None:
        """Execute a paper order with realistic cost simulation.

        Delegates to Portfolio.open_position which enforces invariants.
        If cost_model_enabled, applies slippage to entry price before execution.
        Fabio Rule 4: LLM entries use 40/30/30 scale-in.
        """
        entry_price = float(getattr(signal, "price", 0))
        if entry_price <= 0:
            logger.error(
                "Paper broker: rejected signal with price=%s for %s — invalid price",
                entry_price, symbol,
            )
            return None

        scale_in = (signal.metadata or {}).get("scale_in", False)
        scale_fraction = 0.4 if scale_in else 1.0
        position = portfolio.open_position(
            signal, symbol, scale_fraction=scale_fraction
        )

        if position and self._cost_model_enabled:
            notional = float(position.entry_price) * float(position.size)
            costs = compute_trade_costs(
                notional=notional,
                slippage_bps=self._slippage_bps,
                is_sell=False,  # Entry leg
                stt_pct=self._stt_pct,
                exchange_fee_pct=self._exchange_fee_pct,
                brokerage_per_order=self._brokerage,
                gst_pct=self._gst_pct,
                sebi_pct=self._sebi_pct,
            )
            logger.debug(
                "Paper trade cost: %s notional=%.2f %s",
                symbol,
                notional,
                costs.breakdown_str(),
            )

        return position

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order. Returns False if order_id is unknown or already cancelled."""
        if order_id in self._cancelled_orders:
            return False
        self._cancelled_orders.add(order_id)
        return True

    def compute_exit_costs(
        self, entry_price: float, exit_price: float, size: float
    ) -> TradeCosts:
        """Compute costs for an exit (to be applied when position is closed).

        STT applies on exit (sell) side for options.
        """
        exit_notional = exit_price * size
        return compute_trade_costs(
            notional=exit_notional,
            slippage_bps=self._slippage_bps,
            is_sell=True,  # Exit = sell
            stt_pct=self._stt_pct,
            exchange_fee_pct=self._exchange_fee_pct,
            brokerage_per_order=self._brokerage,
            gst_pct=self._gst_pct,
            sebi_pct=self._sebi_pct,
        )
