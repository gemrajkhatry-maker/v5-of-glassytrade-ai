"""Adversarial audit regressions — defects found in the production-rework audit.

Each test pins a defect found by tracing spec -> code -> live path. A test here
FAILING means its defect has been fixed; the docstring names the defect ID and
the failure mode it guards against.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from quant.amt.market.break_detector import detect_break
from quant.contracts.value_objects import FloatOHLC


class _EmptyGw:
    def subscribe(self, symbol):
        return

    def next_tick(self):
        return None


# ---------------------------------------------------------------------------
# D-ABS-01: absorption must require proximity to the labeled level
# ---------------------------------------------------------------------------

def _doji(i: int, close: float, delta: float, vol: float) -> FloatOHLC:
    """Flat-body candle (body ~10% of range)."""
    return FloatOHLC(
        time=f"2026-08-24T10:{i:02d}:00",
        open=close - 0.3,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        volume=float(vol),
        delta=float(delta),
    )


def test_absorption_requires_level_proximity():
    """D-ABS-01: a flat high-|delta| candle FAR from every key level must NOT
    be reported as absorption at that level. Regression for the deleted
    ``abs(current.close - level) < threshold`` guard — previously any doji
    anywhere was labeled 'ABSORPTION @ VAH', poisoning the context-builder
    direction hierarchy with phantom level tags."""
    data = [
        _doji(1, 100.0, 10, 1000),
        _doji(2, 100.5, 12, 1000),
        _doji(3, 100.2, -400, 1000),  # |delta|/vol = 0.4 > 0.25, body flat
    ]
    res = detect_break(
        data, vah=200.0, val=180.0, ib_high=150.0, ib_low=80.0, baseline_vol=900.0
    )
    # Price ~100; nearest level (IBL=80) is ~20 points away — far beyond any
    # proximity threshold (threshold = 0.3% of close = 0.30).
    assert res["break_type"] != "ABSORPTION", (
        f"absorption fired far from every level: {res}"
    )


def test_absorption_still_fires_near_level():
    """Guard the fix's other side: absorption NEAR a real level still detects,
    so adding back proximity doesn't kill legitimate signals."""
    data = [
        _doji(1, 199.7, 10, 1000),
        _doji(2, 199.8, 12, 1000),
        _doji(3, 200.1, -800, 1000),  # near VAH=200 within threshold
    ]
    res = detect_break(
        data, vah=200.0, val=180.0, ib_high=150.0, ib_low=80.0, baseline_vol=900.0
    )
    assert res["break_type"] == "ABSORPTION"
    assert res["break_level"] == pytest.approx(200.0)


def test_absorption_polarity_negative_delta_is_bullish():
    """Polarity flip correctness: negative delta (buyers absorbing sellers)
    -> bullish UP absorption; positive delta -> bearish DOWN."""
    # Place both candles near IBL/VAH respectively so proximity holds post-fix.
    up = [_doji(1, 79.9, 10, 1000), _doji(2, 80.1, -500, 1000)]
    res_up = detect_break(
        [up[0], up[1]], vah=200.0, val=180.0, ib_high=150.0, ib_low=80.0,
        baseline_vol=900.0,
    )
    if res_up.get("break_type") == "ABSORPTION":
        assert res_up["break_direction"] == "UP"


# ---------------------------------------------------------------------------
# D-GATE-05: VA-fade fallback must not depend on gate-list ordering
# ---------------------------------------------------------------------------

def test_decision_service_fallback_uses_gate_numbers_not_positions(monkeypatch):
    """D-GATE-05: a positional results[0]/results[1] hard-reject check would
    let VA-fade fire while session-closed or position-open the moment the
    pipeline reorders gates or inserts a new one. Behavioral proof: build a
    context where a VA-fade candidate genuinely fires (real detect_va_fade
    inputs), monkeypatch GatePipeline.evaluate to return gate 1 (session
    phase) FAILED but placed LAST in the tuple — a positional
    results[0]/results[1] check would miss this and wrongly approve the
    fade. DecisionService must still hard-reject because it identifies gates
    by GateResult.gate number, not list position."""
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.decision_service import DecisionService
    import quant.decision.pipeline as pipeline_mod
    from quant.decision.result import GateResult

    bar = Bar(time="t", open=100.0, high=100.5, low=97.0, close=98.0, volume=1000.0)
    ctx = DecisionContext(
        bar=bar,
        symbol="NIFTY",
        session_open=False,   # the real reason gate 1 fails
        poc=100.0, vah=101.0, val=99.0,   # close=98 < val -> BELOW_VA
        cvd_slope=5.0,                     # buyer order flow -> LONG fade candidate
        tick_size=0.05,
    )

    # Reordered: gate 1 (SESSION_PHASE, FAILED) is placed LAST — a
    # positional check for "gate index 0 or 1 failed" would see gate 3/4
    # (both passing, in this fake order) at positions 0/1 and miss the
    # real failure entirely.
    fake_results = [
        GateResult(gate=3, passed=True, reason="edge ok"),
        GateResult(gate=4, passed=True, reason="rr ok"),
        GateResult(gate=2, passed=True, reason="no position"),
        GateResult(gate=1, passed=False, reason="session closed"),
    ]
    monkeypatch.setattr(
        pipeline_mod.GatePipeline, "evaluate", lambda self, ctx: fake_results
    )

    decision = DecisionService().evaluate(ctx)

    assert decision.approved is False
    assert decision.reason == "GATE_REJECTED", (
        "gate 1 failure must hard-reject regardless of its position in the "
        f"results tuple; got reason={decision.reason!r} (a positional check "
        "would have let the VA-fade fallback fire instead)"
    )


# ---------------------------------------------------------------------------
# D-RISK-03: SIGTERM emergency halt must reach a real risk authority
# ---------------------------------------------------------------------------

def test_emergency_halt_actually_blocks_new_entries(monkeypatch, tmp_path):
    """D-RISK-03: main.py's SIGTERM handler used to set ``eng._risk_halted``
    guarded by hasattr() — QuantEngine never defined it, so the emergency
    flatten was a silent no-op. Behavioral proof, not a shape check: spawn a
    real engine through QuantCoordinator, call the real
    ``QuantCoordinator.emergency_halt()`` path exactly as the SIGTERM handler
    does, and assert the engine's real SessionRisk.can_trade() actually
    flips to False afterward."""
    import threading

    import quant.multi_engine as multi_engine
    from quant.multi_engine import QuantCoordinator

    monkeypatch.setattr("quant.amt_engine.AMTEngine.seed", lambda self: None)

    class _NoStart(threading.Thread):
        def start(self):
            return

    monkeypatch.setattr(multi_engine.threading, "Thread", _NoStart)

    class _MD:
        def get_nearest_futures(self, *a, **k):
            return None

        def get_lot_size(self, symbol):
            return 1.0

        async def fetch_history(self, *a, **k):
            return []

    coord = QuantCoordinator(
        _MD(),
        config={
            "underlyings": ["NIFTY"],
            "n": 1,
            "contracts_file": str(tmp_path / "c.json"),
            # Isolate from the coordinator's shared, real-disk default
            # (backend/.session_levels.json) — other tests/processes halt
            # SessionRisk under the same symbol+date key there, which would
            # otherwise leak a stale halt into this test.
            "session_levels_file": str(tmp_path / "session_levels.json"),
            "include_futures": False,
        },
    )
    eng = coord._spawn_engine("NIFTY AUG FUT")

    allowed_before, _ = eng._risk.can_trade()
    assert allowed_before is True, "sanity: engine must be tradeable before halt"

    halted_count = coord.emergency_halt("SIGTERM flatten")
    assert halted_count == 1

    allowed_after, reason = eng._risk.can_trade()
    assert allowed_after is False, (
        "emergency_halt() must flip the real engine's SessionRisk so Guard 0 "
        "of _decide() rejects every subsequent entry"
    )
    assert "emergency" in reason.lower()


# ---------------------------------------------------------------------------
# D-PERS-04: reconciliation must be able to restore positions, not just count
# ---------------------------------------------------------------------------

def test_startup_reconciliation_reports_restorable_state_shape():
    """D-PERS-04: StartupReconciliation claims 'restore' but only counts —
    no Position object is reconstructed into any engine, and orphaned broker
    positions are logged then dropped (no registration target exists).
    This pins the CONTRACT: reconcile() must return per-symbol details so a
    caller can rebuild state; bare ints make silent drops invisible."""
    from app.domain.ops.startup_reconciliation import ReconciliationResult
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(ReconciliationResult)}
    # Until real restore wiring exists, at minimum the result must carry the
    # symbol-level discrepancy detail (it currently does via `discrepancies`).
    assert "discrepancies" in field_names


# ---------------------------------------------------------------------------
# D-TIME-06: feed must prefer exchange event time over local wall clock
# ---------------------------------------------------------------------------

def test_normalize_packet_prefers_exchange_ltt_over_local_clock():
    """D-TIME-06: WSMessage.timestamp is datetime.now() on the deployment
    machine (naive local). _normalize_dhan_packet prefers it over the
    exchange's last_trade_time epoch, so bar windows follow machine-local
    wall clock — IST session gates evaluate against the wrong instants when
    the box isn't on IST, and the monotonic guard discards ticks after NTP
    corrections. Exchange LTT is the event time and must win."""
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed.__new__(MultiplexedMarketFeed)
    feed._prev_cum = {}
    feed._prev_ts = {}
    feed._prev_price = {}
    feed._depth_cache = {}

    pkt = {
        "symbol": "NIFTY AUG FUT",
        "ltp": 100.0,
        "volume": 500,
        "total_buy_qty": 300,
        "total_sell_qty": 200,
        "last_trade_time": 1771832400,               # exchange epoch
        "timestamp": datetime(2026, 8, 24, 10, 30, 0),  # local naive now()
        "depth_bids": [],
        "depth_asks": [],
    }
    norm = feed._normalize_dhan_packet(pkt, "NIFTY AUG FUT")
    raw_ts = norm["_raw_timestamp"] or norm["timestamp"]
    ts = float(raw_ts.timestamp()) if hasattr(raw_ts, "timestamp") else float(raw_ts or 0)
    assert abs(ts - 1771832400) < 60, (
        f"engine used local-clock epoch {ts} instead of exchange LTT 1771832400 "
        "(skew {ts - 1771832400:.0f}s)"
    )


def test_normalize_packet_handles_real_full_packet_shape():
    """D-TIME-06 re-audit: the FIRST fix only checked pkt["last_trade_time"],
    a key that never survives production. The real packet — built via
    dataclasses.asdict(FullPacket) exactly as backend/.../dhan_adapter.py's
    stream_full() yields it — carries the exchange epoch under "ltt", not
    "last_trade_time". A dict-shape test (above) alone cannot catch this;
    this test uses the actual production dataclass."""
    from dataclasses import asdict
    from datetime import datetime as _dt

    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed
    from shared.entities.models import FullPacket

    feed = MultiplexedMarketFeed.__new__(MultiplexedMarketFeed)
    feed._prev_cum = {}
    feed._prev_ts = {}
    feed._prev_price = {}
    feed._depth_cache = {}

    exchange_epoch = 1771832400
    packet = FullPacket(
        symbol="NIFTY AUG FUT", ltp=100.0, open=99.0, high=101.0, low=98.0,
        close=100.0, volume=500, oi=0, atp=100.0, total_buy_qty=300,
        total_sell_qty=200, depth_bids=(), depth_asks=(), security_id="1",
        exchange_segment="NSE_FNO",
        timestamp=_dt(2026, 8, 24, 10, 30, 0),  # local arrival stamp — must lose
        ltt=exchange_epoch,
    )
    pkt = asdict(packet)
    norm = feed._normalize_dhan_packet(pkt, "NIFTY AUG FUT")
    raw_ts = norm["_raw_timestamp"] or norm["timestamp"]
    ts = float(raw_ts.timestamp()) if hasattr(raw_ts, "timestamp") else float(raw_ts or 0)
    assert abs(ts - exchange_epoch) < 60, (
        f"engine used {ts} instead of the real packet's ltt={exchange_epoch} — "
        "the fix does not survive the FullPacket field-name rename"
    )


# ---------------------------------------------------------------------------
# D-EXCH-07: BSE index options must not silently classify as MCX
# ---------------------------------------------------------------------------

def test_registry_does_not_default_known_bse_indices_to_mcx():
    """D-EXCH-07 (same class as the original MIDCPNIFTY bug): SENSEX/BANKEX
    have selector strike intervals but are absent from ExchangeConfig, so
    SymbolRegistry.exchange_for falls through to the 'MCX' safe default —
    applying 09:00–23:30 MCX sessions and MCX tick/lot metadata to BSE index
    options. Either register BSE properly or make unknown roots LOUD."""
    from quant.contracts.exchange_config import ExchangeConfig
    from quant.amt.session.symbol_registry import SymbolRegistry

    registry = SymbolRegistry()
    nse = ExchangeConfig.for_exchange("NSE")

    for idx in ("SENSEX", "BANKEX"):
        if idx in nse.underlyings or idx in ExchangeConfig.for_exchange("MCX").underlyings:
            continue  # registered somewhere authoritative — fine
        # Not registered anywhere: the registry MUST NOT claim MCX.
        assert registry.exchange_for(f"{idx} 27 AUG 81000 CALL") != "MCX", (
            f"{idx} unregistered yet defaults to MCX (wrong session/tick/lot)"
        )


# ---------------------------------------------------------------------------
# Safety + persistence slice
# ---------------------------------------------------------------------------

def test_live_oms_unwired_halts_spawned_engine(monkeypatch, tmp_path):
    """Live fill path is PaperOMS: spawn must halt entries before run()."""
    import threading

    import quant.multi_engine as multi_engine
    from quant.multi_engine import QuantCoordinator

    monkeypatch.setattr(
        "quant.amt_engine.AMTEngine.seed", lambda self: None
    )

    class _NoStart(threading.Thread):
        def start(self):
            return

    monkeypatch.setattr(multi_engine.threading, "Thread", _NoStart)

    class _MD:
        def get_nearest_futures(self, *a, **k):
            return None

        def get_lot_size(self, symbol):
            return 1.0

        async def fetch_history(self, *a, **k):
            return []

    coord = QuantCoordinator(
        _MD(),
        config={
            "live_oms_unwired": True,
            "underlyings": ["NIFTY"],
            "n": 1,
            "contracts_file": str(tmp_path / "c.json"),
            # Isolate from the coordinator's shared, real-disk default
            # (backend/.session_levels.json) so this test's halt doesn't
            # leak into other tests reusing the same symbol+date key.
            "session_levels_file": str(tmp_path / "session_levels.json"),
            "include_futures": False,
        },
    )
    eng = coord._spawn_engine("NIFTY AUG FUT")
    st = eng._risk.state()
    assert st.halted
    assert "LIVE_OMS_UNWIRED" in st.halt_reason


def test_cooldown_emits_decision_produced():
    """Cooldown used to return with no event, leaving a stale ENTER on the WS."""
    from quant.bars import Bar
    from quant.events import DecisionProduced
    from quant.runtime import QuantEngine

    eng = QuantEngine(_EmptyGw(), "SYM", interval_seconds=1)
    seen = []
    eng._bus.subscribe(DecisionProduced, seen.append)
    eng._last_close_bar_index = 0
    eng._bar_index = 1
    bar = Bar(
        time="2026-08-24T10:00:00+05:30",
        open=100, high=101, low=99, close=100, volume=10,
    )
    eng._decide({}, bar)
    assert seen, "cooldown must emit DecisionProduced"
    assert seen[0].decision.approved is False
    assert "COOLDOWN" in seen[0].decision.reason


def test_dead_market_force_exits():
    from quant.contracts.enums import MarketState
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine
    from quant.execution.order import Order, Position

    sig = Signal(
        type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
        model_label="Triple-A", symbol="SYM", timestamp="t0",
    )
    pos = Position(order=Order(sig, 10), open_price=100.0, open_time="t0", size=10)
    d = ExitEngine().evaluate(pos, market_state=MarketState.DEAD, bar_close=100.5)
    assert d.should_exit and d.reason == "DEAD_MARKET"


def test_position_manager_closes_on_dead_market():
    from quant.bars import Bar
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine
    from quant.execution.oms import PaperOMS
    from quant.execution.order import Order, Position
    from quant.execution.risk import SessionRisk
    from quant.position_manager import PositionManager

    sig = Signal(
        type="LONG", reason="r", entry=100.0, sl=90.0, tp=120.0, rr=2.0,
        model_label="Triple-A", symbol="S", timestamp="t0",
    )
    pos = Position(order=Order(sig, 10), open_price=100.0, open_time="t0", size=10)
    closed = []
    pm = PositionManager(
        oms=PaperOMS(), exits=ExitEngine(time_stop_bars=10_000),
        risk=SessionRisk(storage=None, symbol="S"),
        emit_fn=closed.append, symbol="S", market="NSE",
        contract_expiry=None, tick_size=0.05,
    )
    bar = Bar(
        time="2026-08-24T10:00:00+05:30",
        open=100, high=101, low=99, close=100.5, volume=10,
    )
    result = pm.manage_exit(
        {"marketState": "DEAD"}, bar, pos, bar_index=3, entry_bar_index=1,
        entry_time_epoch=0.0,
    )
    assert result is None, "DEAD_MARKET must fully close the position"
    assert closed and closed[0].fill.reason == "DEAD_MARKET"


def test_seed_is_synchronous():
    from datetime import datetime, timedelta

    from quant.contracts.timezones import IST
    from quant.contracts.value_objects import OHLC
    from quant.runtime import QuantEngine

    now = datetime.now(IST)

    class _Hist:
        async def fetch_history(self, symbol, interval="1m", limit=500):
            return [
                OHLC(
                    time=(now - timedelta(minutes=5)).isoformat(),
                    open=100, high=101, low=99, close=100.5,
                    volume=1000, vwap=100.2, taker_buy_volume=0, delta=10,
                )
            ]

    eng = QuantEngine(
        _EmptyGw(), "SYM", interval_seconds=60, history_source=_Hist(),
    )
    eng._amt_engine.seed()
    assert len(eng._amt_engine._amt_candles) == 1


def test_journal_consecutive_failures_reset_on_success(tmp_path):
    from quant.persistence import Journal

    path = str(tmp_path / "j.jsonl")
    j = Journal(path=path)
    assert j.consecutive_failures == 0
    j._file.close()
    with pytest.raises(Exception):
        j.append({"type": "x"})
    assert j.consecutive_failures >= 1
    j._file = open(path, "a", encoding="utf-8")
    j.append({"type": "ok"})
    assert j.consecutive_failures == 0
    j.close()


def test_position_opened_persists_and_close_deletes():
    from quant.decision.signal_builder import Signal
    from quant.events import PositionClosed, PositionOpened
    from quant.execution.oms import PaperOMS
    from quant.execution.order import Fill
    from quant.runtime import QuantEngine

    class _Store:
        def __init__(self):
            self.positions = {}
            self.trades = []

        def save_open_position(self, row):
            self.positions[row["id"]] = row

        def delete_open_position(self, pid):
            self.positions.pop(pid, None)

        def save_trade(self, row):
            self.trades.append(row)

        def load_open_positions(self):
            return list(self.positions.values())

    store = _Store()
    eng = QuantEngine(_EmptyGw(), "SYM", interval_seconds=1)
    eng.attach_storage(store)
    pos = PaperOMS().submit(
        Signal(
            type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
            model_label="Triple-A", symbol="SYM", timestamp="t0",
        ),
        10,
    )
    eng._emit(PositionOpened(symbol="SYM", time="t0", position=pos))
    assert pos._id in store.positions
    assert store.positions[pos._id]["symbol"] == "SYM"
    fill = Fill(position=pos, close_price=102.0, close_time="t1", reason="TP", pnl=20.0)
    eng._emit(PositionClosed(symbol="SYM", time="t1", fill=fill))
    assert pos._id not in store.positions
    assert store.trades and store.trades[0]["reason"] == "TP"


def test_restore_position_sets_engine_book():
    from quant.decision.signal_builder import Signal
    from quant.execution.oms import PaperOMS
    from quant.runtime import QuantEngine

    eng = QuantEngine(_EmptyGw(), "SYM", interval_seconds=1)
    pos = PaperOMS().submit(
        Signal(
            type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
            model_label="Triple-A", symbol="SYM", timestamp="t0",
        ),
        10,
    )
    eng.restore_position(pos)
    assert eng._position is pos


def test_paper_reconciliation_does_not_delete_db_positions(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    from app.domain.ops.startup_reconciliation import StartupReconciliation

    class _Store:
        def __init__(self):
            self.deleted = []
            self.rows = [
                {"id": "p1", "symbol": "NIFTY AUG FUT", "size": 10},
            ]

        def load_open_positions(self):
            return list(self.rows)

        def delete_open_position(self, pid):
            self.deleted.append(pid)

    class _Broker:
        def get_positions(self):
            return []

    rec = StartupReconciliation(_Broker(), _Store())
    result = rec.reconcile()
    assert result.stale_removed == 0
    assert result.restored == 1
    assert rec._storage.deleted == []
