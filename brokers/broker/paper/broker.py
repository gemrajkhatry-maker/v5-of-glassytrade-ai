"""
Paper Broker - Simulated broker for testing and development.

This broker simulates all operations without making real API calls.
Useful for:
- Testing trading strategies
- Development without API access
- Simulating market scenarios
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import List, Dict, AsyncIterator

from ..ports import IBrokerPort
from ..entities import (
    Instrument,
    Quote,
    Tick,
    Order,
    Position,
    OptionChain,
    MarketDepth,
    DepthLevel,
)
from ..types import Exchange, OrderStatus
from brokers.broker.logging import get_logger

logger = get_logger("paper")


# Default mock prices for common symbols
DEFAULT_PRICES = {
    "RELIANCE": 2500.0,
    "TCS": 3800.0,
    "NIFTY": 22000.0,
    "BANKNIFTY": 45000.0,
    "INFY": 1450.0,
    "HDFCBANK": 1600.0,
    "SBIN": 580.0,
    "ICICIBANK": 950.0,
    "HINDUNILVR": 2400.0,
    "ITC": 420.0,
    "GOLD": 78000.0,
    "SILVER": 92000.0,
    "CRUDEOIL": 5800.0,
}


class PaperBroker(IBrokerPort):
    """
    Paper trading broker implementation.

    Simulates broker operations without real API calls.
    All operations are performed in-memory.
    """

    def __init__(self, prices: Dict[str, float] = None):
        """
        Initialize paper broker.

        Args:
            prices: Optional custom price dict (symbol -> price)
        """
        self._prices = DEFAULT_PRICES.copy()
        if prices:
            self._prices.update(prices)
        self._running = True

        self._order_counter = 0
        self._positions: List[Position] = []
        self._orders: List[Order] = []

    def _get_price(self, symbol: str) -> float:
        """Get simulated price for symbol with small variation."""
        base_price = self._prices.get(symbol.upper(), 100.0)
        variation = base_price * 0.001 * random.uniform(-1, 1)
        return round(base_price + variation, 2)

    # -------------------------------------------------------------------------
    # Market Data - Synchronous
    # -------------------------------------------------------------------------

    def get_quote(self, instrument: Instrument) -> Quote:
        """Get simulated quote for instrument."""
        price = self._get_price(instrument.symbol)

        return Quote(
            instrument=instrument,
            ltp=price,
            bid=round(price - 1, 2),
            ask=round(price + 1, 2),
            volume=random.randint(100000, 10000000),
            open=round(price - 10, 2),
            high=round(price + 20, 2),
            low=round(price - 15, 2),
            close=round(price - 5, 2),
            timestamp=datetime.now(),
            oi=None,
        )

    def get_quotes_batch(
        self, instruments: List[Instrument]
    ) -> Dict[Instrument, Quote]:
        """Get simulated quotes for multiple instruments."""
        return {inst: self.get_quote(inst) for inst in instruments}

    def get_historical(
        self,
        instrument: Instrument,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        include_oi: bool = False,
    ):
        """Get simulated historical data."""
        import pandas as pd

        dates = pd.date_range(from_date, to_date, freq="D")
        price = self._get_price(instrument.symbol)

        data = {
            "timestamp": dates,
            "open": [price + i for i in range(len(dates))],
            "high": [price + i + 5 for i in range(len(dates))],
            "low": [price + i - 5 for i in range(len(dates))],
            "close": [price + i + 2 for i in range(len(dates))],
            "volume": [1000000 + i * 10000 for i in range(len(dates))],
        }
        if include_oi:
            data["oi"] = [0] * len(dates)

        return pd.DataFrame(data)

    # -------------------------------------------------------------------------
    # Streaming - Asynchronous
    # -------------------------------------------------------------------------

    def close(self) -> None:
        """Stop streaming loops and clean up."""
        self._running = False

    async def stream_ticker(self, instruments: List[Instrument]) -> AsyncIterator[Tick]:
        """Stream simulated ticker data."""
        while self._running:
            for inst in instruments:
                price = self._get_price(inst.symbol)
                spread = price * 0.0002  # 0.02% synthetic spread
                yield Tick(
                    instrument=inst,
                    price=price,
                    volume=random.randint(100, 10000),
                    timestamp=datetime.now(),
                    bid=round(price - spread, 2),
                    ask=round(price + spread, 2),
                )
            await asyncio.sleep(0.05)  # 50ms between ticks

    async def stream_quotes(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[Quote]:
        """Stream simulated quote data."""
        while self._running:
            for inst in instruments:
                yield self.get_quote(inst)
            await asyncio.sleep(0.05)

    async def stream_depth(
        self, instruments: List[Instrument], depth_level: int = 20
    ) -> AsyncIterator[MarketDepth]:
        """Stream simulated 20-level market depth data."""
        while self._running:
            for inst in instruments:
                quote = self.get_quote(inst)

                # Generate simulated bid levels
                bid_levels = []
                for i in range(min(depth_level, 20)):
                    bid_levels.append(
                        DepthLevel(
                            price=quote.bid - (i * 0.05),
                            quantity=random.randint(100, 10000),
                            orders=random.randint(1, 50),
                        )
                    )

                # Generate simulated ask levels
                ask_levels = []
                for i in range(min(depth_level, 20)):
                    ask_levels.append(
                        DepthLevel(
                            price=quote.ask + (i * 0.05),
                            quantity=random.randint(100, 10000),
                            orders=random.randint(1, 50),
                        )
                    )

                # Yield bid depth
                yield MarketDepth(
                    symbol=inst.symbol,
                    security_id=inst.security_id,
                    side="bid",
                    levels=bid_levels,
                    timestamp=datetime.now(),
                )

                # Yield ask depth
                yield MarketDepth(
                    symbol=inst.symbol,
                    security_id=inst.security_id,
                    side="ask",
                    levels=ask_levels,
                    timestamp=datetime.now(),
                )

            await asyncio.sleep(0.1)

    # -------------------------------------------------------------------------
    # Options
    # -------------------------------------------------------------------------

    def get_option_chain(
        self, underlying: str, exchange: Exchange, expiry_index: int = 0
    ) -> OptionChain:
        """Get simulated option chain."""
        from brokers.broker.entities import Option

        spot = self._get_price(underlying)

        # Use shared market_info for step sizes
        from brokers.broker.market_info import get_step_size as _get_step
        step_size = _get_step(underlying)

        # ATM rounded to step
        atm = round(spot / step_size) * step_size
        strikes = [atm + i * step_size for i in range(-5, 6)]  # ATM ± 5 strikes

        # Nearest future weekly Thursday (expiry_index weeks out)
        today = datetime.now()
        days_until_thursday = (3 - today.weekday()) % 7
        if days_until_thursday == 0:
            days_until_thursday = 7
        base_expiry = today + timedelta(days=days_until_thursday + expiry_index * 7)
        expiry = base_expiry.replace(hour=15, minute=30, second=0, microsecond=0)

        calls: dict = {}
        puts: dict = {}

        for strike in strikes:
            moneyness = spot - strike
            ce_ltp = max(0.05, round(moneyness if moneyness > 0 else abs(moneyness) * 0.1, 2))
            pe_ltp = max(0.05, round(-moneyness if moneyness < 0 else abs(moneyness) * 0.1, 2))
            spread = 0.5

            calls[strike] = Option(
                symbol=f"{underlying}{expiry.strftime('%d%b%y').upper()}{int(strike)}CE",
                security_id=f"OPT{int(strike)}CE",
                strike=strike,
                option_type="CE",
                expiry=expiry,
                ltp=ce_ltp,
                bid=round(ce_ltp - spread, 2),
                ask=round(ce_ltp + spread, 2),
                oi=random.randint(10000, 500000),
                volume=random.randint(1000, 50000),
            )
            puts[strike] = Option(
                symbol=f"{underlying}{expiry.strftime('%d%b%y').upper()}{int(strike)}PE",
                security_id=f"OPT{int(strike)}PE",
                strike=strike,
                option_type="PE",
                expiry=expiry,
                ltp=pe_ltp,
                bid=round(pe_ltp - spread, 2),
                ask=round(pe_ltp + spread, 2),
                oi=random.randint(10000, 500000),
                volume=random.randint(1000, 50000),
            )

        underlying_inst = Instrument(
            symbol=underlying, exchange=exchange, security_id=""
        )

        return OptionChain(
            underlying=underlying_inst,
            expiry=expiry,
            spot_price=spot,
            atm_strike=atm,
            step_size=step_size,
            calls=calls,
            puts=puts,
        )

    def get_expiry_list(self, underlying: str, exchange: Exchange) -> List[datetime]:
        """Get simulated expiry dates (4 weekly Thursdays from today)."""
        today = datetime.now()
        days_until_thursday = (3 - today.weekday()) % 7
        if days_until_thursday == 0:
            days_until_thursday = 7
        return [
            (today + timedelta(days=days_until_thursday + i * 7)).replace(
                hour=15, minute=30, second=0, microsecond=0
            )
            for i in range(4)
        ]

    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------

    def place_order(self, order: Order) -> Order:
        """Place simulated order - immediately fills."""
        self._order_counter += 1

        order.order_id = f"PAPER_{self._order_counter:06d}"
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.timestamp = datetime.now()

        self._orders.append(order)

        # Update positions
        self._update_position(order)

        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel simulated order."""
        for order in self._orders:
            if order.order_id == order_id:
                order.status = OrderStatus.CANCELLED
                return True
        return False

    def get_order_status(self, order_id: str) -> Order:
        """Get simulated order status."""
        for order in self._orders:
            if order.order_id == order_id:
                return order
        raise ValueError(f"Order not found: {order_id}")

    # -------------------------------------------------------------------------
    # Portfolio
    # -------------------------------------------------------------------------

    def get_positions(self) -> List[Position]:
        """Get simulated positions."""
        return [p for p in self._positions if p.quantity != 0]

    def get_orderbook(self) -> List[Order]:
        """Get simulated orderbook."""
        return self._orders.copy()

    # -------------------------------------------------------------------------
    # Private Methods
    # -------------------------------------------------------------------------

    def _update_position(self, order: Order):
        """Update position after order fill."""
        for pos in self._positions:
            if pos.instrument.symbol == order.instrument.symbol:
                if order.side.value == "BUY":
                    pos.quantity += order.quantity
                    pos.avg_price = (
                        (
                            pos.avg_price * (pos.quantity - order.quantity)
                            + order.price * order.quantity
                        )
                        / pos.quantity
                        if pos.quantity > 0
                        else order.price
                    )
                else:
                    pos.quantity -= order.quantity
                return

        # New position
        if order.side.value == "BUY":
            self._positions.append(
                Position(
                    instrument=order.instrument,
                    side=order.side,
                    quantity=order.quantity,
                    avg_price=order.price or self._get_price(order.instrument.symbol),
                )
            )
        else:
            self._positions.append(
                Position(
                    instrument=order.instrument,
                    side=order.side,
                    quantity=-order.quantity,
                    avg_price=order.price or self._get_price(order.instrument.symbol),
                )
            )
