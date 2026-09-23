"""Gate 1 exchange-clock blackout (phase-table authority).

The production gate (``quant/decision/gate_session_phase.py``) delegates the
exchange clock to ``session_allow_entry`` — the phase table in
``quant/amt/session/context.py`` built from ``quant/contracts/timezones.py``:

  NSE entries 09:30:00–15:15:00 IST (close protection starts at 15:15:00)
  MCX entries 09:15:00–23:00:00 IST (close protection starts at 23:00:00;
  the exchange trades until 23:30 — there is no independent 23:15 gate clock)

These tests pin that behaviour, including the ISO-8601 timestamp format the
context builder actually feeds via ``ctx.time_str`` — regression guard: the
original private parser could not read ISO strings (``int("2026-08-19T09")``
raised) and silently skipped the blackout on every live bar.
"""

from quant.decision.context import DecisionContext
from quant.decision.gate_session_phase import gate_session_phase
from quant.session_gates import session_allow_entry


def _ctx(time_str: str, market: str = "NSE") -> DecisionContext:
    return DecisionContext(
        state=None,
        bar=None,
        session_open=True,
        warmup_complete=True,
        market=market,
        time_str=time_str,
        bid=99.95,
        ask=100.05,
        tick_size=0.05,
    )


# --- NSE window: 09:30:00–15:15:00 IST -------------------------------


def test_nse_opening_blackout_blocks():
    assert not gate_session_phase(_ctx("2026-08-19T09:15:00+05:30")).passed


def test_nse_boundary_start_passes():
    assert gate_session_phase(_ctx("2026-08-19T09:30:00+05:30")).passed


def test_nse_boundary_end_is_close_protection():
    """Phase table starts close protection AT 15:15:00 (NSE_LAST_ENTRY) —
    the gate must match it. The old private clock allowed this exact second
    (inclusive end); production already blocked it via session_open."""
    r = gate_session_phase(_ctx("2026-08-19T15:15:00+05:30"))
    assert not r.passed
    assert "clock blackout" in r.reason


def test_nse_last_entry_second_passes():
    assert gate_session_phase(_ctx("2026-08-19T15:14:59+05:30")).passed


def test_nse_after_close_blocks():
    r = gate_session_phase(_ctx("2026-08-19T15:16:00+05:30"))
    assert not r.passed
    assert "NSE clock blackout" in r.reason


def test_nse_pre_open_blocks():
    r = gate_session_phase(_ctx("2026-08-19T09:29:59+05:30"))
    assert not r.passed
    assert "blackout" in r.reason


# --- MCX window: 09:15:00–23:00:00 IST (market trades to 23:30) ------


def test_mcx_evening_session_passes():
    # 22:00 IST is outside NSE hours but inside MCX — the market field
    # must select the window, not the default.
    assert gate_session_phase(_ctx("2026-08-19T22:00:00+05:30", market="MCX")).passed


def test_same_timestamp_blocks_under_nse_window():
    assert not gate_session_phase(_ctx("2026-08-19T22:00:00+05:30", market="NSE")).passed


def test_mcx_force_exit_from_2300_blocks():
    """Owner rule: phase-table force-exit starts 23:00 IST — Gate 1 blocks
    even though the exchange stays open until 23:30 (the old private clock
    allowed 23:00–23:15 and is gone)."""
    for hhmm in ("23:00:00", "23:10:00", "23:15:00"):
        r = gate_session_phase(_ctx(f"2026-08-19T{hhmm}+05:30", market="MCX"))
        assert not r.passed, hhmm
        assert "MCX clock blackout" in r.reason, hhmm


def test_mcx_last_entry_minute_passes():
    assert gate_session_phase(_ctx("2026-08-19T22:59:59+05:30", market="MCX")).passed


def test_mcx_after_close_blocks():
    r = gate_session_phase(_ctx("2026-08-19T23:30:00+05:30", market="MCX"))
    assert not r.passed
    assert "MCX clock blackout" in r.reason


def test_mcx_pre_open_blocks():
    assert not gate_session_phase(_ctx("2026-08-19T09:00:00+05:30", market="MCX")).passed


# --- parser robustness (shared authority, not a private parser) -------


def test_bare_clock_string_follows_session_allow_entry():
    # "HH:MM:SS" without a date has no calendar day — the shared authority
    # anchors it on the wall clock. Gate 1 must agree with session_gates
    # instead of keeping its own time-of-day parser.
    r = gate_session_phase(_ctx("09:20:00"))
    assert r.passed is session_allow_entry("09:20:00", market="NSE")


def test_unparseable_time_skips_clock_check():
    # Garbage must not hard-block trading: the shared authority treats it as
    # synthetic (fail-open) and the other guards (session_open, warmup,
    # spread) still apply.
    assert gate_session_phase(_ctx("not-a-time")).passed


def test_missing_time_skips_clock_check():
    assert gate_session_phase(_ctx("")).passed
