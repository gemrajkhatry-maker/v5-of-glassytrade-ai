# tests/quant/runtime/test_runtime.py
"""QuantEngine runtime tests: ticks -> bars -> coordinator -> decision ->
OMS -> exit -> risk -> journal, all driven deterministically by the engine."""

import pytest

from datetime import datetime, timedelta, timezone

from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import MAX_POSITION_QUANTITY, Signal
from quant.events import DecisionProduced, PositionClosed, PositionOpened, SignalApproved
from quant.runtime import QuantEngine


def _ticks():
    """Quiet range bars @100, absorption spike, then rising closes.

    With interval_seconds=1 the aggregator pairs consecutive ticks into a bar
    (each odd tick closes the prior window), so:
      - ticks t0..t299 alternate 99.95/100.05 -> ~150 quiet bars with a 0.1
        range (keeps avg_range > 0 so the zero-range spike passes range_ok)
      - t300/t301 form the absorption spike bar (zero range, 5x volume, 90% buys)
      - t302..t305 are two accumulation bars at POC -> ABSORBING -> ACCUMULATING
      - t306..t309 rise above vwap.upper_1 -> AGGRESSION -> LONG
    """
    out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 6, 4)
           for i in range(300)]
    out.append(Tick("t300", 100.0, 500, 450, 50))
    for i in range(1, 6):
        out.append(Tick(f"t{300 + i}", 100.0, 10, 6, 4))
    for i, price in enumerate([100.3, 100.6, 100.9, 101.2]):
        out.append(Tick(f"t{306 + i}", price, 10, 6, 4))
    return out


def test_session_scope_keeps_latest_date_only():
    from quant.runtime import QuantEngine
    from quant.contracts.value_objects import OHLC

    # Two sessions: yesterday (2026-08-06) and today (2026-08-07, 6 candles)
    candles = [
        OHLC(time=f"2026-08-06T09:{i:02d}:00+05:30", open=100, high=101, low=99, close=100, volume=10)
        for i in range(3)
    ] + [
        OHLC(time=f"2026-08-07T09:{i:02d}:00+05:30", open=100, high=101, low=99, close=100, volume=10)
        for i in range(6)
    ]
    scoped = QuantEngine._session_scope(candles)
    assert len(scoped) == 6
    assert all(c.time.startswith("2026-08-07") for c in scoped)


def test_session_scope_keeps_only_today_when_thin():
    from quant.runtime import QuantEngine
    from quant.contracts.value_objects import OHLC

    # Today has only 2 candles (< 5) — still keep ONLY today's, never pull
    # prior-day candles back into the "session" profile.
    candles = [
        OHLC(time=f"2026-08-0{6 if i < 4 else 7}T09:{i:02d}:00+05:30",
             open=100, high=101, low=99, close=100, volume=10)
        for i in range(6)
    ]
    scoped = QuantEngine._session_scope(candles)
    assert len(scoped) == 2
    assert all(c.time.startswith("2026-08-07") for c in scoped)


def test_engine_emits_signal_event_for_long():
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1)
    trace = eng.run()
    assert any(isinstance(e, SignalApproved) for e in trace)
    signal_evt = next(e for e in trace if isinstance(e, SignalApproved))
    assert signal_evt.signal.type == "LONG"


def _short_ticks():
    """Mirror of _ticks() with a SELL absorption spike and falling closes.

    SELL absorption (500 vol, 50 buys / 450 sells) -> accumulation at POC ->
    closes falling below vwap.lower_1 -> AGGRESSION -> SHORT. Regression test
    for _decide hard-coding agent_direction="LONG", which made the kernel's
    SHORT edge structurally unreachable (gate 4 requires
    triple_a_signal == agent_direction). The drop must be decisive on the
    trigger bar itself: gate 4 refuses the initiative edge unless the AMT
    analyzer reports IMBALANCED on that same bar (Fabio: the edge exists only
    out of balance), and gate 5 needs the structural stop (vah+step) within
    its 20-tick distance — so the first falling bar lands at ~99.3, clear of
    the session VAL (~99.9x) yet close enough to VAH for a tradeable stop.
    """
    out = [Tick(f"t{i}", 99.9 if i % 2 == 0 else 100.1, 10, 6, 4)
           for i in range(300)]
    out.append(Tick("t300", 100.1, 500, 50, 450))
    for i in range(1, 6):
        out.append(Tick(f"t{300 + i}", 100.1, 10, 6, 4))
    for i, price in enumerate([99.5, 99.3, 99.1, 98.9]):
        out.append(Tick(f"t{306 + i}", price, 10, 6, 4))
    return out


def test_engine_emits_short_signal_for_sell_absorption():
    eng = QuantEngine(SyntheticGateway(_short_ticks()), "SYM", interval_seconds=1)
    trace = eng.run()
    assert any(isinstance(e, SignalApproved) for e in trace), \
        "SHORT edge must be reachable by the deterministic engine"
    signal_evt = next(e for e in trace if isinstance(e, SignalApproved))
    assert signal_evt.signal.type == "SHORT"
    opened = next(e for e in trace if isinstance(e, PositionOpened))
    assert opened.position.size < 0, "SHORT entry must open a negative-size position"


# ---------------------------------------------------------------------------
# Session-phase (Fabio NSE) and warmup enforcement in the live engine
# ---------------------------------------------------------------------------


def _long_price_volume():
    """Price/volume sequence of the LONG session (same as _ticks())."""
    seq = [(99.95 if i % 2 == 0 else 100.05, 10, 6, 4) for i in range(300)]
    seq.append((100.0, 500, 450, 50))
    seq += [(100.0, 10, 6, 4)] * 5
    seq += [(100.3, 10, 6, 4), (100.6, 10, 6, 4), (100.9, 10, 6, 4), (101.2, 10, 6, 4)]
    return seq


def _epoch_ticks(prices, base):
    """Epoch-timed ticks (bar times land inside the given IST window)."""
    return [Tick(str(base + i), p, v, b, s)
            for i, (p, v, b, s) in enumerate(prices)]


def _ist_epoch(hour, minute):
    ist = timezone(timedelta(hours=5, minutes=30))
    return int(datetime(2026, 8, 11, hour, minute, tzinfo=ist).timestamp())


def test_engine_blocks_entries_during_opening_noise():
    """Fabio Phase 1 (09:15-09:30 IST) is DO-NOT-TRADE — gate 1 must block."""
    base = _ist_epoch(9, 20)
    eng = QuantEngine(SyntheticGateway(_epoch_ticks(_long_price_volume(), base)),
                      "SYM", interval_seconds=1)
    trace = eng.run()
    assert not any(isinstance(e, SignalApproved) for e in trace), \
        "engine must not trade in the opening-noise window"


def test_engine_allows_entries_in_primary_window():
    """Control: same session at 10:00 IST (Phase 2) does fire the edge."""
    base = _ist_epoch(10, 0)
    eng = QuantEngine(SyntheticGateway(_epoch_ticks(_long_price_volume(), base)),
                      "SYM", interval_seconds=1)
    trace = eng.run()
    assert any(isinstance(e, SignalApproved) for e in trace)


def test_engine_gate1_blocks_until_warmup_complete():
    base = _ist_epoch(10, 0)
    eng = QuantEngine(SyntheticGateway(_epoch_ticks(_long_price_volume(), base)),
                      "SYM", interval_seconds=1)
    trace = eng.run()
    decisions = [e for e in trace if isinstance(e, DecisionProduced)]
    g1 = [next(g for g in d.decision.gate_results if g.gate == 1) for d in decisions]
    # Decisions fire one per closed bar; warmup requires 15 bars, so gate 1
    # passes only from the 15th bar (index 14).
    assert not g1[13].passed
    assert "Warming up" in g1[13].reason
    assert g1[14].passed


def test_engine_squares_off_position_on_session_close(monkeypatch):
    """Phase 5 / post-market force-exit closes the open position."""
    from quant.runtime import QuantEngine as QE
    eng = QE(SyntheticGateway(_epoch_ticks(_long_price_volume(), _ist_epoch(10, 0))),
             "SYM", interval_seconds=1)
    monkeypatch.setattr(
        QE, "_session_force_exit",
        staticmethod(lambda t, market="NSE", contract_expiry=None: True),
    )
    trace = eng.run()
    closes = [e for e in trace if isinstance(e, PositionClosed)]
    assert closes, "session close must square off the open position"
    assert closes[0].fill.reason == "SESSION_CLOSE"


def test_session_force_exit_helpers():
    # Synthetic times (unit/replay determinism) never force or block.
    assert QuantEngine._session_force_exit("t300") is False
    assert QuantEngine._session_allow_entry("t300") is True
    # Phase 5 window (15:20 IST) forces exit and blocks new entries.
    assert QuantEngine._session_force_exit(str(_ist_epoch(15, 20))) is True
    assert QuantEngine._session_allow_entry(str(_ist_epoch(15, 20))) is False
    # Pre-market blocks; post-market blocks and forces.
    assert QuantEngine._session_allow_entry(str(_ist_epoch(9, 10))) is False
    assert QuantEngine._session_force_exit(str(_ist_epoch(15, 45))) is True
    assert QuantEngine._session_allow_entry(str(_ist_epoch(15, 45))) is False


def test_mcx_session_gate_is_exchange_aware():
    """MCX trades until 23:30, so 16:45 IST must be an OPEN session for an
    MCX engine even though NSE is in close-protection/post-market there."""
    ts = str(_ist_epoch(16, 45))
    # NSE: 16:45 is post-market — entries blocked, positions forced out.
    assert QuantEngine._session_allow_entry(ts) is False
    assert QuantEngine._session_force_exit(ts) is True
    # MCX: 16:45 is MCX_AFTERNOON (14:00-18:00) — entries allowed, no exit.
    assert QuantEngine._session_allow_entry(ts, market="MCX") is True
    assert QuantEngine._session_force_exit(ts, market="MCX") is False
    # MCX close window (23:20) blocks new entries and forces the square-off.
    ts_close = str(_ist_epoch(23, 20))
    assert QuantEngine._session_allow_entry(ts_close, market="MCX") is False
    assert QuantEngine._session_force_exit(ts_close, market="MCX") is True


def test_parse_contract_expiry():
    """MCX option symbols embed the expiry day+month; year is inferred from
    the current IST date (past dates roll to next year)."""
    from datetime import date
    from quant.runtime import QuantEngine

    assert QuantEngine._parse_contract_expiry("CRUDEOIL 17 AUG 7450 CALL").month == 8
    assert QuantEngine._parse_contract_expiry("GOLDM 28 AUG 150500 CALL").day == 28
    assert QuantEngine._parse_contract_expiry("NATURALGAS 24 AUG 245 CALL") is not None
    # No month token -> None (synthetic/test symbols, futures, unknown).
    assert QuantEngine._parse_contract_expiry("SYM") is None
    assert QuantEngine._parse_contract_expiry("SYM 100 CALL") is None
    assert QuantEngine._parse_contract_expiry("CRUDEOIL") is None
    # Parsed date is never in the past: a January contract while it is
    # December must be next year's.
    from datetime import datetime as dt, timedelta, timezone

    # Use a fixed "today" (2026-08-10 IST) via monkeypatching-free check:
    # any parsed date < today is bumped to next year.
    today = dt.now(timezone(timedelta(hours=5, minutes=30))).date()
    parsed = QuantEngine._parse_contract_expiry("CRUDEOIL 10 JAN 7450 CALL")
    if today.month > 1 or (today.month == 1 and today.day > 10):
        assert parsed.year == today.year + 1
    else:
        assert parsed.year == today.year


def test_mcx_contract_expiry_day_gates_entries():
    """On the contract's own expiry day, MCX entries close at 21:00 IST
    (option buying stops at 22:00) — before that the normal phases apply."""
    from datetime import date
    from quant.runtime import QuantEngine

    expiry = date(2026, 8, 11)
    # 20:30 on expiry day: still open for entries.
    assert QuantEngine._session_allow_entry(
        str(_ist_epoch(20, 30)), market="MCX", contract_expiry=expiry
    ) is True
    # 21:15 on expiry day: entries blocked.
    assert QuantEngine._session_allow_entry(
        str(_ist_epoch(21, 15)), market="MCX", contract_expiry=expiry
    ) is False
    # Not the expiry day: no gating even at 21:15 (normal MCX evening).
    assert QuantEngine._session_allow_entry(
        str(_ist_epoch(21, 15)), market="MCX", contract_expiry=date(2026, 8, 12)
    ) is True


def test_mcx_contract_expiry_day_forces_square_off():
    """On expiry day, an open position is force-squared from 21:30 IST so an
    ITM option can never devolve into a futures position at expiry."""
    from datetime import date
    from quant.runtime import QuantEngine

    expiry = date(2026, 8, 11)
    # 21:15 on expiry day: not yet force-exit.
    assert QuantEngine._session_force_exit(
        str(_ist_epoch(21, 15)), market="MCX", contract_expiry=expiry
    ) is False
    # 21:45 on expiry day: force square-off.
    assert QuantEngine._session_force_exit(
        str(_ist_epoch(21, 45)), market="MCX", contract_expiry=expiry
    ) is True
    # 21:45 but NOT the expiry day: normal evening, no force-exit.
    assert QuantEngine._session_force_exit(
        str(_ist_epoch(21, 45)), market="MCX", contract_expiry=date(2026, 8, 12)
    ) is False
    # NSE never gets the MCX expiry-day treatment: 21:45 is NSE post-market
    # (force-exit for its own reason) and the MCX expiry param changes nothing.
    assert QuantEngine._session_force_exit(
        str(_ist_epoch(21, 45)), market="NSE", contract_expiry=expiry
    ) is True
    assert QuantEngine._session_force_exit(
        str(_ist_epoch(21, 45)), market="NSE"
    ) is True


def test_nse_contract_expiry_day_closes_entries_at_1400():
    """On the contract's own expiry day (NIFTY Tuesday), no fresh NSE entries
    after 14:00 IST — the final hour's gamma/theta distortion is avoided."""
    from datetime import date
    from quant.runtime import QuantEngine

    expiry = date(2026, 8, 11)  # a Tuesday
    # 13:45 on expiry day: entries still open (Phase 3/4).
    assert QuantEngine._session_allow_entry(
        str(_ist_epoch(13, 45)), market="NSE", contract_expiry=expiry
    ) is True
    # 14:15 on expiry day: blocked (was POWER_HOUR before the gate).
    assert QuantEngine._session_allow_entry(
        str(_ist_epoch(14, 15)), market="NSE", contract_expiry=expiry
    ) is False
    # 14:15 but NOT the expiry day: normal POWER_HOUR, entries allowed.
    assert QuantEngine._session_allow_entry(
        str(_ist_epoch(14, 15)), market="NSE", contract_expiry=date(2026, 8, 12)
    ) is True
    # MCX expiry cut-off (21:00) does not apply to NSE.
    assert QuantEngine._session_allow_entry(
        str(_ist_epoch(21, 15)), market="NSE", contract_expiry=expiry
    ) is False  # NSE post-market anyway


def test_nse_contract_expiry_day_squares_off_by_1515():
    """NSE Phase 5 close-protection starts 15:15 — an open position on expiry
    day is force-squared by then regardless of the expiry param."""
    from datetime import date
    from quant.runtime import QuantEngine

    expiry = date(2026, 8, 11)
    # 15:10: still POWER_HOUR — no force-exit yet.
    assert QuantEngine._session_force_exit(
        str(_ist_epoch(15, 10)), market="NSE", contract_expiry=expiry
    ) is False
    # 15:20: Phase 5 close-protection — force square-off.
    assert QuantEngine._session_force_exit(
        str(_ist_epoch(15, 20)), market="NSE", contract_expiry=expiry
    ) is True
    # Same on a non-expiry day (the phase table is date-independent).
    assert QuantEngine._session_force_exit(
        str(_ist_epoch(15, 20)), market="NSE", contract_expiry=date(2026, 8, 12)
    ) is True


def test_engine_wires_nse_contract_expiry_from_symbol():
    """An NSE engine derives its contract expiry from its symbol too."""
    from datetime import date

    eng = QuantEngine(SyntheticGateway([]), "NIFTY 11 AUG 24600 CALL",
                      interval_seconds=1, market="NSE")
    assert eng._market == "NSE"
    expiry = eng._contract_expiry
    assert expiry is not None
    assert expiry.month == 8 and expiry.day == 11


def test_engine_wires_contract_expiry_from_symbol():
    """An MCX engine derives its contract expiry from its symbol and passes it
    into the session gates."""
    from datetime import date

    eng = QuantEngine(SyntheticGateway([]), "CRUDEOIL 11 AUG 7450 CALL",
                      interval_seconds=1, market="MCX")
    assert eng._market == "MCX"
    expiry = eng._contract_expiry
    assert expiry is not None
    assert expiry.month == 8 and expiry.day == 11


def test_engine_session_gate_uses_its_own_market():
    """The engine instance gates on its configured market (default NSE); an
    MCX engine stays open at 16:45 IST."""
    nse = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    assert nse._market == "NSE"
    assert nse._session_allow_entry(str(_ist_epoch(16, 45))) is False
    mcx = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1, market="MCX")
    assert mcx._market == "MCX"
    assert mcx._session_allow_entry(str(_ist_epoch(16, 45)), market=mcx._market) is True


def test_engine_position_size_is_lot_aware():
    """A lot-aware engine snaps position size to lot multiples (same
    rounding as the live adapter), so paper rupee P&L matches live fills."""
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1,
                      lot_size=65)
    trace = eng.run()
    opened = next(e for e in trace if isinstance(e, PositionOpened))
    assert opened.position.order.quantity % 65 == 0
    assert opened.position.order.quantity >= 65
    closes = [e for e in trace if isinstance(e, PositionClosed)]
    if closes:
        fill = closes[0].fill
        assert fill.pnl == pytest.approx(
            (fill.close_price - opened.position.open_price)
            * opened.position.size
        )


def test_engine_default_lot_size_preserves_determinism():
    t1 = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1).run()
    t2 = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1).run()
    assert t1 == t2
    opened = next(e for e in t1 if isinstance(e, PositionOpened))
    assert opened.position.order.quantity % 1 == 0  # lot_size=1: no snapping


def test_engine_trace_is_deterministic():
    t1 = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1).run()
    t2 = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1).run()
    assert t1 == t2


class _FixedDecisionService:
    """Returns a canned approved decision for the thin/healthy stop cases."""

    def __init__(self, signal: Signal) -> None:
        self._signal = signal

    def evaluate(self, ctx):
        return QuantDecision(True, self._signal, "Triple-A", "AGGRESSION", ())


def _run_with_signal(signal: Signal):
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1)
    eng._decision_service = _FixedDecisionService(signal)
    trace = eng.run()
    return next(e for e in trace if isinstance(e, PositionOpened))


def _thin_stop_signal() -> Signal:
    # 0.02% stop -> SessionRisk would size 500_000 units; clamp caps at 1000.
    return Signal(type="LONG", reason="test", entry=100.0, sl=99.98, tp=100.06,
                  rr=3.0, model_label="Triple-A", symbol="SYM", timestamp="t")


def _healthy_stop_signal() -> Signal:
    # 20% stop -> 1M (SessionRisk default) * 1% / 20.0 = 500 units, under the ceiling.
    return Signal(type="LONG", reason="test", entry=100.0, sl=80.0, tp=140.0,
                  rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t")


def test_runtime_clamps_thin_stop_quantity_to_max():
    opened = _run_with_signal(_thin_stop_signal())
    assert opened.position.order.quantity == MAX_POSITION_QUANTITY


def test_runtime_leaves_healthy_stop_quantity_unclamped():
    opened = _run_with_signal(_healthy_stop_signal())
    # 1M (SessionRisk default) * 0.25% (CONSERVATIVE tier) / 20.0 = 125 units, under the ceiling.
    # Fabio cushion system starts trades in CONSERVATIVE tier at 0.25%.
    assert opened.position.order.quantity == pytest.approx(1_000_000.0 * 0.0025 / 20.0)


def test_engine_rolls_prior_session_levels_on_date_change():
    """Crossing a session date persists the previous session's POC/VAH/VAL and
    feeds them back as prior levels, so the analyzer and the Triple-A TP can
    target the previous balance area (Fabio's rule). Synthetic "tN" times must
    NOT roll — only real dates do."""
    from quant.bars import Bar
    from quant.session_levels import SessionLevelStore

    store = SessionLevelStore()  # memory-only
    eng = QuantEngine(SyntheticGateway([]), "NIFTY 11 AUG 24600 CALL",
                      interval_seconds=1, session_levels=store)
    # Simulate a completed session: the last DTO of 2026-08-10 is in hand.
    eng._session_date = "2026-08-10"
    eng._last_amt_dto = {
        "poc": 24600.0, "valueAreaHigh": 24680.0, "valueAreaLow": 24520.0,
    }
    # First bar of the new session triggers the rollover.
    day2 = _ist_epoch(9, 20)  # 2026-08-11 09:20 IST
    eng._amt_analyze(Bar(time=str(day2), open=24500.0, high=24510.0,
                         low=24490.0, close=24505.0, volume=100.0))
    rec = store.load_levels("NIFTY 11 AUG 24600 CALL")
    assert rec["date"] == "2026-08-10"
    assert rec["poc"] == 24600.0
    assert rec["vah"] == 24680.0 and rec["val"] == 24520.0
    # The engine now carries them as the prior session for this contract.
    assert eng._prior["poc"] == 24600.0
    assert eng._session_date == "2026-08-11"
    # The underlying's prior-session POC became an active NPOC magnet.
    assert eng._npoc.get_active_npocs("NIFTY", 24500.0).nearest_above is not None
    assert eng._npoc.get_active_npocs("NIFTY", 24500.0).nearest_above.price == 24600.0


def test_engine_does_not_roll_on_synthetic_times():
    """Test-suite bar times ("t0"...) never match the date check, so engines
    built without a session date keep prior levels at zero."""
    from quant.bars import Bar
    from quant.session_levels import SessionLevelStore

    store = SessionLevelStore()
    eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1,
                      session_levels=store)
    eng._amt_analyze(Bar(time="t0", open=100.0, high=101.0, low=99.0,
                         close=100.0, volume=100.0))
    assert eng._session_date is None
    assert eng._prior["poc"] == 0.0
    assert store.load_levels("SYM")["poc"] == 0.0
