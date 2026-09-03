# tests/quant/test_event_store_roundtrip_real.py
"""Phase 2: EventStore export/import round-trip for REAL engine payloads.

The pre-fix ``_dict_to_event`` decoded every ``PositionOpened`` payload into a
``PositionState`` by reading keys (``id``/``entry``/``sl``/``tp``) that an
execution ``Position`` never serializes (it exports ``order``/``open_price``/
``_id``), so a round-trip of a real engine event log produced a position with
entry=0.0, sl=0.0 and an empty id, and ``PositionReduced`` was dropped
entirely. These tests pin the fix: export -> import -> fold must reproduce
the same EngineState for the full state-relevant event stream.
"""
from __future__ import annotations

import pytest

from quant.decision.signal_builder import Signal
from quant.event_store import EventStore
from quant.events import (
    BarClosed,
    PositionClosed,
    PositionOpened,
    PositionReduced,
    RiskUpdated,
)
from quant.execution.order import Fill, Order, Position
from quant.execution.risk import RiskState
from quant.state_machine import Bar as StateBar, PositionState


def _signal(side="LONG", entry=100.0, sl=90.0, tp=120.0):
    return Signal(
        type=side,
        reason="Triple-A setup",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=2.0,
        model_label="Triple-A",
        symbol="NIFTY",
        timestamp="1700000000",
    )


def _position(size=4.0, _id="pos-1", is_pyramid=False, pyramid_level=0):
    sig = _signal()
    return Position(
        order=Order(signal=sig, quantity=abs(size)),
        open_price=sig.entry,
        open_time=sig.timestamp,
        size=size,
        pyramid_level=pyramid_level,
        is_pyramid=is_pyramid,
        _id=_id,
    )


def _partial(position, fraction=0.5, price=110.0, time="1700000060"):
    closed_size = position.size * fraction
    remaining_size = position.size * (1.0 - fraction)
    pnl = (price - position.open_price) * closed_size
    fill = Fill(
        position=Position(
            order=position.order,
            open_price=position.open_price,
            open_time=position.open_time,
            size=closed_size,
            realized_pnl=pnl,
            pyramid_level=position.pyramid_level,
            is_pyramid=position.is_pyramid,
            _id=position._id,
        ),
        close_price=price,
        close_time=time,
        reason="TP1",
        pnl=pnl,
    )
    remaining = Position(
        order=position.order,
        open_price=position.open_price,
        open_time=position.open_time,
        size=remaining_size,
        pyramid_level=position.pyramid_level,
        is_pyramid=position.is_pyramid,
        _id=position._id,
    )
    return fill, remaining


def _risk_state():
    return RiskState(
        daily_pnl=75.0,
        consecutive_losses=0,
        halted=False,
        halt_reason="",
        risk_per_trade_pct=0.005,
        trades_today=1,
        equity=1_000_000.0,
        cushion_tier="CUSHION",
    )


def _real_engine_sequence() -> list:
    """Open -> bar -> partial (TP1) -> close runner -> risk update, all with
    the REAL execution types the engine emits through ``QuantEngine._emit``."""
    pos = _position(size=4.0)
    fill, remaining = _partial(pos, fraction=0.5)
    close_fill = Fill(
        position=remaining,
        close_price=105.0,
        close_time="1700000100",
        reason="SESSION_CLOSE",
        pnl=(105.0 - pos.open_price) * remaining.size,
    )
    return [
        PositionOpened(symbol="NIFTY", time="t0", position=pos),
        BarClosed(
            symbol="NIFTY",
            time="t1",
            bar=StateBar(time="t1", close=110.0, delta=0.5),
        ),
        PositionReduced(
            symbol="NIFTY", time="t2", fill=fill, remaining=remaining
        ),
        PositionClosed(symbol="NIFTY", time="t3", fill=close_fill),
        RiskUpdated(symbol="NIFTY", time="t4", risk=_risk_state()),
    ]


class TestRealPayloadRoundTrip:
    def _round_trip(self, events):
        store1 = EventStore()
        for evt in events:
            store1.append(evt)
        exported = store1.export()
        store2 = EventStore()
        store2.import_(exported)
        return store1, store2, exported

    def test_position_opened_survives_with_signal_data(self):
        """Entry/SL/TP/id survive: the pre-fix decode zeroed them."""
        store1, store2, _ = self._round_trip(
            [PositionOpened(symbol="NIFTY", time="t0", position=_position())]
        )
        state2 = store2.fold()
        assert state2.position is not None
        assert state2.position.id == "pos-1"
        assert state2.position.entry == pytest.approx(100.0)
        assert state2.position.sl == pytest.approx(90.0)
        assert state2.position.tp == pytest.approx(120.0)
        assert state2.position.size == pytest.approx(4.0)
        # Same state as the original store's fold.
        assert state2.position == store1.fold().position

    def test_position_reduced_round_trips_size(self):
        """The reduced survivor size survives the round-trip."""
        pos = _position(size=4.0)
        fill, remaining = _partial(pos, fraction=0.5)
        store1, store2, _ = self._round_trip(
            [
                PositionOpened(symbol="NIFTY", time="t0", position=pos),
                PositionReduced(symbol="NIFTY", time="t2", fill=fill, remaining=remaining),
            ]
        )
        state2 = store2.fold()
        assert state2.position.size == pytest.approx(2.0)
        assert state2.position.id == pos._id

    def test_full_sequence_folds_identically_and_chain_verifies(self):
        """export -> import -> fold == original fold, and the new store's
        checksum chain verifies."""
        store1, store2, exported = self._round_trip(_real_engine_sequence())
        state1, state2 = store1.fold(), store2.fold()
        assert state1 == state2
        assert state2.position is None  # flat after close
        assert state2.pyramids == ()
        assert state2.risk.daily_pnl == pytest.approx(75.0)
        assert store2.verify_chain() is True
        # Bar delta survives (lossless bar payload).
        assert state2.last_bar.delta == pytest.approx(0.5)

    def test_reimport_stability(self):
        """export(import(export(x))) is stable — the chain survives a second
        round-trip with the reconstructed payloads."""
        store1, store2, _ = self._round_trip(_real_engine_sequence())
        store3 = EventStore()
        store3.import_(store2.export())
        assert store3.fold() == store1.fold()
        assert store3.verify_chain() is True

    def test_legacy_position_state_shape_still_decodes(self):
        """PositionState-shaped payloads (legacy test fixtures) still decode
        to an object exposing ``.id`` (pinned by test_event_store_hardening)."""
        store1 = EventStore()
        pos = PositionState(
            id="abc", entry=100, size=100, sl=95, tp=110, side="LONG"
        )
        store1.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        store2 = EventStore()
        store2.import_(store1.export())
        imported = store2.get_all()[0]
        assert isinstance(imported, PositionOpened)
        assert imported.position.id == "abc"
        assert store2.fold().position.entry == pytest.approx(100.0)