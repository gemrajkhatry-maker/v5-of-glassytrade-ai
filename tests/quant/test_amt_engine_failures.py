"""B-4a: every AMT analyze failure is reported (log + counter + AMT_FAILING).

Pre-fix defect: ``_amt_fail_logged`` logged the first analyze exception once,
then every later failure returned the stale DTO with ZERO signal — no log,
no counter, no flag.
"""

from __future__ import annotations

import logging
import time

import pytest

import quant.amt_engine as amt_eng
from quant.amt_engine import AMTEngine
from quant.bars import Bar
from quant.session_levels import SessionLevelStore


class _ExplodingAnalyzer:
    """Analyzer double that always fails the way a broken detector would."""

    def analyze(self, *args, **kwargs):
        raise RuntimeError("analyzer exploded")


@pytest.fixture
def engine():
    return AMTEngine(
        symbol="NIFTY 1 SEP 25000 CALL",
        market="NSE",
        session_levels=SessionLevelStore(),
    )


@pytest.fixture
def failure_counter():
    """Isolate the process-global counter across tests."""
    before = amt_eng.AMT_FAILURES_TOTAL
    yield
    amt_eng.AMT_FAILURES_TOTAL = before


def _bar(minute: int) -> Bar:
    return Bar(
        time=f"2026-09-21T09:{minute:02d}:00+05:30",
        open=25000.0, high=25010.0, low=24990.0, close=25005.0,
        volume=1000.0, buy_volume=600.0, sell_volume=400.0, delta=200.0,
    )


def _error_records(caplog) -> list:
    return [
        r for r in caplog.records
        if r.levelno == logging.ERROR and "AMT analyze failed" in r.getMessage()
    ]


def test_two_failures_emit_two_error_logs_and_counter(
    engine, failure_counter, monkeypatch, caplog,
):
    monkeypatch.setattr(engine, "_amt_analyzer", _ExplodingAnalyzer())
    before = amt_eng.AMT_FAILURES_TOTAL

    with caplog.at_level(logging.ERROR, logger="quant.amt_engine"):
        engine.analyze(_bar(15))
        engine.analyze(_bar(20))

    assert len(_error_records(caplog)) == 2, [
        r.getMessage() for r in caplog.records
    ]
    assert amt_eng.AMT_FAILURES_TOTAL == before + 2


def test_second_failure_still_signals_amt_failing_flag(
    engine, failure_counter, monkeypatch, caplog,
):
    monkeypatch.setattr(engine, "_amt_analyzer", _ExplodingAnalyzer())
    assert amt_eng.AMT_FAILING not in engine.status_flags

    with caplog.at_level(logging.ERROR, logger="quant.amt_engine"):
        engine.analyze(_bar(15))
        engine.analyze(_bar(20))

    # Second failure must signal too — not once-then-silent.
    assert amt_eng.AMT_FAILING in engine.status_flags


def test_amt_failing_flag_expires_after_window(engine):
    engine._amt_last_failure_at = time.monotonic() - (
        amt_eng.AMT_FAILING_WINDOW_SEC + 1.0
    )
    assert amt_eng.AMT_FAILING not in engine.status_flags

    engine._amt_last_failure_at = time.monotonic() - 1.0
    assert amt_eng.AMT_FAILING in engine.status_flags


def test_failure_keeps_returning_last_good_dto(engine, monkeypatch):
    monkeypatch.setattr(engine, "_amt_analyzer", _ExplodingAnalyzer())
    engine._last_amt_dto = {"poc": 25000.0}
    out = engine.analyze(_bar(15))
    assert out == {"poc": 25000.0}
