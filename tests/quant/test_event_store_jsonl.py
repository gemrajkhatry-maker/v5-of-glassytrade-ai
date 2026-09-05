"""Tests for ``EventStore.export_to_jsonl`` — streaming JSONL export.

The method must write one export row per line WITHOUT materializing the full
row list in memory: it consumes the lazy :class:`EventExport` view strictly
through the iteration path (never indexing, which is the memoization path),
so a 1M-event log never becomes ~500MB of dicts.

The output must be byte-stable (``sort_keys``) and lossless: each line is
exactly the row dict ``export()`` produces, so the file round-trips through
``import_()`` and tamper detection stays intact.
"""
from __future__ import annotations

import json

import pytest

from quant.decision.signal_builder import Signal
from quant.event_store import EventExport, EventStore
from quant.events import (
    BarClosed,
    PositionClosed,
    PositionOpened,
    PositionReduced,
    RiskUpdated,
)
from quant.execution.order import Fill, Order, Position
from quant.execution.risk import RiskState
from quant.state_machine import Bar


def _bar(i: int = 0) -> Bar:
    return Bar(
        time=f"2026-01-01T09:{i % 60:02d}:00",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5 + i,
        volume=1000.0 + i,
    )


def _bar_closed(i: int = 0) -> BarClosed:
    return BarClosed(symbol="NIFTY", time=f"2026-01-01T09:{i % 60:02d}:00", bar=_bar(i))


def _signal():
    return Signal(
        type="LONG",
        reason="Triple-A setup",
        entry=100.0,
        sl=90.0,
        tp=120.0,
        rr=2.0,
        model_label="Triple-A",
        symbol="NIFTY",
        timestamp="1700000000",
    )


def _position(size=4.0, _id="pos-1"):
    sig = _signal()
    return Position(
        order=Order(signal=sig, quantity=abs(size)),
        open_price=sig.entry,
        open_time=sig.timestamp,
        size=size,
        _id=_id,
    )


def _state_sequence():
    """A state-relevant stream: open -> partial -> close -> risk update."""
    pos = _position(size=4.0)
    fill = Fill(
        position=pos,
        close_price=105.0,
        close_time="1700000060",
        reason="TP1",
        pnl=20.0,
    )
    close_fill = Fill(
        position=pos,
        close_price=110.0,
        close_time="1700000100",
        reason="SESSION_CLOSE",
        pnl=40.0,
    )
    risk = RiskState(
        daily_pnl=60.0,
        consecutive_losses=0,
        halted=False,
        halt_reason="",
        risk_per_trade_pct=0.005,
        trades_today=1,
        equity=1_000_060.0,
        cushion_tier="CUSHION",
    )
    return [
        PositionOpened(symbol="NIFTY", time="t0", position=pos),
        PositionReduced(symbol="NIFTY", time="t2", fill=fill, remaining=pos),
        PositionClosed(symbol="NIFTY", time="t3", fill=close_fill),
        RiskUpdated(symbol="NIFTY", time="t4", risk=risk),
    ]


def _read_rows(path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class TestExportToJsonl:
    def test_writes_one_row_per_line_matching_export(self, tmp_path):
        """Each line is exactly an export() row, in order; count returned."""
        store = EventStore()
        for i in range(10):
            store.append(_bar_closed(i))
        path = tmp_path / "log.jsonl"

        rows_written = store.export_to_jsonl(path)

        assert rows_written == 10
        lines = path.read_text().splitlines()
        assert len(lines) == 10
        assert _read_rows(path) == list(store.export())

    def test_round_trip_via_import_preserves_folded_state(self, tmp_path):
        """File -> import_ -> fold reproduces the original store's fold."""
        store1 = EventStore()
        for evt in _state_sequence():
            store1.append(evt)
        path = tmp_path / "log.jsonl"
        assert store1.export_to_jsonl(path) == 4

        store2 = EventStore()
        store2.import_(_read_rows(path))
        assert store1.fold() == store2.fold()
        assert store2.verify_chain() is True

    def test_tampered_line_is_rejected_on_import(self, tmp_path):
        """A modified JSONL row is caught by import_'s checksum verification."""
        store = EventStore()
        for i in range(5):
            store.append(_bar_closed(i))
        path = tmp_path / "log.jsonl"
        store.export_to_jsonl(path)

        rows = _read_rows(path)
        rows[2]["payload"]["bar"]["close"] = 9999.0
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")

        fresh = EventStore()
        with pytest.raises(ValueError, match="checksum mismatch"):
            fresh.import_(_read_rows(path))

    def test_empty_store_writes_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        assert EventStore().export_to_jsonl(path) == 0
        assert path.read_text() == ""

    def test_existing_file_is_truncated(self, tmp_path):
        """The destination is overwritten, not appended to."""
        path = tmp_path / "log.jsonl"
        path.write_text("stale garbage\nnot jsonl\n")

        store = EventStore()
        store.append(_bar_closed(0))
        assert store.export_to_jsonl(path) == 1

        lines = _read_rows(path)
        assert len(lines) == 1
        assert lines[0]["sequence"] == 1

    def test_output_is_byte_stable(self, tmp_path):
        """sort_keys serialization → identical files across writes."""
        store = EventStore()
        for i in range(10):
            store.append(_bar_closed(i))

        p1 = tmp_path / "a.jsonl"
        p2 = tmp_path / "b.jsonl"
        store.export_to_jsonl(p1)
        store.export_to_jsonl(p2)
        assert p1.read_bytes() == p2.read_bytes()

    def test_fsync_flag_path(self, tmp_path):
        store = EventStore()
        for i in range(3):
            store.append(_bar_closed(i))
        path = tmp_path / "fsynced.jsonl"
        assert store.export_to_jsonl(path, fsync=True) == 3
        assert len(_read_rows(path)) == 3

    def test_pathlike_input(self, tmp_path):
        from pathlib import Path

        store = EventStore()
        store.append(_bar_closed(0))
        path = Path(tmp_path) / "log.jsonl"
        assert store.export_to_jsonl(path) == 1
        assert path.exists()

    def test_streams_via_iteration_never_indexes(self, tmp_path, monkeypatch):
        """The writer must consume the export through iteration ONLY.

        Indexing is the memoization/mutation path — a streaming writer that
        indexed rows would retain them (and, on a huge log, materialize the
        whole export). The view subclass below raises on any __getitem__ so
        this test deterministically proves the method streams.
        """
        store = EventStore()
        for i in range(20):
            store.append(_bar_closed(i))

        class _ForbidIndexing(EventExport):
            def __getitem__(self, index):
                raise AssertionError(
                    "export_to_jsonl must stream rows via iteration, never "
                    "index them (indexing is the retention path)"
                )

        monkeypatch.setattr(
            store,
            "export",
            lambda: _ForbidIndexing(list(store._events), list(store._checksums)),
        )
        path = tmp_path / "log.jsonl"
        assert store.export_to_jsonl(path) == 20
        assert len(_read_rows(path)) == 20


def test_self_referential_payload_serializes_without_recursion():
    """A payload holding a self-referential object must append (and checksum)
    instead of crashing the emit path with RecursionError."""
    from dataclasses import dataclass

    from quant.events import Event

    @dataclass(frozen=True)
    class _LoopEvent(Event):
        payload: object = None

    @dataclass
    class _Node:
        name: str = "n"
        child: object = None

    node = _Node()
    node.child = node  # cycle

    store = EventStore()
    seq = store.append(_LoopEvent(symbol="S", time="t0", payload=node))
    assert seq >= 1
    row = store.export()[0]
    assert "<cycle>" in json.dumps(row)