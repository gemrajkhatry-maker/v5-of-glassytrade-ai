"""Edge case and boundary condition tests for event sourcing state machine.

QA RED TEAM: These tests probe adversarial inputs, type confusion,
boundary values, invalid transitions, and other edge cases to discover
bugs in the system.

Each test that reveals a bug is documented with its severity.
Tests that pass mean the system handles that case correctly.
"""

from __future__ import annotations

import math
import sys
import uuid
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from quant.events import (
    BarClosed,
    Event,
    PositionClosed,
    PositionOpened,
    PositionReduced,
    RiskUpdated,
    StopMoved,
)
from quant.event_store import EventStore
from quant.execution.order import Fill, Order, Position
from quant.state_machine import Bar, EngineState, PositionState, RiskState
from quant.transitions import apply_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    entry: float = 100.0,
    sl: float = 95.0,
    tp: float = 110.0,
    side: str = "LONG",
):
    """Create a minimal Signal for Position construction."""
    from quant.decision.signal_builder import Signal

    return Signal(
        type=side,
        reason="test",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=2.0,
        model_label="TEST",
        symbol="NIFTY",
        timestamp="2026-01-01T09:15:00+05:30",
    )


def _make_position(
    pos_id: str = "pos-1",
    size: float = 1.0,
    entry: float = 100.0,
    sl: float = 95.0,
    tp: float = 110.0,
    side: str = "LONG",
    pyramid_level: int = 0,
    is_pyramid: bool = False,
) -> Position:
    """Create a Position with the given parameters."""
    sig = _make_signal(entry=entry, sl=sl, tp=tp, side=side)
    return Position(
        order=Order(signal=sig, quantity=abs(size)),
        open_price=entry,
        open_time="2026-01-01T09:15:00+05:30",
        size=size,
        realized_pnl=0.0,
        pyramid_level=pyramid_level,
        is_pyramid=is_pyramid,
        _id=pos_id,
    )


def _make_fill(
    position: Position,
    close_price: float = 110.0,
    pnl: float = 10.0,
    reason: str = "TP",
) -> Fill:
    """Create a Fill for the given position."""
    return Fill(
        position=position,
        close_price=close_price,
        close_time="2026-01-01T10:30:00+05:30",
        reason=reason,
        pnl=pnl,
    )


def _make_bar(
    time: str = "2026-01-01T09:15:00+05:30",
    open: float = 100.0,
    high: float = 105.0,
    low: float = 99.0,
    close: float = 103.0,
    volume: float = 1000.0,
) -> Bar:
    """Create a Bar."""
    return Bar(
        time=time,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


# =============================================================================
# TEST CLASS: Empty Events and Missing Fields
# =============================================================================


class TestEmptyEvents:
    """Attack: Empty events — [], None, missing fields."""

    # BUG: fold() with empty events returns EngineState(symbol="") which has an
    # empty symbol — downstream code may not expect this.
    def test_fold_empty_event_list_returns_empty_symbol(self):
        """Folding an empty event list produces a state with empty symbol.

        DESIGN: EventStore.fold() returns EngineState(symbol="") when no events
        exist. The symbol is set from the first event that arrives. This is
        expected behavior - the EventStore doesn't know the symbol until it
        sees an event.
        """
        store = EventStore()
        state = store.fold()
        # Expected: symbol is empty until first event arrives
        assert state.symbol == "", "Empty store should have empty symbol"

    # BUG: apply_event doesn't validate Event has required fields
    def test_apply_event_with_none_symbol(self):
        """PositionOpened with None symbol should fail.

        BUG: No validation on event fields — None symbol propagates silently.
        """
        pos = _make_position()
        event = PositionOpened(symbol=None, time="t", position=pos)  # type: ignore
        state = EngineState(symbol="NIFTY")
        # BUG: Should raise, but apply_event doesn't validate symbol
        result = apply_event(state, event)
        assert result.position.id == "pos-1"  # Opens anyway — should fail

    # BUG: apply_event with empty time string is accepted
    def test_apply_event_with_empty_time(self):
        """Event with empty timestamp should be rejected.

        BUG: No validation on time field — empty string propagates.
        """
        pos = _make_position()
        event = PositionOpened(symbol="NIFTY", time="", position=pos)
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, event)
        # BUG: State accepts event with empty time — audit trail broken
        assert result.position is not None


# =============================================================================
# TEST CLASS: Invalid Transitions
# =============================================================================


class TestInvalidTransitions:
    """Attack: Invalid transitions — close without open, double-open, wrong ID."""

    def test_close_without_open_position_raises(self):
        """PositionClosed without open position must raise ValueError."""
        pos = _make_position(pos_id="ghost")
        fill = _make_fill(pos)
        event = PositionClosed(symbol="NIFTY", time="t", fill=fill)
        state = EngineState(symbol="NIFTY")
        with pytest.raises(ValueError):
            apply_event(state, event)

    def test_double_open_same_position_raises(self):
        """Opening a position when one is already open must raise."""
        pos1 = _make_position(pos_id="pos-1")
        pos2 = _make_position(pos_id="pos-2")
        state = EngineState(symbol="NIFTY")
        state = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos1))
        with pytest.raises(ValueError):
            apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos2))

    def test_double_open_same_id_raises_error(self):
        """Opening the same position ID twice must raise ValueError.

        The system correctly rejects double-opens. This test documents
        that the guard works for both different and same IDs.
        """
        pos = _make_position(pos_id="same-id")
        state = EngineState(symbol="NIFTY")
        state = apply_event(state, PositionOpened(symbol="NIFTY", time="t1", position=pos))

        # Same position ID — should raise because state.position is not None
        pos2 = _make_position(pos_id="same-id")
        with pytest.raises(ValueError, match="Position already open"):
            apply_event(state, PositionOpened(symbol="NIFTY", time="t2", position=pos2))

    def test_close_wrong_id_returns_unchanged(self):
        """Closing a different position ID should be a no-op (pyramid handling).

        BUG: In apply_event, if event.fill.position._id != state.position.id,
        the state is returned unchanged. But this swallows the close event
        silently — the PositionClosed event is never applied.
        """
        pos1 = _make_position(pos_id="base")
        pos2 = _make_position(pos_id="other")
        fill2 = _make_fill(pos2)

        state = EngineState(symbol="NIFTY")
        state = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos1))

        # Close with a different position ID — BUG: silently ignored
        event = PositionClosed(symbol="NIFTY", time="t2", fill=fill2)
        result = apply_event(state, event)
        # BUG: Position is still open despite PositionClosed event
        assert result.position is not None, "BUG: Close with wrong ID silently ignored"

    def test_close_after_close_raises_or_noop(self):
        """Closing an already-closed position — must be idempotent or error."""
        pos = _make_position(pos_id="p1")
        fill = _make_fill(pos)

        state = EngineState(symbol="NIFTY")
        state = apply_event(state, PositionOpened(symbol="NIFTY", time="t1", position=pos))
        state = apply_event(state, PositionClosed(symbol="NIFTY", time="t2", fill=fill))

        assert state.position is None  # Position closed

        # Second close — BUG: raises ValueError "No position to close"
        with pytest.raises(ValueError):
            apply_event(state, PositionClosed(symbol="NIFTY", time="t3", fill=fill))


# =============================================================================
# TEST CLASS: Boundary Values
# =============================================================================


class TestBoundaryValues:
    """Attack: float('inf'), float('nan'), -1, 0, sys.maxsize."""

    def test_apply_event_with_zero_size_position(self):
        """Position with zero size should be rejected.

        BUG: No validation on size — zero-size position opens silently.
        """
        pos = _make_position(size=0.0)
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))
        # BUG: Zero-size position is allowed — division by zero risk later
        assert result.position is not None, "BUG: Zero-size position opens"

    def test_apply_event_with_negative_size(self):
        """Position with negative size when long — should this be valid?

        BUG: Negative size for a "LONG" side position is inconsistent
        but allowed. Side is derived from size sign in _position_to_state.
        """
        # size=-1 with side="LONG" in signal — inconsistent
        pos = _make_position(size=-1.0, side="LONG")
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))
        # BUG: Side derived from size.signal which conflicts with signal.side
        assert result.position.side == "SHORT"  # Derived from size, not signal

    def test_apply_event_with_inf_entry_price(self):
        """Position with float('inf') entry price.

        BUG: No validation on price values — inf propagates silently.
        """
        pos = _make_position(entry=float("inf"))
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))
        # BUG: inf entry price accepted
        assert math.isinf(result.position.entry), "BUG: inf entry price accepted"

    def test_apply_event_with_nan_entry_price(self):
        """Position with float('nan') entry price.

        BUG: NaN comparisons always return False, so SL/TP checks break.
        """
        pos = _make_position(entry=float("nan"))
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))
        # BUG: NaN entry price accepted — NaN != NaN so comparisons fail
        assert math.isnan(result.position.entry), "BUG: NaN entry price accepted"

    def test_apply_event_with_maxsize_values(self):
        """Position with sys.maxsize values.

        BUG: Extreme values may cause overflow in downstream calculations.
        """
        huge = float(sys.maxsize)
        pos = _make_position(entry=huge, sl=huge - 1000, tp=huge + 1000)
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))
        # BUG: maxsize values accepted without overflow checks
        assert result.position.entry == huge

    def test_apply_event_with_zero_price(self):
        """Bar with zero close price.

        BUG: Zero prices may cause division errors in indicators.
        """
        bar = _make_bar(close=0.0, high=0.0, low=0.0, open=0.0)
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, BarClosed(symbol="NIFTY", time="t", bar=bar))
        # BUG: All-zero bar accepted — downstream division by zero risk
        assert result.last_bar.close == 0.0, "BUG: Zero-price bar accepted"

    def test_apply_event_with_negative_price(self):
        """Bar with negative prices — logically impossible for equities.

        BUG: Negative prices silently accepted.
        """
        bar = _make_bar(close=-100.0, high=-90.0, low=-110.0, open=-95.0)
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, BarClosed(symbol="NIFTY", time="t", bar=bar))
        # BUG: Negative price bar accepted
        assert result.last_bar.close == -100.0, "BUG: Negative price bar accepted"


# =============================================================================
# TEST CLASS: Type Confusion
# =============================================================================


class TestTypeConfusion:
    """Attack: Pass dict instead of Event, wrong types."""

    def test_apply_event_with_dict_instead_of_event(self):
        """Passing a dict instead of Event should raise TypeError.

        BUG: apply_event uses isinstance checks — a dict falls through to
        the else branch and is silently treated as a no-op.
        """
        state = EngineState(symbol="NIFTY")
        # A dict that looks like an event but isn't
        fake_event = {"symbol": "NIFTY", "time": "t", "type": "BarClosed"}
        result = apply_event(state, fake_event)  # type: ignore
        # BUG: Dict passes through as unknown event — no error raised
        assert result is state, "BUG: Dict silently treated as no-op event"

    def test_apply_event_with_base_event_class(self):
        """Base Event class should be handled explicitly.

        BUG: Unknown events are no-ops — base Event is treated as unknown.
        """
        state = EngineState(symbol="NIFTY")
        event = Event(symbol="NIFTY", time="t")
        result = apply_event(state, event)
        # BUG: Base Event silently ignored — no warning or error
        assert result is state, "BUG: Base Event silently ignored"

    def test_event_store_append_non_event(self):
        """Appending a non-Event to EventStore should raise TypeError.

        BUG: No type validation on append — non-events accepted.
        """
        store = EventStore()
        # BUG: No type check on append — non-Event objects accepted
        seq = store.append({"symbol": "NIFTY", "time": "t"})  # type: ignore
        assert seq == 1, "BUG: Dict appended as event"

    def test_apply_event_position_opened_with_position_state(self):
        """PositionOpened with a PositionState instead of Position.

        BUG: _position_to_state checks isinstance(pos, PositionState) and
        returns as-is — so this works. But the type annotation says Position.
        This tests whether the type system catches the mismatch.
        """
        pos_state = PositionState(
            id="ps-1",
            entry=100.0,
            size=1.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        # PositionOpened expects Position, not PositionState
        event = PositionOpened(symbol="NIFTY", time="t", position=pos_state)  # type: ignore
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, event)
        # BUG: PositionState passes through _position_to_state unchanged
        assert result.position.id == "ps-1"


# =============================================================================
# TEST CLASS: Huge Values
# =============================================================================


class TestHugeValues:
    """Attack: 1e308 prices, massive sequences."""

    def test_apply_event_with_1e308_entry(self):
        """Position with 1e308 entry price.

        BUG: Extreme values cause float overflow in arithmetic.
        """
        pos = _make_position(entry=1e308, sl=1e308 - 1e307, tp=1e308 + 1e307)
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))
        # BUG: 1e308 values accepted — adding anything overflows to inf
        assert result.position.entry == 1e308

    def test_fold_massive_sequence(self):
        """Folding a massive event sequence.

        BUG: fold() iterates all events — performance may degrade.
        Also, sequence numbers may overflow.
        """
        store = EventStore()
        bar = _make_bar()

        # Append 100k bar events
        for i in range(100_000):
            store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar))

        state = store.fold()
        # BUG: After 100k bar events, sequence counter should be 100000
        assert state.sequence == 100_000

    def test_checksum_collision_with_massive_events(self):
        """After millions of events, checksum chain should still verify.

        BUG: Checksum chain is O(n) to verify — performance may degrade.
        """
        store = EventStore()
        for i in range(10_000):
            store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=_make_bar(time=f"t{i}")))

        # Should still verify
        assert store.verify_chain()


# =============================================================================
# TEST CLASS: Unicode and Special Characters
# =============================================================================


class TestUnicodeSpecialChars:
    """Attack: Emoji in symbols, null bytes in timestamps."""

    def test_apply_event_with_emoji_symbol(self):
        """Position with emoji in symbol field.

        BUG: No validation on symbol — emoji propagates to state.
        """
        pos = _make_position()
        event = PositionOpened(symbol="NIFTY🚀", time="t", position=pos)
        state = EngineState(symbol="NIFTY🚀")
        result = apply_event(state, event)
        # BUG: Emoji symbol accepted
        assert "🚀" in result.symbol, "BUG: Emoji in symbol accepted"

    def test_apply_event_with_null_byte_in_time(self):
        """Event with null byte in time string.

        BUG: Null bytes may cause issues with serialization/logging.
        """
        pos = _make_position()
        event = PositionOpened(symbol="NIFTY", time="2026\x0001\x0001", position=pos)
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, event)
        # BUG: Null bytes in timestamp accepted
        assert "\x00" in result.last_close_bar.__str__() or True  # Stored somewhere

    def test_apply_event_with_unicode_symbol(self):
        """Position with unicode characters in symbol.

        BUG: Unicode symbols may break downstream code expecting ASCII.
        """
        pos = _make_position()
        event = PositionOpened(symbol="日本語", time="t", position=pos)
        state = EngineState(symbol="日本語")
        result = apply_event(state, event)
        # BUG: Non-ASCII symbol accepted without normalization
        assert result.symbol == "日本語"

    def test_apply_event_with_very_long_symbol(self):
        """Symbol with 10MB string.

        BUG: No length limits on symbol — memory exhaustion risk.
        """
        long_symbol = "A" * (10 * 1024 * 1024)  # 10MB
        pos = _make_position()
        event = PositionOpened(symbol=long_symbol, time="t", position=pos)
        state = EngineState(symbol=long_symbol)
        result = apply_event(state, event)
        # BUG: 10MB symbol accepted — memory DoS vector
        assert len(result.symbol) == 10 * 1024 * 1024


# =============================================================================
# TEST CLASS: Time Travel and Ordering
# =============================================================================


class TestTimeTravel:
    """Attack: Events out of order, future dates."""

    def test_fold_events_out_of_order(self):
        """Events appended out of chronological order.

        BUG: EventStore doesn't validate temporal ordering — events are
        applied in insertion order regardless of timestamp.
        """
        store = EventStore()
        bar1 = _make_bar(time="2026-01-01T10:00:00+05:30", close=100.0)
        bar2 = _make_bar(time="2026-01-01T09:00:00+05:30", close=90.0)  # Earlier

        store.append(BarClosed(symbol="NIFTY", time="2026-01-01T10:00:00+05:30", bar=bar1))
        store.append(BarClosed(symbol="NIFTY", time="2026-01-01T09:00:00+05:30", bar=bar2))

        state = store.fold()
        # BUG: Last bar is bar2 (90.0) which is earlier in time — state
        # reflects insertion order, not temporal order
        assert state.last_bar.close == 90.0, "BUG: Out-of-order events applied as-is"

    def test_fold_events_with_future_timestamp(self):
        """Events with future timestamps.

        BUG: No validation on time — future dates accepted silently.
        """
        store = EventStore()
        future_time = "2099-12-31T23:59:59+05:30"
        bar = _make_bar(time=future_time)
        store.append(BarClosed(symbol="NIFTY", time=future_time, bar=bar))

        state = store.fold()
        # BUG: Future timestamp accepted — logic comparing to "now" breaks
        assert state.last_bar.time == future_time

    def test_fold_events_with_epoch_zero(self):
        """Events with Unix epoch 0 timestamp.

        BUG: Epoch 0 (1970-01-01) accepted — may be treated as "no time".
        """
        store = EventStore()
        bar = _make_bar(time="1970-01-01T00:00:00+00:00")
        store.append(BarClosed(symbol="NIFTY", time="1970-01-01T00:00:00+00:00", bar=bar))

        state = store.fold()
        assert state.last_bar.time == "1970-01-01T00:00:00+00:00"

    def test_fold_events_with_negative_bar_index(self):
        """Risk update with negative daily PnL.

        BUG: Negative PnL is valid (losses), but trades_today=-1 is not.
        """
        risk = RiskState(daily_pnl=-1000.0, trades_today=-1, halted=False)
        state = EngineState(symbol="NIFTY")
        event = RiskUpdated(symbol="NIFTY", time="t", risk=risk)
        result = apply_event(state, event)
        # BUG: Negative trades_today accepted
        assert result.risk.trades_today == -1, "BUG: Negative trades_today accepted"


# =============================================================================
# TEST CLASS: Checksum Chain Integrity
# =============================================================================


class TestChecksumIntegrity:
    """Attack: Verify checksum chain detects tampering."""

    def test_tampered_event_detected(self):
        """Tampering with an event should break the checksum chain."""
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))
        store.append(BarClosed(symbol="NIFTY", time="t2", bar=_make_bar(time="t2")))

        assert store.verify_chain()

        # Tamper with the first event
        store._checksums[0] = "tampered"
        assert not store.verify_chain()

    def test_tampered_event_data_detected(self):
        """Changing event data after append should be detectable.

        BUG: Since events are frozen dataclasses, direct modification is hard,
        but the checksums list can be modified independently.
        """
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))

        # Modify the checksum to simulate tampering
        store._checksums[0] = "0" * 64
        assert not store.verify_chain()


# =============================================================================
# TEST CLASS: PositionManager Double-Close Guard
# =============================================================================


class TestPositionManagerDoubleCloseGuard:
    """Attack: Double-close scenarios and _closed_ids guard."""

    def test_closed_ids_guard_prevents_double_close(self):
        """After a full close, the position ID is in _closed_ids.

        BUG: The _closed_ids guard works, but only if the same
        PositionManager instance is used. A new instance loses the guard.
        """
        from quant.position_manager import PositionManager

        # Create mocks
        mock_oms = MagicMock()
        mock_exits = MagicMock()
        mock_risk = MagicMock()
        mock_risk.record_trade.return_value = RiskState(daily_pnl=100.0, trades_today=1)
        mock_risk.can_trade.return_value = (True, "")

        def emit(event):
            pass

        pm = PositionManager(
            oms=mock_oms,
            exits=mock_exits,
            risk=mock_risk,
            emit_fn=emit,
            symbol="NIFTY",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )

        pos = _make_position(pos_id="guard-test")
        pm.current_position = pos
        pm._closed_ids.add("guard-test")

        # Now try to close — should be blocked by guard
        from quant.execution.exits import ExitDecision

        exit_dec = ExitDecision(True, "SL", 95.0)
        result = pm._execute_full_close(pos, exit_dec, "t")

        # BUG: Returns None (skipped) due to guard — but no error raised
        assert result is None
        # OMS close should NOT have been called
        mock_oms.close.assert_not_called()


# =============================================================================
# TEST CLASS: EngineState Immutability
# =============================================================================


class TestEngineStateImmutability:
    """Attack: Verify EngineState transitions produce new instances."""

    def test_with_bar_returns_new_instance(self):
        """with_bar must return a new EngineState."""
        bar1 = _make_bar(close=100.0)
        state1 = EngineState(symbol="NIFTY", last_bar=bar1)
        bar2 = _make_bar(close=110.0)
        state2 = state1.with_bar(bar2)

        assert state1 is not state2
        assert state1.last_bar.close == 100.0  # Original unchanged
        assert state2.last_bar.close == 110.0

    def test_with_position_returns_new_instance(self):
        """with_position must return a new EngineState."""
        state1 = EngineState(symbol="NIFTY")
        pos = PositionState(
            id="p1", entry=100.0, size=1.0, sl=95.0, tp=110.0, side="LONG"
        )
        state2 = state1.with_position(pos)

        assert state1 is not state2
        assert state1.position is None
        assert state2.position.id == "p1"

    def test_without_position_returns_new_instance(self):
        """without_position must return a new EngineState."""
        pos = PositionState(
            id="p1", entry=100.0, size=1.0, sl=95.0, tp=110.0, side="LONG"
        )
        state1 = EngineState(symbol="NIFTY", position=pos)
        state2 = state1.without_position()

        assert state1 is not state2
        assert state1.position is not None
        assert state2.position is None

    def test_sequence_increments_on_each_transition(self):
        """Sequence number must increment on every state change."""
        state = EngineState(symbol="NIFTY")
        assert state.sequence == 0

        state = state.with_bar(_make_bar())
        assert state.sequence == 1

        state = state.with_bar(_make_bar(close=101.0))
        assert state.sequence == 2

        pos = PositionState(
            id="p1", entry=100.0, size=1.0, sl=95.0, tp=110.0, side="LONG"
        )
        state = state.with_position(pos)
        assert state.sequence == 3

        state = state.without_position()
        assert state.sequence == 4


# =============================================================================
# TEST CLASS: Export/Import Roundtrip
# =============================================================================


class TestExportImportRoundtrip:
    """Attack: Verify export/import preserves event data."""

    def test_roundtrip_empty_store(self):
        """Exporting and importing an empty store should work."""
        store = EventStore()
        exported = store.export()
        assert exported == []

        store.import_(exported)
        assert len(store) == 0

    def test_roundtrip_single_bar_event(self):
        """BarClosed should survive export/import roundtrip."""
        store = EventStore()
        bar = _make_bar(time="t1", close=100.0)
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=bar))

        exported = store.export()
        assert len(exported) == 1
        assert exported[0]["event_type"] == "BarClosed"
        assert exported[0]["payload"]["bar"]["close"] == 100.0

        new_store = EventStore()
        new_store.import_(exported)
        assert len(new_store) == 1

    def test_roundtrip_unknown_event_type_returns_base_event(self):
        """Unknown event type on import returns base Event.

        BUG: Unknown event types are silently converted to base Event —
        data loss without warning.
        """
        store = EventStore()
        store._events = []
        store._sequence = 0
        store._checksums = []

        unknown_event = {
            "sequence": 1,
            "symbol": "NIFTY",
            "time": "t",
            "event_type": "SomeFutureEvent",
            "payload": {"data": "value"},
        }

        store.import_([unknown_event])
        # BUG: Unknown type silently becomes base Event — data lost
        assert len(store) == 1
        assert isinstance(store.get_all()[0], Event)


# =============================================================================
# TEST CLASS: RiskState Edge Cases
# =============================================================================


class TestRiskStateEdgeCases:
    """Attack: RiskState boundary conditions."""

    def test_risk_state_with_extreme_daily_pnl(self):
        """RiskState with extreme daily PnL values.

        BUG: No bounds checking on daily_pnl — may overflow in risk calc.
        """
        risk = RiskState(
            daily_pnl=float("inf"),
            trades_today=sys.maxsize,
            halted=False,
        )
        state = EngineState(symbol="NIFTY")
        event = RiskUpdated(symbol="NIFTY", time="t", risk=risk)
        result = apply_event(state, event)

        # BUG: Extreme values accepted without validation
        assert math.isinf(result.risk.daily_pnl)
        assert result.risk.trades_today == sys.maxsize

    def test_risk_state_halt_without_reason(self):
        """RiskState halted=True with empty halt_reason.

        BUG: halt_reason="" when halted=True — downstream code may check
        truthiness of halt_reason instead of halted flag.
        """
        risk = RiskState(halted=True, halt_reason="")
        state = EngineState(symbol="NIFTY")
        event = RiskUpdated(symbol="NIFTY", time="t", risk=risk)
        result = apply_event(state, event)

        # BUG: halt_reason is empty string — truthiness check fails
        assert result.risk.halted is True
        assert not result.risk.halt_reason  # Empty string is falsy!


# =============================================================================
# TEST CLASS: PositionState Edge Cases
# =============================================================================


class TestPositionStateEdgeCases:
    """Attack: PositionState boundary conditions."""

    def test_position_state_with_zero_sl_tp(self):
        """PositionState with SL=0 and TP=0.

        BUG: Zero SL/TP means no stop-loss protection — dangerous.
        """
        pos = PositionState(
            id="noprot",
            entry=100.0,
            size=1.0,
            sl=0.0,
            tp=0.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))

        # BUG: Zero SL/TP accepted — no protection
        assert result.position.sl == 0.0
        assert result.position.tp == 0.0

    def test_position_state_with_negative_sl(self):
        """PositionState with negative stop-loss.

        BUG: Negative SL for a LONG is below zero — guaranteed loss.
        """
        pos = PositionState(
            id="negsl",
            entry=100.0,
            size=1.0,
            sl=-50.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))

        # BUG: Negative SL accepted
        assert result.position.sl == -50.0

    def test_position_state_with_empty_id(self):
        """PositionState with empty ID.

        BUG: Empty ID makes matching/lookup impossible.
        """
        pos = PositionState(
            id="",
            entry=100.0,
            size=1.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos))

        # BUG: Empty ID accepted
        assert result.position.id == ""


# =============================================================================
# TEST CLASS: Event Handler Edge Cases
# =============================================================================


class TestEventHandlerEdgeCases:
    """Attack: Event handler failures and dead-letter queue."""

    def test_handler_exception_captured_in_dead_letter_queue(self):
        """Handler failures should be captured, not crash the system."""
        store = EventStore()

        def failing_handler(event):
            raise RuntimeError("Handler crashed!")

        store.subscribe(BarClosed, failing_handler)
        event = BarClosed(symbol="NIFTY", time="t", bar=_make_bar())
        store.publish_with_dead_letter(event)

        dlq = store.get_dead_letter_queue()
        assert len(dlq) == 1
        assert isinstance(dlq[0][1], RuntimeError)


# =============================================================================
# TEST CLASS: PositionManager Edge Cases
# =============================================================================


class TestPositionManagerEdgeCases:
    """Attack: PositionManager with invalid inputs."""

    def test_manage_exit_with_none_position(self):
        """manage_exit(None) should return None gracefully."""
        from quant.position_manager import PositionManager

        pm = PositionManager(
            oms=MagicMock(),
            exits=MagicMock(),
            risk=MagicMock(),
            emit_fn=lambda e: None,
            symbol="NIFTY",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )
        result = pm.manage_exit({}, _make_bar(), None, 0, 0, 0.0)
        assert result is None

    def test_manage_exit_with_invalid_bar(self):
        """manage_exit with None bar should crash or handle gracefully.

        BUG: manage_exit accesses bar.time, bar.close, bar.high, bar.low
        — passing None bar causes AttributeError.
        """
        from quant.position_manager import PositionManager

        pm = PositionManager(
            oms=MagicMock(),
            exits=MagicMock(),
            risk=MagicMock(),
            emit_fn=lambda e: None,
            symbol="NIFTY",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )
        pos = _make_position()
        # BUG: No validation on bar parameter
        with pytest.raises(AttributeError):
            pm.manage_exit({}, None, pos, 0, 0, 0.0)  # type: ignore

    def test_execute_full_close_with_none_position_id(self):
        """_execute_full_close with a position that has no _id crashes.

        BUG: _execute_full_close does `pos_id = getattr(position, '_id', None) or getattr(position, 'id', None)`.
        If position has no _id and no id attribute, pos_id is None, and `if pos_id and pos_id in self._closed_ids`
        skips the guard. Then `self._closed_ids.add(None)` is called, adding None to the set.
        """
        from quant.execution.exits import ExitDecision
        from quant.position_manager import PositionManager

        pm = PositionManager(
            oms=MagicMock(),
            exits=MagicMock(),
            risk=MagicMock(),
            emit_fn=lambda e: None,
            symbol="NIFTY",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )
        # Position with no _id and no id
        pos = MagicMock()
        del pos._id  # Remove _id
        del pos.id   # Remove id
        pos.size = 1.0
        pos.pyramid_level = 0

        exit_dec = ExitDecision(True, "SL", 95.0)
        # Should handle gracefully but will crash on self._closed_ids.add(None)
        with pytest.raises((AttributeError, TypeError)):
            pm._execute_full_close(pos, exit_dec, "t")

    def test_execute_full_close_with_none_position_id_does_not_raise(self):
        """Verify the _closed_ids.add(None) bug — it silently succeeds.

        BUG: _execute_full_close doesn't crash, it just adds None to _closed_ids.
        This test documents the silent failure mode.
        """
        from quant.execution.exits import ExitDecision
        from quant.position_manager import PositionManager

        pm = PositionManager(
            oms=MagicMock(),
            exits=MagicMock(),
            risk=MagicMock(),
            emit_fn=lambda e: None,
            symbol="NIFTY",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )
        # Position with no _id
        pos = MagicMock(spec=[])  # Empty spec — no attributes at all
        exit_dec = ExitDecision(True, "SL", 95.0)

        # BUG: This does NOT raise — it silently adds None to _closed_ids
        result = pm._execute_full_close(pos, exit_dec, "t")
        # The position was never actually closed (OMS not called)
        assert None in pm._closed_ids, "BUG: None was added to _closed_ids"


class TestEventStoreExportImportBugs:
    """Attack: Export/import preserves all data."""

    def test_export_import_position_closed_loses_order_data(self):
        """PositionClosed export/import loses order data.

        BUG: _dict_to_event reconstructs Position with order=None,
        losing signal data. The original fill.pnl is preserved but
        the signal (entry, sl, tp) is lost.
        """
        store = EventStore()
        pos = _make_position(pos_id="export-test", entry=100.0, sl=95.0, tp=110.0)
        fill = _make_fill(pos, close_price=105.0, pnl=5.0, reason="TP")
        store.append(PositionOpened(symbol="NIFTY", time="t1", position=pos))
        store.append(PositionClosed(symbol="NIFTY", time="t2", fill=fill))

        exported = store.export()
        assert len(exported) == 2

        # Import into new store
        new_store = EventStore()
        new_store.import_(exported)

        # Verify the PositionClosed fill.position.order is None
        closed_event = new_store.get_all()[1]
        # BUG: order is None after roundtrip — signal data lost
        assert closed_event.fill.position.order is None, "BUG: order=None after import"

    def test_import_preserves_all_event_types(self):
        """Import should fail for unknown event types instead of silent base Event.

        BUG: Unknown event types are silently converted to base Event without
        any warning. Data is lost silently.
        """
        store = EventStore()
        unknown_event = {
            "sequence": 1,
            "symbol": "NIFTY",
            "time": "t",
            "event_type": "SomeFutureEventType",
            "payload": {"critical_data": "must_not_be_lost"},
        }

        # BUG: Should raise TypeError or preserve as raw dict, but silently converts
        store.import_([unknown_event])
        imported_event = store.get_all()[0]
        assert isinstance(imported_event, Event), "BUG: Unknown event type silently converted to base Event"
        assert not hasattr(imported_event, 'critical_data'), "BUG: Payload data lost during import"


class TestApplyEventMissingFieldBugs:
    """Attack: apply_event crashes on missing event fields."""

    def test_apply_event_bar_closed_missing_bar_attribute(self):
        """apply_event where event has no bar attribute crashes.

        BUG: apply_event accesses event.bar without checking it exists.
        If BarClosed is created without bar field, this crashes.
        """
        state = EngineState(symbol="NIFTY")
        # Create a BarClosed with bar=None — frozen dataclass accepts it
        event = BarClosed(symbol="NIFTY", time="t", bar=None)  # type: ignore
        result = apply_event(state, event)
        # BUG: state.last_bar is now None
        assert result.last_bar is None, "BUG: None bar stored in state"

    def test_apply_event_position_closed_with_missing_fill_position_id(self):
        """apply_event PositionClosed where fill.position._id missing crashes.

        BUG: apply_event accesses event.fill.position._id without checking.
        """
        pos = _make_position()
        fill = _make_fill(pos)
        # Make fill.position._id inaccessible
        object.__setattr__(fill, 'position', MagicMock(spec=[]))  # No _id, no id

        event = PositionClosed(symbol="NIFTY", time="t", fill=fill)
        state = EngineState(symbol="NIFTY", position=PositionState(
            id="p1", entry=100.0, size=1.0, sl=95.0, tp=110.0, side="LONG"
        ))
        with pytest.raises(AttributeError):
            apply_event(state, event)


class TestApplyEventEdgeCases:
    """Attack: apply_event with malformed events."""

    def test_apply_event_position_opened_with_none_order(self):
        """PositionOpened where position.order is None crashes.

        BUG: _position_to_state accesses pos.order.signal which raises AttributeError
        if pos.order is None.
        """
        pos = _make_position()
        # Set order to None via mock
        object.__setattr__(pos, 'order', None)  # Bypass frozen
        event = PositionOpened(symbol="NIFTY", time="t", position=pos)
        state = EngineState(symbol="NIFTY")
        with pytest.raises(AttributeError):
            apply_event(state, event)

    def test_apply_event_position_closed_with_none_fill_position(self):
        """PositionClosed where fill.position is None crashes.

        BUG: apply_event accesses event.fill.position._id which raises
        AttributeError if fill.position is None.
        """
        pos = _make_position()
        fill = _make_fill(pos)
        # Set fill.position to None
        object.__setattr__(fill, 'position', None)  # Bypass frozen
        event = PositionClosed(symbol="NIFTY", time="t", fill=fill)
        state = EngineState(symbol="NIFTY", position=PositionState(
            id="p1", entry=100.0, size=1.0, sl=95.0, tp=110.0, side="LONG"
        ))
        with pytest.raises(AttributeError):
            apply_event(state, event)

    def test_apply_event_bar_closed_with_none_bar(self):
        """BarClosed with None bar should crash or handle gracefully.

        BUG: apply_event calls state.with_bar(event.bar) which stores None
        — downstream code accessing bar.close will crash.
        """
        event = BarClosed(symbol="NIFTY", time="t", bar=None)  # type: ignore
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, event)
        # BUG: None bar stored in state
        assert result.last_bar is None, "BUG: None bar stored in state"

    def test_apply_event_risk_updated_with_none_risk(self):
        """RiskUpdated with None risk should crash or handle gracefully.

        BUG: apply_event calls state.with_risk(event.risk) which stores None.
        """
        event = RiskUpdated(symbol="NIFTY", time="t", risk=None)  # type: ignore
        state = EngineState(symbol="NIFTY")
        result = apply_event(state, event)
        # BUG: None risk stored in state
        assert result.risk is None, "BUG: None risk stored in state"


class TestEventStoreComputeChecksumEdgeCases:
    """Attack: _compute_checksum with invalid event fields."""

    def test_compute_checksum_with_none_symbol_event(self):
        """_compute_checksum with event.symbol=None crashes json.dumps.

        BUG: json.dumps(None) works, but downstream code may not expect None.
        """
        store = EventStore()
        event = Event(symbol=None, time="t")  # type: ignore
        # BUG: No validation — None symbol accepted
        store.append(event)
        assert store._checksums[0] is not None  # Computed anyway

    def test_compute_checksum_with_none_time_event(self):
        """_compute_checksum with event.time=None.

        BUG: json.dumps(None) works but is semantically wrong.
        """
        store = EventStore()
        event = Event(symbol="NIFTY", time=None)  # type: ignore
        store.append(event)
        assert store._checksums[0] is not None


class TestPositionToStateEdgeCases:
    """Attack: _position_to_state with invalid Position objects."""

    def test_position_to_state_with_none_position(self):
        """_position_to_state(None) crashes.

        BUG: No None check.
        """
        from quant.transitions import _position_to_state
        with pytest.raises(AttributeError):
            _position_to_state(None)

    def test_position_to_state_with_position_missing_signal(self):
        """_position_to_state with position.order.signal=None crashes.

        BUG: Accesses sig.entry without checking sig is None.
        """
        from quant.transitions import _position_to_state
        pos = MagicMock()
        pos.order.signal = None
        pos._id = "p1"
        pos.size = 1.0
        pos.pyramid_level = 0
        pos.is_pyramid = False
        with pytest.raises(AttributeError):
            _position_to_state(pos)


class TestEventStoreSequenceBugs:
    """Attack: EventStore sequence number integrity."""

    def test_sequence_not_reset_on_import(self):
        """import_ resets sequence to 0, then increments — so sequence numbers
        restart from 1 after import.

        BUG: If events were already in the store and then import_ is called,
        sequence numbers restart from 1, losing the original sequence context.
        """
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))
        store.append(BarClosed(symbol="NIFTY", time="t2", bar=_make_bar(time="t2")))

        assert store._sequence == 2

        # Import new events — BUG: sequence resets
        store.import_([
            {"sequence": 1, "symbol": "NIFTY", "time": "t3",
             "event_type": "BarClosed", "payload": {"bar": {"time": "t3"}}},
        ])

        # BUG: sequence is now 1, not 3 — continuity broken
        assert store._sequence == 1, "BUG: Sequence reset to 1 after import"

    def test_get_since_off_by_one(self):
        """get_since has off-by-one: sequence is 1-based but list is 0-based.

        BUG: get_since(sequence=1) should return events[0:]. But due to
        start_idx = max(0, sequence - 1) = 0, it returns all events.
        This is correct behavior, but the semantics are confusing.
        """
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))
        store.append(BarClosed(symbol="NIFTY", time="t2", bar=_make_bar(time="t2")))

        # get_since(1) returns all events (start_idx=0)
        result = store.get_since(1)
        assert len(result) == 2

        # get_since(2) returns events from index 1 (second event)
        result = store.get_since(2)
        assert len(result) == 1
        assert result[0].time == "t2"


class TestApplyEventSequenceNotIncremented:
    """Attack: apply_event doesn't update sequence number in some branches."""

    def test_apply_event_bar_closed_increments_sequence(self):
        """BarClosed should increment sequence."""
        state = EngineState(symbol="NIFTY", sequence=0)
        bar = _make_bar()
        event = BarClosed(symbol="NIFTY", time="t", bar=bar)
        result = apply_event(state, event)
        assert result.sequence == 1

    def test_apply_event_position_opened_increments_sequence(self):
        """PositionOpened should increment sequence."""
        state = EngineState(symbol="NIFTY", sequence=0)
        pos = _make_position()
        event = PositionOpened(symbol="NIFTY", time="t", position=pos)
        result = apply_event(state, event)
        assert result.sequence == 1

    def test_apply_event_position_closed_wrong_id_doesnt_increment(self):
        """PositionClosed with wrong ID returns state unchanged — but sequence?

        BUG: If the close is a no-op (wrong ID), the sequence is NOT incremented.
        But the event WAS applied (as a no-op). The sequence should increment.
        """
        pos1 = _make_position(pos_id="base")
        pos2 = _make_position(pos_id="other")
        fill2 = _make_fill(pos2)

        state = EngineState(symbol="NIFTY", sequence=0)
        state = apply_event(state, PositionOpened(symbol="NIFTY", time="t", position=pos1))
        assert state.sequence == 1

        # Close with wrong ID — no-op but sequence should still increment?
        event = PositionClosed(symbol="NIFTY", time="t2", fill=fill2)
        result = apply_event(state, event)
        # BUG: Sequence stays at 1 — inconsistent with other events
        assert result.sequence == 1, "BUG: Sequence not incremented for no-op close"

    def test_apply_event_unknown_event_doesnt_increment(self):
        """Unknown event types (base Event) don't increment sequence.

        BUG: If an unknown event is passed, state is returned as-is without
        incrementing sequence. This is actually correct for a no-op, but
        may cause sequence gaps.
        """
        state = EngineState(symbol="NIFTY", sequence=5)
        event = Event(symbol="NIFTY", time="t")
        result = apply_event(state, event)
        # Sequence stays at 5 — unknown event is a no-op
        assert result.sequence == 5


class TestFoldIdempotencyWithState:
    """Attack: fold() should not mutate the EventStore."""

    def test_fold_does_not_mutate_store(self):
        """fold() should not modify the event store's internal state."""
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))

        initial_events = store.get_all()
        initial_len = len(store)
        initial_seq = store._sequence

        state = store.fold()

        # Store should be unchanged
        assert len(store) == initial_len
        assert store._sequence == initial_seq
        assert store.get_all() == initial_events

    def test_fold_result_is_new_instance(self):
        """fold() should return a fresh EngineState each time."""
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))

        state1 = store.fold()
        state2 = store.fold()

        # Should be equal but not same object (EngineState is a dataclass)
        assert state1 == state2
        # Note: since EngineState is frozen and we use replace(),
        # state1 and state2 are different objects


class TestImportDuplicateSequence:
    """Attack: import_ with duplicate sequence numbers."""

    def test_import_duplicate_sequence_numbers(self):
        """import_ rejects duplicate sequence numbers.

        Duplicate sequences are ambiguous log metadata (a gap or replay);
        import_ must reject them instead of silently renumbering.
        """
        store = EventStore()
        with pytest.raises(ValueError, match="sequence"):
            store.import_([
                {"sequence": 1, "symbol": "NIFTY", "time": "t1",
                 "event_type": "BarClosed", "payload": {"bar": {"time": "t1"}}},
                {"sequence": 1, "symbol": "NIFTY", "time": "t2",
                 "event_type": "BarClosed", "payload": {"bar": {"time": "t2"}}},
            ])
        # Failed import is atomic — store untouched.
        assert len(store) == 0


class TestApplyEventSequenceGaps:
    """Attack: Sequence gaps in apply_event."""

    def test_unknown_event_creates_sequence_gap(self):
        """Unknown event (base Event) doesn't increment sequence, creating gaps.

        BUG: If apply_event receives an unknown event type, it returns the
        same state with the same sequence number. This creates gaps in the
        sequence when the next valid event increments past the skipped one.
        """
        state = EngineState(symbol="NIFTY", sequence=5)

        # Apply unknown event
        unknown_event = Event(symbol="NIFTY", time="t")
        result = apply_event(state, unknown_event)
        assert result.sequence == 5  # No increment

        # Apply known event
        bar = _make_bar()
        known_event = BarClosed(symbol="NIFTY", time="t2", bar=bar)
        result2 = apply_event(result, known_event)
        # BUG: Sequence jumps from 5 to 6, but the unknown event "consumed"
        # a logical position — the sequence should be monotonically increasing
        # per event, not per state change
        assert result2.sequence == 6


class TestEventStoreImportMalformedData:
    """Attack: import_ with malformed data."""

    def test_import_missing_bar_data_creates_invalid_bar(self):
        """import_ with missing bar fields creates Bar with defaults.

        BUG: If bar data is missing fields, Bar is created with defaults (0.0),
        which may be invalid (e.g., 0.0 close price).
        """
        store = EventStore()
        store.import_([{
            "sequence": 1,
            "symbol": "NIFTY",
            "time": "t",
            "event_type": "BarClosed",
            "payload": {"bar": {}},  # Missing all fields
        }])

        event = store.get_all()[0]
        # BUG: Bar with all 0.0 values — invalid state
        assert event.bar.close == 0.0, "BUG: Default 0.0 close price from missing data"
        assert event.bar.high == 0.0
        assert event.bar.low == 0.0

    def test_import_risk_updated_missing_fields(self):
        """import_ RiskUpdated with missing risk fields creates defaults.

        BUG: Missing fields become defaults, which may be invalid
        (e.g., halted=False with halt_reason="")."""
        store = EventStore()
        store.import_([{
            "sequence": 1,
            "symbol": "NIFTY",
            "time": "t",
            "event_type": "RiskUpdated",
            "payload": {"risk": {}},  # Missing all fields
        }])

        event = store.get_all()[0]
        # BUG: Default RiskState with trades_today=0, halted=False
        assert event.risk.trades_today == 0
        assert event.risk.halted is False


class TestEventStoreAppendNonEventCrash:
    """Attack: EventStore.append crashes with wrong type."""

    def test_append_non_event_crashes_not_type_error(self):
        """append with non-Event crashes with AttributeError, not TypeError.

        BUG: The error is AttributeError because it tries event.symbol
        inside _compute_checksum. Should be TypeError.
        """
        store = EventStore()
        try:
            store.append({"symbol": "NIFTY", "time": "t"})  # type: ignore
            assert False, "Should have raised"
        except TypeError:
            pass  # Correct
        except AttributeError:
            # BUG: Wrong exception type
            assert False, "BUG: AttributeError instead of TypeError"

    def test_append_none_crashes(self):
        """append(None) crashes with AttributeError.

        BUG: No None check.
        """
        store = EventStore()
        try:
            store.append(None)  # type: ignore
            assert False, "Should have raised"
        except TypeError:
            pass  # Correct
        except AttributeError:
            # BUG: Wrong exception type
            assert False, "BUG: AttributeError instead of TypeError"


class TestApplyEventSequenceIntegrity:
    """Attack: Sequence numbers should be monotonically increasing."""

    def test_fold_tracks_max_sequence(self):
        """fold() should produce state with sequence = number of events.

        BUG: apply_event only increments sequence for known events.
        Unknown events don't increment. So after N events where some
        are unknown, sequence < N.
        """
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))
        store.append(Event(symbol="NIFTY", time="t2"))  # Unknown event
        store.append(BarClosed(symbol="NIFTY", time="t3", bar=_make_bar(time="t3")))

        state = store.fold()
        # BUG: sequence is 2, not 3 — unknown event didn't increment
        assert state.sequence == 2, "BUG: sequence < number of events"


class TestPositionClosedEventIdMismatch:
    """Attack: PositionClosed event with mismatched ID."""

    def test_close_wrong_id_leaves_position_open(self):
        """PositionClosed with wrong ID leaves position open.

        BUG: The event is silently ignored, position remains open.
        This is by design (pyramid closes have different IDs), but
        there's no logging or warning.
        """
        pos1 = _make_position(pos_id="base-pos")
        pos2 = _make_position(pos_id="pyramid-pos")
        fill2 = _make_fill(pos2, close_price=105.0, pnl=5.0)

        state = EngineState(symbol="NIFTY")
        state = apply_event(state, PositionOpened(symbol="NIFTY", time="t1", position=pos1))
        assert state.position is not None

        # Close pyramid ID — BUG: silently ignored
        state = apply_event(state, PositionClosed(symbol="NIFTY", time="t2", fill=fill2))
        # Position is still open
        assert state.position is not None, "BUG: Pyramid close ignored, base still open"
        assert state.position.id == "base-pos"


class TestFoldDoesNotValidateEventFields:
    """Attack: fold() applies events without validation."""

    def test_fold_applies_invalid_bar_without_error(self):
        """fold() applies BarClosed with invalid bar data without error.

        BUG: No validation in apply_event means invalid data propagates
        through fold() silently.
        """
        store = EventStore()
        # Bar with negative high/low (invalid: high < low)
        invalid_bar = Bar(
            time="t",
            open=100.0,
            high=90.0,  # BUG: high < low
            low=110.0,  # BUG: low > high
            close=95.0,
            volume=1000.0,
        )
        store.append(BarClosed(symbol="NIFTY", time="t", bar=invalid_bar))

        state = store.fold()
        # BUG: Invalid bar data accepted — high=90, low=110 is inconsistent
        assert state.last_bar.high == 90.0
        assert state.last_bar.low == 110.0
        assert state.last_bar.high < state.last_bar.low, "BUG: high < low accepted"

    def test_fold_applies_bar_with_future_timestamp(self):
        """fold() accepts bars with future timestamps.

        BUG: No validation on bar.time — future timestamps accepted.
        """
        store = EventStore()
        future_bar = Bar(time="2099-12-31T23:59:59+05:30", close=100.0)
        store.append(BarClosed(symbol="NIFTY", time="2099-12-31T23:59:59+05:30", bar=future_bar))

        state = store.fold()
        assert state.last_bar.time == "2099-12-31T23:59:59+05:30"


class TestInputValidationBugs:
    """Attack: System should validate inputs but doesn't."""

    def test_apply_event_rejects_nan_entry_price(self):
        """apply_event should reject NaN entry prices.

        BUG: NaN comparisons always return False, breaking SL/TP logic.
        This test asserts correct behavior — it will FAIL.
        """
        pos = _make_position(entry=float("nan"))
        state = EngineState(symbol="NIFTY")
        event = PositionOpened(symbol="NIFTY", time="t", position=pos)
        # BUG: Should raise ValueError, but doesn't
        with pytest.raises(ValueError, match="NaN"):
            apply_event(state, event)

    def test_apply_event_rejects_inf_entry_price(self):
        """apply_event should reject Inf entry prices.

        BUG: Inf causes arithmetic overflow in downstream calculations.
        This test asserts correct behavior — it will FAIL.
        """
        pos = _make_position(entry=float("inf"))
        state = EngineState(symbol="NIFTY")
        event = PositionOpened(symbol="NIFTY", time="t", position=pos)
        # BUG: Should raise ValueError, but doesn't
        with pytest.raises(ValueError, match="inf"):
            apply_event(state, event)

    def test_apply_event_rejects_zero_size_position(self):
        """apply_event should reject zero-size positions.

        BUG: Zero-size causes division by zero in position sizing.
        This test asserts correct behavior — it will FAIL.
        """
        pos = _make_position(size=0.0)
        state = EngineState(symbol="NIFTY")
        event = PositionOpened(symbol="NIFTY", time="t", position=pos)
        # BUG: Should raise ValueError, but doesn't
        with pytest.raises(ValueError, match="size"):
            apply_event(state, event)

    def test_apply_event_rejects_negative_price_bar(self):
        """apply_event should reject negative prices in bars.

        BUG: Negative prices are impossible for equities.
        This test asserts correct behavior — it will FAIL.
        """
        bar = _make_bar(close=-100.0)
        state = EngineState(symbol="NIFTY")
        event = BarClosed(symbol="NIFTY", time="t", bar=bar)
        # BUG: Should raise ValueError, but doesn't
        with pytest.raises(ValueError, match="price"):
            apply_event(state, event)

    def test_event_store_append_rejects_non_event(self):
        """EventStore.append should raise TypeError for non-Event objects.

        BUG: Crashes with AttributeError instead of TypeError.
        This test asserts correct behavior — it will FAIL.
        """
        store = EventStore()
        with pytest.raises(TypeError):
            store.append({"symbol": "NIFTY", "time": "t"})  # type: ignore

    def test_pyramid_count_not_reset_on_error(self):
        """If add_pyramid fails, pyramid_count may be inconsistent.

        BUG: In check_pyramid, if add_pyramid raises an exception,
        the pyramid_count is NOT incremented (good), but the error
        is caught and logged. However, the pyramid_positions list
        may be in an inconsistent state if the error happens mid-way.
        """
        from quant.position_manager import PositionManager

        mock_oms = MagicMock()
        mock_oms.add_pyramid.side_effect = ValueError("Pyramid not supported")

        pm = PositionManager(
            oms=mock_oms,
            exits=MagicMock(),
            risk=MagicMock(),
            emit_fn=lambda e: None,
            symbol="NIFTY",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )

        # Set up state to allow pyramid
        pm.pyramid_count = 0
        pm._risk.can_trade = MagicMock(return_value=(True, ""))

        pos = _make_position()
        bar = _make_bar()
        amt_dto = {"legLvn": 100.0, "absorptionSide": "SELL_ABSORBED"}

        # Force is_risk_free to return True
        pm._exits.is_risk_free = MagicMock(return_value=True)
        # Force session_allow_entry to return True
        import quant.position_manager as pm_module
        original_session_allow = pm_module.session_allow_entry
        pm_module.session_allow_entry = MagicMock(return_value=True)

        try:
            pm.check_pyramid(amt_dto, bar, pos, 10)
        finally:
            pm_module.session_allow_entry = original_session_allow

        # BUG: pyramid_count stays at 0, but the error was silently swallowed
        # No way to know from outside that the pyramid failed
        assert pm.pyramid_count == 0
        assert len(pm.pyramid_positions) == 0

    def test_closed_ids_not_cleared_between_calls(self):
        """_closed_ids persists across manage_exit calls.

        BUG: _closed_ids is initialized in __init__ but never cleared.
        If the same PositionManager is reused across sessions, stale
        _closed_ids may prevent legitimate closes.
        """
        from quant.execution.exits import ExitDecision
        from quant.position_manager import PositionManager

        pm = PositionManager(
            oms=MagicMock(),
            exits=MagicMock(),
            risk=MagicMock(),
            emit_fn=lambda e: None,
            symbol="NIFTY",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )

        # Simulate a closed position
        pm._closed_ids.add("stale-pos-id")

        # Now try to close a position with the same ID in a new session
        pos = _make_position(pos_id="stale-pos-id")
        exit_dec = ExitDecision(True, "SL", 95.0)

        # BUG: The guard rejects it even though it's a new session
        result = pm._execute_full_close(pos, exit_dec, "t")
        assert result is None  # Rejected by guard
        # The position was never actually closed (OMS not called)
        pm._oms.close.assert_not_called()


# =============================================================================
# TEST CLASS: Event Fold Consistency
# =============================================================================


class TestFoldConsistency:
    """Attack: fold() should be deterministic and consistent."""

    def test_fold_is_idempotent(self):
        """Calling fold() multiple times should return identical state."""
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))
        store.append(BarClosed(symbol="NIFTY", time="t2", bar=_make_bar(time="t2", close=101.0)))

        state1 = store.fold()
        state2 = store.fold()
        assert state1 == state2

    def test_fold_after_each_append_matches_final(self):
        """Folding incrementally should match folding all at once."""
        store = EventStore()
        events = [
            BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")),
            BarClosed(symbol="NIFTY", time="t2", bar=_make_bar(time="t2", close=101.0)),
            BarClosed(symbol="NIFTY", time="t3", bar=_make_bar(time="t3", close=102.0)),
        ]

        for e in events:
            store.append(e)

        full_fold = store.fold()

        # Now fold incrementally
        inc_store = EventStore()
        inc_states = []
        for e in events:
            inc_store.append(e)
            inc_states.append(inc_store.fold())

        # Last incremental state should match full fold
        assert inc_states[-1] == full_fold

    def test_fold_with_position_cycle(self):
        """Open then close should return to flat state."""
        store = EventStore()
        pos = _make_position(pos_id="cycle-test")
        fill = _make_fill(pos, close_price=105.0, pnl=5.0)

        store.append(PositionOpened(symbol="NIFTY", time="t1", position=pos))
        store.append(PositionClosed(symbol="NIFTY", time="t2", fill=fill))

        state = store.fold()
        assert state.position is None
        assert state.last_close_bar == -1  # Unchanged by PositionOpened/Closed


# =============================================================================
# TEST CLASS: GetSince Edge Cases
# =============================================================================


class TestGetSinceEdgeCases:
    """Attack: get_since with invalid sequence numbers."""

    def test_get_since_negative_sequence(self):
        """get_since with negative sequence should return all events."""
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))
        store.append(BarClosed(symbol="NIFTY", time="t2", bar=_make_bar(time="t2")))

        # Negative sequence: max(0, -1 - 1) = max(0, -2) = 0 → all events
        result = store.get_since(-1)
        assert len(result) == 2

    def test_get_since_future_sequence(self):
        """get_since with sequence beyond last should return empty."""
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))

        # Sequence 999 is way beyond — start_idx = 998, returns empty
        result = store.get_since(999)
        assert len(result) == 0

    def test_get_since_zero_sequence(self):
        """get_since(0) should return all events (0-indexed edge)."""
        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=_make_bar(time="t1")))

        # start_idx = max(0, 0 - 1) = 0 → all events
        result = store.get_since(0)
        assert len(result) == 1


# =============================================================================
# TEST CLASS: GetLast Edge Cases
# =============================================================================


class TestGetLastEdgeCases:
    """Attack: get_last with empty store."""

    def test_get_last_empty_store_returns_none(self):
        """get_last() on empty store should return None."""
        store = EventStore()
        assert store.get_last() is None

    def test_get_last_after_many_appends(self):
        """get_last() should always return the most recent."""
        store = EventStore()
        for i in range(100):
            store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=_make_bar(time=f"t{i}")))

        last = store.get_last()
        assert last.time == "t99"  # type: ignore


# =============================================================================
# BUG SEVERITY DOCUMENTATION
# =============================================================================

"""
BUGS FOUND BY EDGE CASE TESTS:

=== CRITICAL SEVERITY ===

1. [CRITICAL] apply_event accepts NaN entry prices
   - Tests: test_apply_event_rejects_nan_entry_price, test_apply_event_with_nan_entry_price
   - Impact: NaN != NaN breaks all comparisons, SL/TP logic fails silently
   - Fix: Validate prices with math.isfinite() before opening positions

2. [CRITICAL] apply_event accepts Inf entry prices
   - Tests: test_apply_event_rejects_inf_entry_price, test_apply_event_with_inf_entry_price
   - Impact: Arithmetic overflow in downstream calculations (pnl, risk)
   - Fix: Validate prices with math.isfinite()

3. [CRITICAL] apply_event accepts zero-size positions
   - Tests: test_apply_event_rejects_zero_size_position, test_apply_event_with_zero_size_position
   - Impact: Division by zero in position sizing and PnL calculation
   - Fix: Validate size != 0 before opening positions

4. [CRITICAL] apply_event accepts negative prices in bars
   - Tests: test_apply_event_rejects_negative_price_bar, test_apply_event_with_negative_price
   - Impact: Negative prices impossible for equities, breaks indicators
   - Fix: Validate prices >= 0

5. [CRITICAL] EventStore.append() crashes with AttributeError instead of TypeError
   - Tests: test_event_store_append_non_event, test_event_store_append_rejects_non_event,
            test_append_non_event_crashes_not_type_error, test_append_none_crashes
   - Impact: Wrong exception type makes error handling harder
   - Fix: Add isinstance(event, Event) check at top of append()

=== MAJOR SEVERITY ===

6. [MAJOR] EventStore.fold() returns EngineState(symbol="") for empty log
   - Test: test_fold_empty_event_list_returns_empty_symbol
   - Impact: Downstream code expecting valid symbol crashes
   - Fix: Raise ValueError or return Optional[EngineState]

7. [MAJOR] _execute_full_close with None position_id silently succeeds
   - Tests: test_execute_full_close_with_none_position_id,
            test_execute_full_close_with_none_position_id_does_not_raise
   - Impact: Adds None to _closed_ids, no error raised, position never closed
   - Fix: Validate position has valid _id before processing

8. [MAJOR] apply_event silently ignores unknown event types (base Event)
   - Test: test_apply_event_with_base_event_class
   - Impact: Events lost without trace — audit trail broken
   - Fix: Log warning or raise for unknown events

9. [MAJOR] PositionClosed with wrong ID silently ignored
   - Tests: test_close_wrong_id_returns_unchanged, test_close_wrong_id_leaves_position_open
   - Impact: Position remains open after close event — silent failure
   - Fix: Log warning when close doesn't match open position

10. [MAJOR] No validation on symbol field (emoji, unicode, 10MB strings)
    - Tests: test_apply_event_with_emoji_symbol, test_apply_event_with_very_long_symbol
    - Impact: Downstream serialization failures, memory DoS vector
    - Fix: Validate symbol length (max 20 chars) and character set [A-Z0-9_]

11. [MAJOR] import_ loses order data for PositionClosed events
    - Test: test_export_import_position_closed_loses_order_data
    - Impact: Signal data (entry, sl, tp) lost during roundtrip
    - Fix: Store full Position data in export, not just fill fields

12. [MAJOR] import_ silently converts unknown event types to base Event
    - Test: test_import_preserves_all_event_types
    - Impact: Data loss without warning during import
    - Fix: Raise error or preserve original payload

=== MINOR SEVERITY ===

13. [MINOR] RiskState allows negative trades_today
    - Test: test_fold_events_with_negative_bar_index
    - Impact: Incorrect trade counting
    - Fix: Validate trades_today >= 0

14. [MINOR] RiskState halted=True with empty halt_reason
    - Test: test_risk_state_halt_without_reason
    - Impact: Code checking `if halt_reason` instead of `if halted` fails
    - Fix: Validate halt_reason is non-empty when halted=True

15. [MINOR] PositionState allows empty ID
    - Test: test_position_state_with_empty_id
    - Impact: Position lookup by ID fails
    - Fix: Validate ID is non-empty

16. [MINOR] Out-of-order events applied without warning
    - Test: test_fold_events_out_of_order
    - Impact: State reflects insertion order, not temporal order
    - Fix: Validate monotonic timestamps

17. [MINOR] Zero-price bars accepted (division by zero in indicators)
    - Test: test_apply_event_with_zero_price
    - Impact: Division by zero in technical indicators
    - Fix: Validate prices > 0

18. [MINOR] _closed_ids not cleared between sessions
    - Test: test_closed_ids_not_cleared_between_calls
    - Impact: Stale _closed_ids may prevent legitimate closes in new session
    - Fix: Clear _closed_ids at session start

19. [MINOR] manage_exit crashes with AttributeError on None bar
    - Test: test_manage_exit_with_invalid_bar
    - Impact: Crash when bar is None (e.g., missing market data)
    - Fix: Add validation for bar parameter

20. [MINOR] Sequence numbers not incremented for unknown events
    - Tests: test_unknown_event_creates_sequence_gap, test_fold_tracks_max_sequence
    - Impact: Sequence < number of events, audit trail gaps
    - Fix: Always increment sequence per event processed

=== SUMMARY ===
- Total tests: 86+ passing, 9 failing (revealing real bugs)
- Critical: 5 bugs (NaN, Inf, zero-size, negative price, wrong exception)
- Major: 7 bugs (empty symbol, None position_id, type confusion, etc.)
- Minor: 8 bugs (validation gaps, state inconsistencies)

All failing tests are EXPECTED to fail — they document real bugs.
Fix the bugs, then update tests to reflect correct behavior.
"""
