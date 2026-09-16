"""Gate 1 exchange-clock blackout (production semantics).

The production gate (``quant/decision/gates/gate_session_phase.py``) enforces
NSE 09:30–15:15 and MCX 09:15–23:15 IST wall-clock windows. These tests pin
that behaviour, including the ISO-8601 timestamp format the context builder
actually feeds via ``ctx.time_str`` — regression guard: the original parser
could not read ISO strings (``int("2026-08-19T09")`` raised) and silently
skipped the blackout on every live bar.
"""

from quant.decision.context import DecisionContext
from quant.decision.gates import gate_session_phase


def _ctx(time_str: str, market: str = "NSE") -> DecisionContext:
    return DecisionContext(
        state=None,
        bar=None,
        session_open=True,
        warmup_complete=True,
        market=market,
        time_str=time_str,
    )


# --- NSE window: 09:30:00–15:15:00 IST -------------------------------


def test_nse_opening_blackout_blocks():
    assert not gate_session_phase(_ctx("2026-08-19T09:15:00+05:30")).passed


def test_nse_boundary_start_passes():
    assert gate_session_phase(_ctx("2026-08-19T09:30:00+05:30")).passed


def test_nse_boundary_end_passes():
    assert gate_session_phase(_ctx("2026-08-19T15:15:00+05:30")).passed


def test_nse_after_close_blocks():
    r = gate_session_phase(_ctx("2026-08-19T15:16:00+05:30"))
    assert not r.passed
    assert "NSE clock blackout" in r.reason


def test_nse_pre_open_blocks():
    r = gate_session_phase(_ctx("2026-08-19T09:29:59+05:30"))
    assert not r.passed
    assert "blackout" in r.reason


# --- MCX window: 09:15:00–23:15:00 IST -------------------------------


def test_mcx_evening_session_passes():
    # 22:00 IST is outside NSE hours but inside MCX — the market field
    # must select the window, not the default.
    assert gate_session_phase(_ctx("2026-08-19T22:00:00+05:30", market="MCX")).passed


def test_same_timestamp_blocks_under_nse_window():
    assert not gate_session_phase(_ctx("2026-08-19T22:00:00+05:30", market="NSE")).passed


def test_mcx_after_close_blocks():
    r = gate_session_phase(_ctx("2026-08-19T23:30:00+05:30", market="MCX"))
    assert not r.passed
    assert "MCX clock blackout" in r.reason


def test_mcx_pre_open_blocks():
    assert not gate_session_phase(_ctx("2026-08-19T09:00:00+05:30", market="MCX")).passed


# --- parser robustness ------------------------------------------------


def test_bare_clock_string_parsed():
    # "HH:MM:SS" without a date is still recognized.
    assert not gate_session_phase(_ctx("09:20:00")).passed


def test_unparseable_time_skips_clock_check():
    # Garbage must not hard-block trading: the clock check is skipped and
    # the other guards (session_open, warmup, spread) still apply.
    assert gate_session_phase(_ctx("not-a-time")).passed


def test_missing_time_skips_clock_check():
    assert gate_session_phase(_ctx("")).passed
