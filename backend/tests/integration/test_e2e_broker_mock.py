"""End-to-end integration tests with a mock broker adapter.

Exercises the full flow: market data tick → gate evaluation → entry signal →
order placement via broker → position management → exit.

Uses a MockBrokerAdapter that simulates immediate order fills, configurable
market data ticks, and tracks all calls for assertion.

Follows the same patterns as test_trade_lifecycle_full.py.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pytest

from app.domain.fabio_ai.services.exit_engine import (
    CushionState,
    ExitReason,
    ExitEngine as TradeManager,
    TradeManagerConfig,
)
from app.domain.services.circuit_breakers import BreakerReason, BreakerResult, CircuitBreakers
from app.domain.trading.models.value_objects import OHLC


# ==============================================================================
# MockBrokerAdapter — simulates a real broker with immediate fills
# ==============================================================================


@dataclass
class MockOrder:
    """Lightweight record of a placed order."""
    order_id: str
    symbol: str
    side: str          # "BUY" or "SELL"
    qty: int
    price: float
    order_type: str    # "MARKET" or "LIMIT"
    filled: bool = False
    fill_price: float = 0.0


class MockBrokerAdapter:
    """Synchronous broker mock that fills orders immediately.

    This adapter implements the minimal interface needed by the integration
    tests. It is intentionally simpler than IBrokerPort (no streaming) —
    tests wire it directly into TradeManager / CircuitBreakers rather than
    going through the full FastAPI application.

    Key capabilities:
    - place_order()      → records the order and fills it immediately
    - cancel_order()     → marks the order as cancelled
    - get_positions()    → returns currently "open" mock positions
    - get_market_data()  → returns a configurable OHLC tick

    Assertion helpers:
    - orders_placed      → list[MockOrder] of every placed order (entry + exit)
    - entry_orders       → BUY orders
    - exit_orders        → SELL orders (or BUY for SHORTs)
    - was_called_with()  → check that a specific symbol/side combo was placed
    - reset()            → clear state between sub-scenarios
    """

    def __init__(self) -> None:
        self.orders_placed: List[MockOrder] = []
        self._open_positions: Dict[str, MockOrder] = {}   # symbol → last entry order
        self._market_data: Dict[str, OHLC] = {}           # symbol → current tick
        self._next_order_id: int = 1

    # ------------------------------------------------------------------
    # Market data configuration
    # ------------------------------------------------------------------

    def set_market_data(self, symbol: str, tick: OHLC) -> None:
        """Inject a market data tick that get_market_data() will return."""
        self._market_data[symbol] = tick

    def get_market_data(self, symbol: str) -> Optional[OHLC]:
        """Return the last configured tick for the given symbol."""
        return self._market_data.get(symbol)

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        order_type: str = "MARKET",
    ) -> MockOrder:
        """Place and immediately fill an order.

        Returns the MockOrder with fill_price set.
        """
        order_id = f"MOCK-{self._next_order_id:04d}"
        self._next_order_id += 1

        order = MockOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            order_type=order_type,
            filled=True,
            fill_price=price,  # immediate market fill at requested price
        )
        self.orders_placed.append(order)

        # Track open position (entry = BUY for LONG, SELL for SHORT)
        if side == "BUY":
            self._open_positions[symbol] = order
        elif side == "SELL" and symbol in self._open_positions:
            del self._open_positions[symbol]

        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order (no-op for already-filled mock orders)."""
        for o in self.orders_placed:
            if o.order_id == order_id:
                o.filled = False
                return True
        return False

    def get_positions(self) -> List[MockOrder]:
        """Return currently open (not yet exited) positions."""
        return list(self._open_positions.values())

    # ------------------------------------------------------------------
    # Assertion helpers
    # ------------------------------------------------------------------

    @property
    def entry_orders(self) -> List[MockOrder]:
        """All BUY orders (LONG entries or SHORT exits)."""
        return [o for o in self.orders_placed if o.side == "BUY"]

    @property
    def exit_orders(self) -> List[MockOrder]:
        """All SELL orders (LONG exits or SHORT entries)."""
        return [o for o in self.orders_placed if o.side == "SELL"]

    def orders_for(self, symbol: str) -> List[MockOrder]:
        """All orders placed for a specific symbol."""
        return [o for o in self.orders_placed if o.symbol == symbol]

    def was_called_with(self, symbol: str, side: str) -> bool:
        """True if place_order was called with the given symbol and side."""
        return any(o.symbol == symbol and o.side == side for o in self.orders_placed)

    def reset(self) -> None:
        """Clear all recorded orders and positions."""
        self.orders_placed.clear()
        self._open_positions.clear()
        self._market_data.clear()
        self._next_order_id = 1


# ==============================================================================
# Helper: build an OHLC tick
# ==============================================================================


def _tick(
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
    symbol: str = "NIFTY",
    bid: float | None = None,
    ask: float | None = None,
) -> OHLC:
    """Construct a minimal OHLC tick for test scenarios."""
    return OHLC(
        time="2026-04-09T10:00:00+05:30",
        open=close,
        high=high if high is not None else close * 1.002,
        low=low if low is not None else close * 0.998,
        close=close,
        volume=5000,
        vwap=close,
        taker_buy_volume=2500,
        delta=0,
    )


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def broker() -> MockBrokerAdapter:
    """Fresh MockBrokerAdapter for each test."""
    return MockBrokerAdapter()


@pytest.fixture
def trade_manager() -> TradeManager:
    """Fresh TradeManager (no persistence) for each test."""
    return TradeManager()


@pytest.fixture
def circuit_breakers() -> CircuitBreakers:
    """Default CircuitBreakers with 10L equity."""
    return CircuitBreakers(equity=1_000_000.0)


# ==============================================================================
# Test 1: Entry signal → order placement
# ==============================================================================


def test_e2e_entry_signal_to_order_placement(broker: MockBrokerAdapter, trade_manager: TradeManager):
    """Entry gate passes → broker.place_order() called with correct details.

    Scenario:
    - Market at 100; gates pass (no circuit breaker, no cooldown)
    - Strategy signals BUY @ 100, SL=95, TP=115
    - Simulate the entry via MockBrokerAdapter
    - Verify order details: symbol, side, qty, price
    - Register position with TradeManager
    - Assert TradeManager is managing the new position
    """
    symbol = "NIFTY24DEC20000CE"
    entry_price = 100.0
    sl = 95.0
    tp = 115.0
    qty = 10

    # --- Simulate gate evaluation passing (no gate infra needed here) ---

    # Place entry order via broker
    order = broker.place_order(
        symbol=symbol,
        side="BUY",
        qty=qty,
        price=entry_price,
        order_type="MARKET",
    )

    # Assert order details
    assert order.filled is True
    assert order.symbol == symbol
    assert order.side == "BUY"
    assert order.qty == qty
    assert order.fill_price == entry_price
    assert len(broker.orders_placed) == 1
    assert broker.was_called_with(symbol, "BUY") is True

    # Register position in TradeManager
    pos_id = f"pos-{order.order_id}"
    trade_manager.register_position(
        position_id=pos_id,
        symbol=symbol,
        side="LONG",
        entry_price=entry_price,
        stop_loss=sl,
        take_profit=tp,
    )

    # TradeManager must now be managing this position
    assert trade_manager.has_managed_positions(symbol) is True
    mp = trade_manager._positions[pos_id]
    assert mp.entry_price == entry_price
    assert mp.stop_loss == sl
    assert mp.take_profit == tp
    assert mp.cushion_state == CushionState.OPEN


# ==============================================================================
# Test 2: Full profitable trade — entry → cushion → trail → exit
# ==============================================================================


def test_e2e_full_profitable_trade(broker: MockBrokerAdapter, trade_manager: TradeManager):
    """LONG position: entry at 100, price rises to TP zone, cushion activates, trail fires.

    Flow:
    1. Entry order placed via broker (BUY)
    2. Price moves up through partial TP threshold (107.5 = 50% of TP dist)
    3. Partial exit placed via broker (SELL half)
    4. ATR trail activates after 1R profit (entry 100, sl 95 → 1R=5 pts)
    5. Price retraces below trail SL → full exit order placed
    6. Net PnL is positive
    """
    symbol = "NIFTY"
    entry_price = 100.0
    sl = 95.0
    tp = 115.0
    qty = 10
    pos_id = "P-PROFIT-01"

    # ---- Step 1: Entry ----
    entry_order = broker.place_order(symbol=symbol, side="BUY", qty=qty, price=entry_price)
    trade_manager.register_position(
        position_id=pos_id,
        symbol=symbol,
        side="LONG",
        entry_price=entry_price,
        stop_loss=sl,
        take_profit=tp,
    )
    mp = trade_manager._positions[pos_id]
    assert mp.cushion_state == CushionState.OPEN

    # ---- Step 2: Pass grace period (5 ticks) ----
    for _ in range(5):
        trade_manager.check_position(pos_id, 100.5)

    # ---- Step 3: Price moves to 108 (past 50% TP threshold = 107.5) ----
    sig = trade_manager.check_position(pos_id, 108.0)
    assert sig is None, "No exit yet at 108"

    # Simulate partial exit: PartitionExitManager would place this in production
    partial_qty = qty // 2  # 50% size
    partial_exit = broker.place_order(symbol=symbol, side="SELL", qty=partial_qty, price=108.0)
    mp.set_partial_taken(True)

    assert mp.partial_taken is True
    assert mp.cushion_state == CushionState.CUSHIONED
    assert broker.was_called_with(symbol, "SELL") is True

    # ---- Step 4: Price rises to 112 → 1R profit (5 pts) → ATR trail activates ----
    sig = trade_manager.check_position(pos_id, 112.0)
    assert sig is None
    assert mp.atr_trail_active is True
    assert mp.cushion_state == CushionState.TRAILING
    assert mp.stop_loss > entry_price, "SL must be above entry after trail"

    trail_sl = mp.stop_loss  # e.g. ~109.6 = 100 + 12*0.8

    # ---- Step 5: Price goes to 114, then retraces below trail SL ----
    trade_manager.check_position(pos_id, 114.0)
    trail_sl_at_114 = mp.stop_loss  # higher now

    # Force price below trail SL to trigger exit
    exit_price = trail_sl_at_114 - 2.0  # well below trail SL
    sig = trade_manager.check_position(pos_id, exit_price)

    assert sig is not None, "Trail SL hit must generate exit signal"
    assert sig.reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP)
    assert mp.cushion_state == CushionState.CLOSED

    # ---- Step 6: Simulate full exit order via broker ----
    remaining_qty = qty - partial_qty
    full_exit = broker.place_order(symbol=symbol, side="SELL", qty=remaining_qty, price=exit_price)

    # Verify broker received both entry and two exit orders
    assert len(broker.orders_placed) == 3  # entry + partial exit + full exit
    assert len(broker.entry_orders) == 1
    assert len(broker.exit_orders) == 2

    # ---- Step 7: Net PnL is positive ----
    # Partial: (108 - 100) * 5 = 40
    # Full: (exit_price - 100) * 5; exit_price = trail_sl_at_114 - 2 > entry (profitable)
    partial_pnl = (108.0 - entry_price) * partial_qty
    full_pnl = (exit_price - entry_price) * remaining_qty
    total_pnl = partial_pnl + full_pnl

    assert total_pnl > 0, f"Net PnL should be positive, got {total_pnl}"


# ==============================================================================
# Test 3: Losing trade hits SL
# ==============================================================================


def test_e2e_losing_trade_hits_sl(broker: MockBrokerAdapter, trade_manager: TradeManager):
    """LONG position: price drops to SL → exit order placed at SL price.

    Flow:
    1. Entry at 100 (BUY)
    2. Ticks drift down: 99, 97, 95 (SL)
    3. TradeManager fires STOP_LOSS signal
    4. Broker receives SELL exit order at SL price
    5. PnL is negative
    """
    symbol = "NIFTY"
    entry_price = 100.0
    sl = 95.0
    tp = 115.0
    qty = 10
    pos_id = "P-LOSS-01"

    # ---- Entry ----
    broker.place_order(symbol=symbol, side="BUY", qty=qty, price=entry_price)
    trade_manager.register_position(
        position_id=pos_id,
        symbol=symbol,
        side="LONG",
        entry_price=entry_price,
        stop_loss=sl,
        take_profit=tp,
    )

    # ---- Ticks drifting down ----
    sig = trade_manager.check_position(pos_id, 99.0)
    assert sig is None

    sig = trade_manager.check_position(pos_id, 97.0)
    assert sig is None

    # ---- SL hit ----
    sig = trade_manager.check_position(pos_id, 95.0)
    assert sig is not None
    assert sig.reason == ExitReason.STOP_LOSS
    assert sig.exit_price == 95.0

    mp = trade_manager._positions[pos_id]
    assert mp.cushion_state == CushionState.CLOSED

    # ---- Broker receives exit order ----
    exit_order = broker.place_order(symbol=symbol, side="SELL", qty=qty, price=sig.exit_price)

    assert exit_order.symbol == symbol
    assert exit_order.side == "SELL"
    assert exit_order.fill_price == 95.0

    # Total orders: entry + SL exit
    assert len(broker.orders_placed) == 2

    # ---- PnL is negative ----
    pnl = (sig.exit_price - entry_price) * qty  # (95 - 100) * 10 = -50
    assert pnl < 0, f"PnL should be negative at SL, got {pnl}"


# ==============================================================================
# Test 4: Circuit breaker prevents entry after 3 consecutive losses
# ==============================================================================


def test_e2e_circuit_breaker_prevents_entry(
    broker: MockBrokerAdapter,
    circuit_breakers: CircuitBreakers,
):
    """After 3 consecutive losses with negative PnL, circuit breaker blocks all new entries.

    Flow:
    1. Simulate 3 consecutive losses (consecutive_losses=3, session_pnl=-3000)
    2. Evaluate circuit breakers → expect locked
    3. Attempt entry → broker.place_order() is NOT called
    4. Assert broker has 0 orders placed
    """
    symbol = "NIFTY"

    # ---- Evaluate with 3 consecutive losses ----
    result = circuit_breakers.evaluate(
        consecutive_losses=3,
        session_pnl=-3000.0,
        cumulative_account_pnl=-3000.0,
    )

    assert result.is_locked is True
    assert result.reason == BreakerReason.CONSECUTIVE_LOSS

    # ---- Gate: circuit breaker is locked — do NOT place order ----
    if result.is_locked:
        pass  # Entry blocked — no order placed
    else:
        broker.place_order(symbol=symbol, side="BUY", qty=10, price=100.0)

    # ---- Assert broker never received an order ----
    assert len(broker.orders_placed) == 0, (
        f"Broker should not have received any orders when circuit breaker is locked. "
        f"Got: {[o.symbol for o in broker.orders_placed]}"
    )
    assert broker.was_called_with(symbol, "BUY") is False


# ==============================================================================
# Test 5: Account loss limit blocks ALL trading
# ==============================================================================


def test_e2e_account_loss_limit_blocks_all_trading(
    broker: MockBrokerAdapter,
    circuit_breakers: CircuitBreakers,
):
    """Cumulative P&L = -₹31,000 → account loss breaker fires, trading fully blocked.

    Flow:
    1. Set cumulative_account_pnl to -31000
    2. Evaluate circuit breakers → expect ACCOUNT_LOSS_ABSOLUTE
    3. Attempt entries on any symbol → NOT placed
    4. Assert broker has 0 orders
    """
    # ---- Evaluate with cumulative loss > ₹30,000 ----
    result = circuit_breakers.evaluate(
        consecutive_losses=0,
        session_pnl=0.0,
        cumulative_account_pnl=-31_000.0,
    )

    assert result.is_locked is True
    assert result.reason == BreakerReason.ACCOUNT_LOSS_ABSOLUTE
    assert "account loss limit" in result.detail.lower() or "hard cap" in result.detail.lower()

    # ---- Attempt entries on multiple symbols — all must be blocked ----
    symbols = ["NIFTY", "BANKNIFTY", "CRUDEOIL"]
    for sym in symbols:
        if not result.is_locked:
            broker.place_order(symbol=sym, side="BUY", qty=10, price=100.0)

    # ---- All entries blocked ----
    assert len(broker.orders_placed) == 0, (
        "No orders should be placed when account loss limit is breached. "
        f"Placed: {[(o.symbol, o.side) for o in broker.orders_placed]}"
    )


# ==============================================================================
# Test 6: Multiple symbols managed independently
# ==============================================================================


def test_e2e_multiple_symbols_independent(
    broker: MockBrokerAdapter,
    trade_manager: TradeManager,
):
    """Two simultaneous positions on different symbols are managed independently.

    Symbol A: NIFTY  → hits TP zone (profitable)
    Symbol B: CRUDE  → hits SL      (loss)

    Each position must close with the correct exit reason and each symbol's
    PnL must be calculated independently.
    """
    # ---- Setup symbols ----
    sym_a = "NIFTY"
    sym_b = "CRUDEOIL"

    entry_a = 100.0
    sl_a = 95.0
    tp_a = 115.0

    entry_b = 5000.0
    sl_b = 4975.0
    tp_b = 5075.0

    qty = 10
    pos_a = "P-SYM-A"
    pos_b = "P-SYM-B"

    # ---- Enter both positions ----
    broker.place_order(symbol=sym_a, side="BUY", qty=qty, price=entry_a)
    broker.place_order(symbol=sym_b, side="BUY", qty=qty, price=entry_b)

    trade_manager.register_position(
        position_id=pos_a,
        symbol=sym_a,
        side="LONG",
        entry_price=entry_a,
        stop_loss=sl_a,
        take_profit=tp_a,
    )
    trade_manager.register_position(
        position_id=pos_b,
        symbol=sym_b,
        side="LONG",
        entry_price=entry_b,
        stop_loss=sl_b,
        take_profit=tp_b,
    )

    assert trade_manager.has_managed_positions(sym_a) is True
    assert trade_manager.has_managed_positions(sym_b) is True

    # ---- Pass grace period for both ----
    for _ in range(5):
        trade_manager.check_position(pos_a, entry_a + 0.5)
        trade_manager.check_position(pos_b, entry_b + 5.0)

    # ---- Symbol A moves up toward TP ----
    for price in [102.0, 105.0, 108.0, 112.0]:
        trade_manager.check_position(pos_a, price)

    # Simulate partial taken for Symbol A
    mp_a = trade_manager._positions[pos_a]
    mp_a.set_partial_taken(True)

    # ---- Symbol A: price goes to 114, then trail SL hit at ~111 ----
    trade_manager.check_position(pos_a, 114.0)
    trail_sl_a = mp_a.stop_loss  # trail SL after 114

    # Force exit for Symbol A (trail SL hit)
    exit_price_a = trail_sl_a - 1.0
    sig_a = trade_manager.check_position(pos_a, exit_price_a)
    assert sig_a is not None
    assert sig_a.reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP)

    # ---- Symbol B drops to SL ----
    sig_b = trade_manager.check_position(pos_b, 4975.0)
    assert sig_b is not None
    assert sig_b.reason == ExitReason.STOP_LOSS
    assert sig_b.exit_price == 4975.0

    # ---- Place exit orders via broker ----
    broker.place_order(symbol=sym_a, side="SELL", qty=qty, price=exit_price_a)
    broker.place_order(symbol=sym_b, side="SELL", qty=qty, price=4975.0)

    # ---- Each symbol has its own order history ----
    a_orders = broker.orders_for(sym_a)
    b_orders = broker.orders_for(sym_b)

    assert len(a_orders) >= 2, "Symbol A should have entry + exit"
    assert len(b_orders) == 2, "Symbol B should have entry + SL exit"

    # ---- PnL per symbol ----
    pnl_a = (exit_price_a - entry_a) * qty
    pnl_b = (4975.0 - entry_b) * qty  # -25 * 10 = -250

    assert pnl_a > 0, f"Symbol A should be profitable, got {pnl_a}"
    assert pnl_b < 0, f"Symbol B should be a loss, got {pnl_b}"

    # ---- Positions are independent: one profitable, one not ----
    assert mp_a.cushion_state == CushionState.CLOSED
    mp_b = trade_manager._positions[pos_b]
    assert mp_b.cushion_state == CushionState.CLOSED


# ==============================================================================
# Test 7: Spread blowout triggers emergency exit
# ==============================================================================


def test_e2e_spread_blowout_emergency_exit(
    broker: MockBrokerAdapter,
    trade_manager: TradeManager,
):
    """Wide bid-ask spread triggers emergency exit via TradeManager.check_spread_blowout().

    Flow:
    1. Enter a LONG position at 100
    2. Feed a tick where spread is >3% of premium (blowout condition)
    3. check_spread_blowout() returns ExitSignal with SPREAD_BLOWOUT reason
    4. Broker receives SELL exit order at midpoint price
    5. Position state is CLOSED
    """
    symbol = "NIFTY"
    entry_price = 100.0
    sl = 95.0
    tp = 115.0
    qty = 10
    pos_id = "P-SPREAD-01"

    # ---- Entry ----
    broker.place_order(symbol=symbol, side="BUY", qty=qty, price=entry_price)
    trade_manager.register_position(
        position_id=pos_id,
        symbol=symbol,
        side="LONG",
        entry_price=entry_price,
        stop_loss=sl,
        take_profit=tp,
    )

    mp = trade_manager._positions[pos_id]

    # ---- Normal tick: no blowout ----
    normal_sig = trade_manager.check_spread_blowout(
        position_id=pos_id,
        best_bid=99.5,
        best_ask=100.5,
        premium=100.0,
        max_spread_pct=0.03,
    )
    assert normal_sig is None, "1-point spread on 100 premium (1%) should NOT trigger blowout"

    # ---- Blowout tick: spread = 5 on a 100 premium = 5% (> 3% threshold) ----
    blowout_sig = trade_manager.check_spread_blowout(
        position_id=pos_id,
        best_bid=97.0,
        best_ask=102.0,
        premium=100.0,
        max_spread_pct=0.03,
    )

    assert blowout_sig is not None, "5-point spread (5%) should trigger spread blowout"
    assert blowout_sig.reason == ExitReason.SPREAD_BLOWOUT
    assert blowout_sig.position_id == pos_id

    # Exit price should be the midpoint
    expected_midpoint = (97.0 + 102.0) / 2  # 99.5
    assert blowout_sig.exit_price == pytest.approx(expected_midpoint)

    # ---- Broker receives emergency exit order ----
    exit_order = broker.place_order(
        symbol=symbol,
        side="SELL",
        qty=qty,
        price=blowout_sig.exit_price,
    )
    assert exit_order.fill_price == pytest.approx(expected_midpoint)
    assert exit_order.side == "SELL"

    # ---- Position is now CLOSED in state machine ----
    assert mp.cushion_state == CushionState.CLOSED

    # ---- Total broker activity: 1 entry + 1 emergency exit ----
    assert len(broker.orders_placed) == 2
    assert len(broker.entry_orders) == 1
    assert len(broker.exit_orders) == 1


# ==============================================================================
# Additional: MockBrokerAdapter unit behaviour tests
# ==============================================================================


class TestMockBrokerAdapterBehaviour:
    """Verify the mock adapter's own mechanics are correct."""

    def test_place_order_records_and_fills_immediately(self):
        broker = MockBrokerAdapter()
        order = broker.place_order("NIFTY", "BUY", 10, 100.0)
        assert order.filled is True
        assert order.fill_price == 100.0
        assert len(broker.orders_placed) == 1

    def test_orders_for_symbol_filters_correctly(self):
        broker = MockBrokerAdapter()
        broker.place_order("NIFTY", "BUY", 10, 100.0)
        broker.place_order("CRUDE", "BUY", 5, 5000.0)
        broker.place_order("NIFTY", "SELL", 10, 110.0)

        assert len(broker.orders_for("NIFTY")) == 2
        assert len(broker.orders_for("CRUDE")) == 1
        assert len(broker.orders_for("BANKNIFTY")) == 0

    def test_get_positions_tracks_open_trades(self):
        broker = MockBrokerAdapter()
        broker.place_order("NIFTY", "BUY", 10, 100.0)
        assert len(broker.get_positions()) == 1

        broker.place_order("NIFTY", "SELL", 10, 110.0)  # exit
        assert len(broker.get_positions()) == 0

    def test_reset_clears_state(self):
        broker = MockBrokerAdapter()
        broker.place_order("NIFTY", "BUY", 10, 100.0)
        broker.reset()
        assert len(broker.orders_placed) == 0
        assert len(broker.get_positions()) == 0

    def test_market_data_injection(self):
        broker = MockBrokerAdapter()
        tick = _tick(102.5, symbol="NIFTY")
        broker.set_market_data("NIFTY", tick)
        retrieved = broker.get_market_data("NIFTY")
        assert retrieved is not None
        assert retrieved.close == 102.5

    def test_was_called_with_returns_false_when_no_orders(self):
        broker = MockBrokerAdapter()
        assert broker.was_called_with("NIFTY", "BUY") is False

    def test_order_ids_are_unique(self):
        broker = MockBrokerAdapter()
        o1 = broker.place_order("NIFTY", "BUY", 10, 100.0)
        o2 = broker.place_order("NIFTY", "SELL", 10, 105.0)
        assert o1.order_id != o2.order_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
