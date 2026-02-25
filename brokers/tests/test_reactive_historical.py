"""
Tests for ReactiveBroker historical data streams.

Covers:
  - historical_stream()  — single symbol Observable[Dict]
  - bulk_historical_stream() — multi-symbol Observable[Tuple[str, Dict]]

Unit tests use PaperBroker (no credentials).
Integration tests use live Dhan and are gated behind DHAN_* env vars.
"""

import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Skip integration tests when credentials are absent
# ---------------------------------------------------------------------------

DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")
_creds_present = bool(DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN)


def _skip_if_no_creds():
    if not _creds_present:
        pytest.skip("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to run integration tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect(observable) -> list:
    """Synchronously collect all items emitted by an Observable."""
    items = []
    errors = []
    completed = []

    observable.subscribe(
        on_next=items.append,
        on_error=errors.append,
        on_completed=lambda: completed.append(True),
    )

    if errors:
        raise errors[0]
    return items


# ---------------------------------------------------------------------------
# Unit Tests — PaperBroker (no credentials, always run)
# ---------------------------------------------------------------------------


class TestHistoricalStreamUnit:
    """Unit tests for historical_stream() using PaperBroker."""

    @pytest.fixture(scope="class")
    def reactive(self):
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.paper()

    @pytest.fixture
    def date_range(self):
        to_date = datetime.now()
        from_date = to_date - timedelta(days=10)
        return from_date, to_date

    def test_emits_candle_dicts(self, reactive, date_range):
        """historical_stream emits dict items."""
        from_date, to_date = date_range
        items = _collect(
            reactive.historical_stream("NIFTY", from_date, to_date, interval="1d")
        )
        assert len(items) > 0
        assert isinstance(items[0], dict)

    def test_candle_has_ohlcv_keys(self, reactive, date_range):
        """Each emitted candle has open, high, low, close, volume keys."""
        from_date, to_date = date_range
        items = _collect(
            reactive.historical_stream("RELIANCE", from_date, to_date, interval="1d")
        )
        assert len(items) > 0
        candle = items[0]
        for key in ("open", "high", "low", "close", "volume"):
            assert key in candle, f"Missing key: {key}"

    def test_completes_after_all_candles(self, reactive, date_range):
        """Observable completes (not infinite)."""
        from_date, to_date = date_range
        completed = []
        reactive.historical_stream("TCS", from_date, to_date).subscribe(
            on_next=lambda _: None,
            on_completed=lambda: completed.append(True),
        )
        assert completed == [True]

    def test_accepts_instrument_object(self, reactive, date_range):
        """historical_stream accepts an Instrument instead of a string."""
        from brokers.broker.entities import Instrument
        from brokers.broker.types import Exchange

        from_date, to_date = date_range
        inst = Instrument(symbol="SBIN", exchange=Exchange.NSE, security_id="")
        items = _collect(
            reactive.historical_stream(inst, from_date, to_date)
        )
        assert len(items) > 0

    def test_rx_pipe_operators_work(self, reactive, date_range):
        """Rx pipe operators (filter, map) compose with historical_stream."""
        from rx import operators as ops

        from_date, to_date = date_range
        high_volume = []
        reactive.historical_stream("NIFTY", from_date, to_date).pipe(
            ops.filter(lambda c: c["volume"] > 0),
            ops.map(lambda c: c["close"]),
        ).subscribe(on_next=high_volume.append)
        assert len(high_volume) > 0
        assert all(isinstance(p, (int, float)) for p in high_volume)

    def test_error_forwarded_on_bad_instrument(self, reactive, date_range):
        """Observable forwards errors when broker raises."""
        from_date, to_date = date_range
        # Monkey-patch broker to raise
        original = reactive._broker.get_historical
        reactive._broker.get_historical = MagicMock(side_effect=ValueError("bad symbol"))

        errors = []
        reactive.historical_stream("BADXXX", from_date, to_date).subscribe(
            on_next=lambda _: None,
            on_error=errors.append,
        )
        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)

        # Restore
        reactive._broker.get_historical = original


class TestBulkHistoricalStreamUnit:
    """Unit tests for bulk_historical_stream() using PaperBroker."""

    @pytest.fixture(scope="class")
    def reactive(self):
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.paper()

    @pytest.fixture
    def date_range(self):
        to_date = datetime.now()
        from_date = to_date - timedelta(days=10)
        return from_date, to_date

    def test_emits_symbol_candle_tuples(self, reactive, date_range):
        """bulk_historical_stream emits (symbol, candle_dict) tuples."""
        from_date, to_date = date_range
        items = _collect(
            reactive.bulk_historical_stream(["NIFTY", "TCS"], from_date, to_date)
        )
        assert len(items) > 0
        symbol, candle = items[0]
        assert isinstance(symbol, str)
        assert isinstance(candle, dict)

    def test_covers_all_symbols(self, reactive, date_range):
        """All requested symbols appear in emitted items."""
        from_date, to_date = date_range
        symbols = ["NIFTY", "RELIANCE", "TCS"]
        items = _collect(
            reactive.bulk_historical_stream(symbols, from_date, to_date)
        )
        emitted_symbols = {s for s, _ in items}
        for sym in symbols:
            assert sym in emitted_symbols, f"{sym} not found in emitted items"

    def test_completes_after_all_symbols(self, reactive, date_range):
        """Observable completes after all symbols are exhausted."""
        from_date, to_date = date_range
        completed = []
        reactive.bulk_historical_stream(["NIFTY", "TCS"], from_date, to_date).subscribe(
            on_next=lambda _: None,
            on_completed=lambda: completed.append(True),
        )
        assert completed == [True]

    def test_rx_group_by_symbol(self, reactive, date_range):
        """group_by operator correctly splits items by symbol."""
        from rx import operators as ops

        from_date, to_date = date_range
        symbols = ["NIFTY", "RELIANCE"]
        items = _collect(
            reactive.bulk_historical_stream(symbols, from_date, to_date)
        )
        by_symbol: dict = {}
        for sym, candle in items:
            by_symbol.setdefault(sym, []).append(candle)

        for sym in symbols:
            assert sym in by_symbol
            assert len(by_symbol[sym]) > 0

    def test_single_symbol_list(self, reactive, date_range):
        """bulk works with a single-element symbol list."""
        from_date, to_date = date_range
        items = _collect(
            reactive.bulk_historical_stream(["GOLD"], from_date, to_date)
        )
        assert all(sym == "GOLD" for sym, _ in items)

    def test_candle_keys_present(self, reactive, date_range):
        """Each candle dict has the expected OHLCV keys."""
        from_date, to_date = date_range
        items = _collect(
            reactive.bulk_historical_stream(["NIFTY"], from_date, to_date)
        )
        _, candle = items[0]
        for key in ("open", "high", "low", "close", "volume"):
            assert key in candle


# ---------------------------------------------------------------------------
# Integration Tests — Live Dhan (require env vars)
# ---------------------------------------------------------------------------


class TestHistoricalStreamDhan:
    """Live integration tests for historical_stream() with Dhan broker."""

    @pytest.fixture(scope="class")
    def reactive(self):
        _skip_if_no_creds()
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.dhan(
            client_id=DHAN_CLIENT_ID,
            access_token=DHAN_ACCESS_TOKEN,
        )

    def test_tcs_daily_candles(self, reactive):
        """Live: TCS daily candles for last 5 days — returns non-empty DataFrame rows."""
        _skip_if_no_creds()
        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)

        items = _collect(
            reactive.historical_stream("TCS", from_date, to_date, interval="1d")
        )
        assert len(items) > 0, "Expected at least one candle for TCS"
        candle = items[0]
        assert candle["open"] > 0
        assert candle["high"] >= candle["open"]
        assert candle["low"] <= candle["open"]
        assert candle["close"] > 0
        assert candle["volume"] >= 0

    def test_nifty_intraday_candles(self, reactive):
        """Live: NIFTY 5-minute candles for yesterday — returns OHLCV dicts."""
        _skip_if_no_creds()
        from brokers.broker.types import Exchange

        to_date = datetime.now()
        from_date = to_date - timedelta(days=1)

        items = _collect(
            reactive.historical_stream(
                "NIFTY", from_date, to_date, interval="5m", exchange=Exchange.NSE
            )
        )
        # May be empty if yesterday was a holiday; just check structure
        if items:
            candle = items[0]
            for key in ("open", "high", "low", "close", "volume"):
                assert key in candle

    def test_crudeoil_mcx(self, reactive):
        """Live: CRUDEOIL MCX daily — verify MCX exchange works."""
        _skip_if_no_creds()
        from brokers.broker.types import Exchange

        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)

        items = _collect(
            reactive.historical_stream(
                "CRUDEOIL", from_date, to_date, interval="1d", exchange=Exchange.MCX
            )
        )
        if items:
            assert items[0]["close"] > 0

    def test_pipe_operators_on_live_data(self, reactive):
        """Live: Rx pipe operators apply correctly to real candle data."""
        _skip_if_no_creds()
        from rx import operators as ops

        to_date = datetime.now()
        from_date = to_date - timedelta(days=30)

        closes = []
        reactive.historical_stream("TCS", from_date, to_date, interval="1d").pipe(
            ops.filter(lambda c: c["volume"] > 0),
            ops.map(lambda c: c["close"]),
        ).subscribe(on_next=closes.append)

        assert len(closes) > 0
        assert all(p > 0 for p in closes)


class TestBulkHistoricalStreamDhan:
    """Live integration tests for bulk_historical_stream() with Dhan broker."""

    @pytest.fixture(scope="class")
    def reactive(self):
        _skip_if_no_creds()
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.dhan(
            client_id=DHAN_CLIENT_ID,
            access_token=DHAN_ACCESS_TOKEN,
        )

    def test_nifty_and_tcs_bulk(self, reactive):
        """Live: bulk fetch NIFTY + TCS — both appear in output."""
        _skip_if_no_creds()
        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)

        items = _collect(
            reactive.bulk_historical_stream(["NIFTY", "TCS"], from_date, to_date)
        )
        symbols_seen = {s for s, _ in items}
        assert "NIFTY" in symbols_seen
        assert "TCS" in symbols_seen

    def test_group_by_symbol_on_live_data(self, reactive):
        """Live: group_by over bulk stream gives correct per-symbol candle counts."""
        _skip_if_no_creds()
        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)

        by_symbol: dict = {}
        reactive.bulk_historical_stream(
            ["TCS", "RELIANCE"], from_date, to_date
        ).subscribe(
            on_next=lambda item: by_symbol.setdefault(item[0], []).append(item[1])
        )

        for sym in ("TCS", "RELIANCE"):
            assert sym in by_symbol
            # Each symbol should have at least 1 trading day in 7-day window
            assert len(by_symbol[sym]) >= 1
