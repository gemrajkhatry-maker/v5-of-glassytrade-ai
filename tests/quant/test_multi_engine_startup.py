"""Startup selection tests for ``QuantCoordinator``."""

from types import SimpleNamespace

import quant.multi_engine as multi_engine
from quant.multi_engine import QuantCoordinator, save_persisted_contracts


FUTURE = "NIFTY AUG FUT"
OPTION = "NIFTY 26 AUG 24000 CALL"
COMPACT_FUTURE = "NIFTY25AUGFUT"
HYPHEN_FUTURE = "NIFTY-WED-FUT"


class _MarketData:
    def get_nearest_futures(self, underlying, *, exchange):
        assert exchange in ("NSE", "NFO", "BFO", "MCX")
        return {"NIFTY": FUTURE}[underlying]


class _Scanner:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def scan_top_n(self, **kwargs):
        self.calls.append(kwargs)
        return self.results


def _coordinator(tmp_path, monkeypatch, scanner, *, n=2):
    monkeypatch.setattr(multi_engine, "OptionScannerService", lambda _: scanner)
    return QuantCoordinator(
        _MarketData(),
        config={
            "underlyings": ["NIFTY"],
            "n": n,
            "contracts_file": str(tmp_path / "contracts.json"),
        },
    )


def test_scan_rejects_option_only_persisted_selection_when_futures_enabled(
    tmp_path, monkeypatch
):
    scanner = _Scanner([SimpleNamespace(symbol=OPTION, ltp=100)])
    coordinator = _coordinator(tmp_path, monkeypatch, scanner)
    save_persisted_contracts([OPTION], coordinator._contracts_file, exchange="NSE")

    assert coordinator._scan() == [FUTURE, OPTION]
    assert len(scanner.calls) == 1


def test_scan_reuses_complete_persisted_futures_and_options(tmp_path, monkeypatch):
    scanner = _Scanner([])
    coordinator = _coordinator(tmp_path, monkeypatch, scanner)
    persisted = [FUTURE, OPTION]
    save_persisted_contracts(persisted, coordinator._contracts_file, exchange="NSE")

    assert coordinator._scan() == persisted
    assert scanner.calls == []


def test_scan_rejects_duplicate_persisted_contracts(tmp_path, monkeypatch):
    scanner = _Scanner([SimpleNamespace(symbol=OPTION, ltp=100)])
    coordinator = _coordinator(tmp_path, monkeypatch, scanner)
    save_persisted_contracts(
        [FUTURE, FUTURE], coordinator._contracts_file, exchange="NSE"
    )

    assert coordinator._scan() == [FUTURE, OPTION]
    assert len(scanner.calls) == 1


def test_scan_rejects_persisted_selection_over_configured_n(tmp_path, monkeypatch):
    scanner = _Scanner([SimpleNamespace(symbol=OPTION, ltp=100)])
    coordinator = _coordinator(tmp_path, monkeypatch, scanner)
    save_persisted_contracts(
        [FUTURE, OPTION, "NIFTY 26 AUG 24100 PUT"],
        coordinator._contracts_file,
        exchange="NSE",
    )

    assert coordinator._scan() == [FUTURE, OPTION]
    assert len(scanner.calls) == 1


def test_scan_normalizes_persisted_contracts_to_futures_first(tmp_path, monkeypatch):
    scanner = _Scanner([])
    coordinator = _coordinator(tmp_path, monkeypatch, scanner)
    save_persisted_contracts(
        [OPTION, FUTURE], coordinator._contracts_file, exchange="NSE"
    )

    assert coordinator._scan() == [FUTURE, OPTION]
    assert scanner.calls == []


def test_scan_reuses_compact_and_hyphenated_futures_contracts(
    tmp_path, monkeypatch
):
    scanner = _Scanner([])
    coordinator = _coordinator(tmp_path, monkeypatch, scanner)

    for future in (COMPACT_FUTURE, HYPHEN_FUTURE):
        coordinator.market_data.get_nearest_futures = (
            lambda underlying, *, exchange, future=future: future
        )
        save_persisted_contracts(
            [future, OPTION], coordinator._contracts_file, exchange="NSE"
        )

        assert coordinator._scan() == [future, OPTION]

    assert scanner.calls == []


def test_scan_rejects_persisted_option_without_a_matching_future(tmp_path, monkeypatch):
    scanner = _Scanner([SimpleNamespace(symbol=OPTION, ltp=100)])
    coordinator = _coordinator(tmp_path, monkeypatch, scanner)
    save_persisted_contracts(
        [FUTURE, "BANKNIFTY 26 AUG 52000 CALL"],
        coordinator._contracts_file,
        exchange="NSE",
    )

    assert coordinator._scan() == [FUTURE, OPTION]
    assert len(scanner.calls) == 1


def test_scan_rejects_exchange_mismatched_persisted_selection(tmp_path, monkeypatch):
    scanner = _Scanner([SimpleNamespace(symbol=OPTION, ltp=100)])
    coordinator = _coordinator(tmp_path, monkeypatch, scanner)
    save_persisted_contracts(
        ["CRUDEOIL AUG FUT", "CRUDEOIL 26 AUG 6000 CALL"],
        coordinator._contracts_file,
        exchange="MCX",
    )

    assert coordinator._scan() == [FUTURE, OPTION]
    assert len(scanner.calls) == 1


def test_scan_leaves_no_option_slots_after_required_futures(tmp_path, monkeypatch):
    scanner = _Scanner(
        [
            SimpleNamespace(symbol=OPTION, ltp=100),
            SimpleNamespace(symbol="NIFTY 26 AUG 24100 PUT", ltp=80),
        ]
    )
    coordinator = _coordinator(tmp_path, monkeypatch, scanner, n=1)

    assert coordinator._scan() == [FUTURE]
    assert scanner.calls == []


def test_scan_rejects_configuration_smaller_than_required_futures(
    tmp_path, monkeypatch
):
    scanner = _Scanner([])
    coordinator = QuantCoordinator(
        _MarketData(),
        config={
            "underlyings": ["NIFTY", "BANKNIFTY"],
            "n": 1,
            "contracts_file": str(tmp_path / "contracts.json"),
        },
    )
    coordinator.market_data.get_nearest_futures = lambda underlying, *, exchange: {
        "NIFTY": FUTURE,
        "BANKNIFTY": "BANKNIFTY AUG FUT",
    }[underlying]
    monkeypatch.setattr(multi_engine, "OptionScannerService", lambda _: scanner)

    try:
        coordinator._scan()
    except ValueError as exc:
        assert "required futures" in str(exc)
    else:
        raise AssertionError("expected an impossible futures topology to be rejected")
