"""Tests for persisted active-contract selection across backend restarts.

Verifies ``load_persisted_contracts`` / ``save_persisted_contracts`` in
``quant.coordinator``: contracts saved today are reused on restart (when they
belong to the same exchange), stale (yesterday's) or exchange-mismatched
selections are invalidated so the scanner re-runs, and bad files degrade to
``None`` instead of raising.
"""

from pathlib import Path

import pytest

from quant.coordinator import (
    _ist_date_str,
    load_persisted_contracts,
    save_persisted_contracts,
)


@pytest.fixture
def contracts_file(tmp_path: Path) -> str:
    return str(tmp_path / "active_contracts.json")


def test_save_then_load_round_trip(contracts_file: str):
    symbols = ["NIFTY 11 AUG 24600 CALL", "BANKNIFTY 25 AUG 57700 CALL"]
    save_persisted_contracts(symbols, contracts_file)
    assert load_persisted_contracts(contracts_file) == symbols


def test_save_records_exchange_and_load_requires_match(contracts_file: str):
    symbols = ["CRUDEOIL 17 AUG 7350 CALL"]
    save_persisted_contracts(symbols, contracts_file, exchange="MCX")
    # Same exchange → reused.
    assert load_persisted_contracts(contracts_file, exchange="MCX") == symbols
    # Case-insensitive match.
    assert load_persisted_contracts(contracts_file, exchange="mcx") == symbols
    # Different exchange (NSE→MCX strategy switch) → invalidated.
    assert load_persisted_contracts(contracts_file, exchange="NSE") is None
    # No exchange requested → legacy behaviour (reuse today's file).
    assert load_persisted_contracts(contracts_file) == symbols


def test_legacy_file_without_exchange_not_reused_when_exchange_required(contracts_file: str):
    """Files written before exchange scoping (no ``exchange`` key) must be
    treated as stale when an exchange is required, so an NSE selection can
    never leak into an MCX session after a mid-day switch."""
    import json

    with open(contracts_file, "w") as f:
        json.dump(
            {"date": _ist_date_str(), "symbols": ["NIFTY 11 AUG 24600 CALL"]}, f
        )
    assert load_persisted_contracts(contracts_file, exchange="MCX") is None
    assert load_persisted_contracts(contracts_file, exchange="NSE") is None


def test_stale_date_is_invalidated(contracts_file: str):
    import json

    yesterday = "1999-01-01"
    with open(contracts_file, "w") as f:
        json.dump({"date": yesterday, "symbols": ["NIFTY 11 AUG 24600 CALL"]}, f)
    assert load_persisted_contracts(contracts_file) is None


def test_missing_file_returns_none(contracts_file: str):
    assert load_persisted_contracts(contracts_file) is None


def test_corrupt_file_returns_none(contracts_file: str):
    Path(contracts_file).write_text("{not valid json")
    assert load_persisted_contracts(contracts_file) is None


def test_empty_or_nonstring_symbols_invalidated(contracts_file: str):
    import json

    with open(contracts_file, "w") as f:
        json.dump({"date": _ist_date_str(), "symbols": [123, ""]}, f)
    assert load_persisted_contracts(contracts_file) is None


def test_saved_file_records_today_ist_date(contracts_file: str):
    import json

    save_persisted_contracts(["NIFTY 11 AUG 24600 CALL"], contracts_file)
    with open(contracts_file) as f:
        data = json.load(f)
    assert data["date"] == _ist_date_str()
    assert "exchange" not in data  # optional tag stays out when not provided
