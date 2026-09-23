"""SessionClock consistency — one authority (timezones + phase table).

Wave 4 / Task 17. For a weekday table of timestamps x {NSE, MCX}:

1. ``session_gates.session_allow_entry`` == ``get_session_info().allow_entry``
   (session_gates must be a thin wrapper over the phase table, not a clock).
2. ``gate_session_phase`` entry decision == ``session_allow_entry`` when the
   rest of Gate 1 is clean (session_open, warmup, spread all pass).
3. entry <= open: whenever the gate passes, both
   ``symbol_registry.is_market_open`` and ``brokers.broker.market_info.is_market_open``
   agree the exchange is open.

MCX evening owner rule (documented in the test per Task 17; same rule is
stated in ``quant/amt/session/context.py``):

  - phase-table force-exit starts at 23:00 IST (timezones.MCX_EVENING_END);
  - the market itself stays open until 23:30 IST (timezones.MCX_SESSION_CLOSE);
  - Gate 1 uses the phase table only — there is no independent 23:15 clock.

Weekday timestamps only: the phase table is time-of-day-only; the Mon-Fri
calendar belongs to ``symbol_registry.is_market_open`` (no live weekend bars).
"""

import pytest

import brokers.broker.market_info as market_info
from quant.amt.session.context import get_session_info
from quant.amt.session.symbol_registry import (
    is_market_open as registry_is_market_open,
)
from quant.contracts.timezones import (
    MCX_EVENING_END,
    MCX_SESSION_CLOSE,
    NSE_LAST_ENTRY,
    NSE_SESSION_CLOSE,
)
from quant.decision.context import DecisionContext
from quant.decision.gate_session_phase import gate_session_phase
from quant.session_gates import session_allow_entry

# Wednesday 2026-08-19 — weekday table only (see module docstring).
_DAY = "2026-08-19"

# (HH:MM:SS IST, note) — boundaries of both exchanges plus the MCX evening
# close-protection window where the old Gate-1 clock (23:15) diverged from
# the phase table (23:00).
CASES: list[tuple[str, str]] = [
    ("08:00:00", "pre-market both exchanges"),
    ("09:05:00", "NSE pre-open; MCX pre-open (phase PRE_OPEN)"),
    ("09:14:59", "MCX one second before open"),
    ("09:15:00", "MCX open; NSE opening-noise phase"),
    ("09:29:59", "NSE one second before primary window"),
    ("09:30:00", "NSE primary window opens"),
    ("11:30:00", "NSE midday start"),
    ("12:45:00", "NSE midday (entry allowed, trend off)"),
    ("14:00:00", "NSE power hour; MCX afternoon"),
    ("15:14:59", "NSE last entry second"),
    ("15:15:00", "NSE close protection starts (NSE_LAST_ENTRY)"),
    ("15:16:00", "NSE phase 5; MCX still open"),
    ("15:30:00", "NSE market close (NSE_SESSION_CLOSE)"),
    ("16:57:00", "NSE post-market; MCX afternoon"),
    ("18:00:00", "MCX evening window opens"),
    ("22:55:00", "MCX evening — last entry minute"),
    ("23:00:00", "MCX force-exit starts (MCX_EVENING_END owner rule)"),
    ("23:10:00", "MCX force-exit on, market still open until 23:30"),
    ("23:15:00", "old Gate-1 MCX end — phase table already closed"),
    ("23:29:59", "MCX final open second"),
    ("23:30:30", "MCX past close (MCX_SESSION_CLOSE)"),
    ("23:59:00", "MCX post-market"),
]


def _ts(hhmmss: str) -> str:
    return f"{_DAY}T{hhmmss}+05:30"


def _gate(ts: str, market: str):
    """Clean Gate 1 context: only the exchange clock can reject."""
    ctx = DecisionContext(
        state=None,
        bar=None,
        symbol="NIFTY" if market == "NSE" else "CRUDEOIL",
        market=market,
        session_open=True,
        warmup_complete=True,
        setup_evidence=None,
        time_str=ts,
        bid=99.95,
        ask=100.05,
        tick_size=0.05,
    )
    return gate_session_phase(ctx)


@pytest.mark.parametrize("market", ["NSE", "MCX"])
@pytest.mark.parametrize(
    "hhmmss,note", CASES, ids=[case[0] for case in CASES]
)
def test_gate_matches_phase_table_and_registry(hhmmss: str, note: str, market: str):
    ts = _ts(hhmmss)

    # 1. session_gates is a wrapper over the phase table — no second clock.
    info = get_session_info(ts, market=market)
    allow = session_allow_entry(ts, market=market)
    assert allow is info.allow_entry, (
        f"{ts} {market}: session_gates.allow != phase table ({note})"
    )

    # 2. Gate 1 (clean ctx) decides exactly what the phase table decides.
    result = _gate(ts, market)
    assert result.passed is allow, (
        f"{ts} {market}: gate={result.passed} allow={allow} "
        f"reason={result.reason!r} ({note})"
    )

    # 3. entry <= open: a passing gate never trades a closed exchange, and
    #    market_info delegates the same registry hours (incl. MCX).
    if allow:
        assert registry_is_market_open(ts, exchange=market), (
            f"entry admitted while {market} exchange closed ({note})"
        )
        assert market_info.is_market_open(ts=ts, exchange=market) is True, (
            f"market_info disagrees with registry on open {market} ({note})"
        )


def test_market_info_delegates_to_registry():
    """brokers market_info must answer from the registry for BOTH exchanges."""
    for hhmmss, _note in CASES:
        ts = _ts(hhmmss)
        for exchange in ("NSE", "MCX"):
            assert market_info.is_market_open(ts=ts, exchange=exchange) is (
                registry_is_market_open(ts, exchange=exchange)
            ), f"market_info != registry at {ts} {exchange}"


def test_mcx_evening_owner_rule():
    """Force-exit 23:00, market open until 23:30, Gate 1 = phase table only.

    The three clocks people confuse in the MCX evening:
      - phase table (Gate 1 / session_allow_entry): entry stops 23:00,
        force_exit=True from 23:00 (MCX_EVENING_END);
      - market open (symbol_registry / market_info): until 23:30
        (MCX_SESSION_CLOSE) — exiting/monitoring still possible;
      - the deleted Gate-1 hard clock ended at 23:15 and is gone.
    """
    assert MCX_EVENING_END.hour == 23 and MCX_EVENING_END.minute == 0
    assert MCX_SESSION_CLOSE.hour == 23 and MCX_SESSION_CLOSE.minute == 30
    assert MCX_EVENING_END < MCX_SESSION_CLOSE

    # Before 23:00: entry allowed, market open, gate passes.
    before = _ts("22:55:00")
    info_before = get_session_info(before, market="MCX")
    assert info_before.allow_entry is True
    assert info_before.force_exit is False
    assert session_allow_entry(before, market="MCX") is True
    assert _gate(before, "MCX").passed is True
    assert registry_is_market_open(before, exchange="MCX") is True

    # From 23:00: force-exit, no entries, gate blocks — but market still open.
    for hhmmss in ("23:00:00", "23:10:00", "23:15:00", "23:20:00"):
        ts = _ts(hhmmss)
        info = get_session_info(ts, market="MCX")
        assert info.force_exit is True, hhmmss
        assert info.allow_entry is False, hhmmss
        assert session_allow_entry(ts, market="MCX") is False, hhmmss
        assert _gate(ts, "MCX").passed is False, hhmmss
        assert registry_is_market_open(ts, exchange="MCX") is True, (
            f"{hhmmss}: market must stay open until 23:30 for square-off"
        )

    # Exchange itself is shut past the inclusive 23:30 close.
    assert registry_is_market_open(_ts("23:30:01"), exchange="MCX") is False
    assert registry_is_market_open(_ts("23:31:00"), exchange="MCX") is False


def test_nse_entry_window_is_subset_of_market_open():
    """Symmetric NSE rule: entry stops 15:15 (close protection), exchange
    closes 15:30 — Gate 1 must be stricter than market-open, never looser."""
    assert NSE_LAST_ENTRY.hour == 15 and NSE_LAST_ENTRY.minute == 15
    assert NSE_SESSION_CLOSE.hour == 15 and NSE_SESSION_CLOSE.minute == 30
    assert NSE_LAST_ENTRY < NSE_SESSION_CLOSE

    last_entry = _ts("15:14:59")
    assert session_allow_entry(last_entry, market="NSE") is True
    assert _gate(last_entry, "NSE").passed is True

    close_protection = _ts("15:15:00")
    info = get_session_info(close_protection, market="NSE")
    assert info.allow_entry is False
    assert info.force_exit is True
    assert session_allow_entry(close_protection, market="NSE") is False
    assert _gate(close_protection, "NSE").passed is False
    # Exchange still open — positions can be monitored/squared until 15:30.
    assert registry_is_market_open(close_protection, exchange="NSE") is True
    assert registry_is_market_open(_ts("15:30:01"), exchange="NSE") is False
