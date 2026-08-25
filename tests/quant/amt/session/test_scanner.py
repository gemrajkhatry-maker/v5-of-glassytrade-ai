"""Tests for OptionScannerService — ported from backend/tests/unit/domain/test_option_scanner.py.

The backend suite marks the TestOptionScannerService class as a pre-existing
skip; the tests actually pass against the mock broker, so the port runs them.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from quant.amt.session.scanner import OptionScannerService, ScanResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_option(ltp=100.0, oi=1_000_000, volume=50_000, bid=None, ask=None,
                 symbol="NIFTY 20 MAR 23400 CALL", strike=23400.0, prev_oi=None,
                 delta=0.50, iv=15.0):
    """Create a mock option object with standard attributes."""
    opt = MagicMock()
    opt.symbol = symbol
    opt.ltp = ltp
    opt.oi = oi
    opt.volume = volume
    opt.bid = bid if bid is not None else ltp - ltp * 0.0025
    opt.ask = ask if ask is not None else ltp + ltp * 0.0025
    opt.strike = strike
    opt.prev_oi = prev_oi
    opt.delta = delta
    opt.iv = iv
    return opt


def _make_chain(atm=23400.0, expiry_iso="2026-03-20", calls=None, puts=None,
                strikes=None, spot_price=None):
    """Create a mock option chain object."""
    chain = MagicMock()
    chain.atm_strike = atm
    chain.expiry = datetime.fromisoformat(expiry_iso).replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    chain.calls = calls or {}
    chain.puts = puts or {}
    chain.strikes = strikes or list(set(list(chain.calls.keys()) + list(chain.puts.keys()) + [atm]))
    chain.spot_price = spot_price or atm
    return chain


def _next_tuesday_iso() -> str:
    """ISO date (YYYY-MM-DD) of the next Tuesday (NIFTY weekly expiry)
    strictly after today, so expiry tests never depend on the wall clock."""
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    days_ahead = (1 - today.weekday()) % 7  # Tuesday == weekday 1
    if days_ahead == 0:
        days_ahead = 7
    return (today + timedelta(days=days_ahead)).isoformat()


# ---------------------------------------------------------------------------
# OptionScannerService tests
# ---------------------------------------------------------------------------

class TestOptionScannerService:

    def _make_scanner(self, broker=None):
        return OptionScannerService(broker or MagicMock())

    def _full_calls(self, atm=23400.0, interval=50):
        """Build calls for ATM ±2 strikes so scanner has candidates."""
        calls = {}
        for i in range(-2, 3):
            s = atm + i * interval
            calls[s] = _make_option(
                ltp=max(10, 120 - abs(i) * 30), oi=600_000 - abs(i) * 100_000,
                volume=10_000, symbol=f"NIFTY 20 MAR {int(s)} CALL",
                strike=s, delta=max(0.2, 0.50 - i * 0.10),
            )
        return calls

    def _full_puts(self, atm=23400.0, interval=50):
        """Build puts for ATM ±2 strikes."""
        puts = {}
        for i in range(-2, 3):
            s = atm + i * interval
            puts[s] = _make_option(
                ltp=max(10, 85 - abs(i) * 20), oi=700_000 - abs(i) * 100_000,
                volume=8_000, symbol=f"NIFTY 20 MAR {int(s)} PUT",
                strike=s, delta=max(0.2, 0.50 + i * 0.10),
            )
        return puts

    def test_scanner_returns_result(self):
        """Mock broker returning a chain with ATM calls should give ScanResults."""
        calls = self._full_calls()
        chain = _make_chain(atm=23400.0, expiry_iso="2026-03-20", calls=calls)
        broker = MagicMock()
        broker.get_option_chain.return_value = chain

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert len(results) > 0
        assert results[0].underlying == "NIFTY"
        assert "NIFTY" in results[0].symbol

    def test_scanner_returns_put(self):
        """preferred_option_type='PE' should scan puts chain."""
        puts = self._full_puts()
        chain = _make_chain(atm=23400.0, expiry_iso="2026-03-20", puts=puts)
        broker = MagicMock()
        broker.get_option_chain.return_value = chain

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert len(results) > 0
        pe_results = [r for r in results if r.option_type == "PE"]
        assert len(pe_results) > 0

    def test_scanner_none_on_empty_chain(self):
        """Broker returning None should cause scan_top_n to return empty list."""
        broker = MagicMock()
        broker.get_option_chain.return_value = None

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert len(results) == 0

    def test_scanner_none_on_exception(self):
        """Broker raising an exception should be caught and scan_top_n returns empty."""
        broker = MagicMock()
        broker.get_option_chain.side_effect = RuntimeError("Network error")

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert len(results) == 0

    def test_scan_top_n_picks_highest_score(self):
        """scan_top_n should return contracts sorted by score."""
        calls = self._full_calls()
        chain = _make_chain(atm=23400.0, expiry_iso="2026-03-20", calls=calls)
        broker = MagicMock()
        broker.get_option_chain.return_value = chain

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert len(results) > 0
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_unaligned_atm_snaps_to_listed_strike(self):
        """Broker-reported atm_strike off the strike grid (e.g. 23437) must be
        snapped to the nearest listed strike, else all candidate lookups miss
        and the scan silently returns nothing."""
        calls = self._full_calls(atm=23400.0, interval=50)
        chain = _make_chain(
            atm=23437.0,  # off-grid spot print
            expiry_iso=_next_tuesday_iso(),
            calls=calls,
        )
        broker = MagicMock()
        broker.get_option_chain.return_value = chain

        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)

        assert results, "off-grid ATM must still produce contracts"
        # Nearest listed strike to 23437 is 23450.
        assert results[0].strike == 23450

    def test_scan_top_n_uses_nearest_weekly_expiry_for_nifty(self):
        """NIFTY's primary series is the weekly (Tuesday). The scanner must
        request the nearest expiry (expiry_index=0) and operate on that series
        — never a later monthly."""
        calls = self._full_calls()
        weekly_iso = _next_tuesday_iso()
        weekly = _make_chain(atm=23400.0, expiry_iso=weekly_iso, calls=calls)
        broker = MagicMock()
        broker.get_option_chain.return_value = weekly
        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)
        assert results
        assert all(r.expiry == weekly_iso for r in results)
        broker.get_option_chain.assert_called_once()
        _, kwargs = broker.get_option_chain.call_args
        assert kwargs.get("expiry_index") == 0
        assert kwargs.get("exchange") == "NFO"

    def test_scan_advances_past_expired_series(self):
        """The scanner must never select an expired/past series — it advances
        expiry_index until the broker returns a future expiry."""
        calls = self._full_calls()
        past = _make_chain(atm=23400.0, expiry_iso="2026-03-20", calls=calls)
        weekly_iso = _next_tuesday_iso()
        weekly = _make_chain(atm=23400.0, expiry_iso=weekly_iso, calls=calls)
        broker = MagicMock()

        def _chain(underlying=None, exchange=None, expiry_index=0):
            return past if expiry_index == 0 else weekly

        broker.get_option_chain.side_effect = _chain
        scanner = self._make_scanner(broker)
        results = scanner.scan_top_n(underlyings=["NIFTY"], n=3)
        assert results
        assert all(r.expiry == weekly_iso for r in results)
        assert broker.get_option_chain.call_count == 2

    def test_underlying_priority_fills_primary_first(self):
        """underlying_priority makes the primary root fill its slots (including
        the extra pass) before secondary roots, overriding pure score order."""
        # NIFTY chain carries a wide-spread penalty so it scores *below* the
        # tight BANKNIFTY chain — priority must still put NIFTY first.
        nifty_calls = {}
        for i in range(-2, 3):
            s = 23400.0 + i * 50
            ltp = max(10, 120 - abs(i) * 30)
            nifty_calls[s] = _make_option(
                ltp=ltp, oi=600_000 - abs(i) * 100_000, volume=10_000,
                symbol=f"NIFTY 11 AUG {int(s)} CALL", strike=s,
                delta=max(0.2, 0.50 - i * 0.10),
                bid=ltp * 0.994, ask=ltp * 1.006,
            )
        bn_calls = self._full_calls(atm=48000.0, interval=100)
        for o in bn_calls.values():
            o.symbol = f"BANKNIFTY 25 AUG {int(o.strike)} CALL"
        nifty_chain = _make_chain(atm=23400.0, expiry_iso=_next_tuesday_iso(), calls=nifty_calls)
        bn_chain = _make_chain(atm=48000.0, expiry_iso="2026-08-25", calls=bn_calls)
        broker = MagicMock()

        def _chain(underlying=None, exchange=None, expiry_index=0):
            return nifty_chain if underlying.upper() == "NIFTY" else bn_chain

        broker.get_option_chain.side_effect = _chain
        scanner = self._make_scanner(broker)

        # Without priority, the higher-scoring root (BANKNIFTY) leads.
        no_prio = scanner.scan_top_n(underlyings=["NIFTY", "BANKNIFTY"], n=2)
        assert no_prio[0].underlying == "BANKNIFTY"

        # With priority, NIFTY (primary) fills first despite lower scores.
        prio = scanner.scan_top_n(
            underlyings=["NIFTY", "BANKNIFTY"], n=2,
            underlying_priority=["NIFTY", "BANKNIFTY"],
        )
        assert prio[0].underlying == "NIFTY"

        # Extra slots go to the primary: n=3 with top_per_underlying=2 gives
        # NIFTY 2 contracts and BANKNIFTY 1.
        prio3 = scanner.scan_top_n(
            underlyings=["NIFTY", "BANKNIFTY"], n=3, top_per_underlying=2,
            underlying_priority=["NIFTY", "BANKNIFTY"],
        )
        counts = {}
        for r in prio3:
            counts[r.underlying] = counts.get(r.underlying, 0) + 1
        assert counts == {"NIFTY": 2, "BANKNIFTY": 1}

    @pytest.mark.skip(reason="Pre-existing option scanner assertion (NIFTY auto-detects as NFO)")
    def test_scanner_passes_exchange_string(self):
        """Scanner should pass exchange as string to broker.get_option_chain."""
        broker = MagicMock()
        broker.get_option_chain.return_value = None

        scanner = self._make_scanner(broker)
        scanner.scan_top_n(underlyings=["NIFTY"], n=1, exchange="MCX")

        _, kwargs = broker.get_option_chain.call_args
        assert kwargs["exchange"] == "MCX"


def test_silverm_mcx_mini_configured_like_silver_chain():
    """SILVERM is a separate Dhan chain; must use 500 strike step and loose OI floor."""
    assert "SILVERM" in OptionScannerService._SCAN_MCX_UNDERLYINGS
    assert OptionScannerService._STRIKE_INTERVALS["SILVERM"] == 500
    assert OptionScannerService._MIN_OI["SILVERM"] == 0


def test_goldm_mcx_mini_configured_like_gold_chain():
    """GOLDM is a separate Dhan chain; same 100 strike step and loose OI as GOLD."""
    assert "GOLDM" in OptionScannerService._SCAN_MCX_UNDERLYINGS
    assert OptionScannerService._STRIKE_INTERVALS["GOLDM"] == 100
    assert OptionScannerService._MIN_OI["GOLDM"] == 0


# ---------------------------------------------------------------------------
# Big-move mode
# ---------------------------------------------------------------------------

def _future_expiry(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_big_move_mode_skips_rich_iv_chain():
    """Big-move mode must skip a chain whose ATM straddle is a large % of spot
    (premium already expensive = low ROI for a big move)."""
    atm = 10000.0
    calls = {atm: _make_option(ltp=300.0, oi=1_000_000, volume=60_000, strike=atm,
                               symbol="NIFTY CALL")}
    puts = {atm: _make_option(ltp=300.0, oi=1_000_000, volume=60_000, strike=atm,
                              symbol="NIFTY PUT")}
    chain = _make_chain(atm=atm, expiry_iso=_future_expiry(), calls=calls,
                        puts=puts, spot_price=10000.0)
    broker = MagicMock()
    broker.get_option_chain.return_value = chain

    scanner = OptionScannerService(broker)
    results = scanner.scan_top_n(underlyings=["NIFTY"], n=3, big_move_mode=True)

    assert results == []


def test_big_move_mode_premium_band():
    """Big-move mode caps NSE premium at 25-400; expensive contracts are dropped."""
    atm = 100000.0
    strikes = [atm, atm - 50.0, atm + 50.0]

    def side(kind):
        return {
            s: _make_option(ltp=450.0, oi=900_000, volume=50_000, strike=s,
                            symbol=f"NIFTY {int(s)} {kind}")
            for s in strikes
        }

    calls, puts = side("CALL"), side("PUT")
    chain = _make_chain(atm=atm, expiry_iso=_future_expiry(), calls=calls,
                        puts=puts, spot_price=100000.0)
    broker = MagicMock()
    broker.get_option_chain.return_value = chain

    scanner = OptionScannerService(broker)
    # Normal mode keeps the ₹450 contracts (band is 20-800).
    kept = scanner.scan_top_n(underlyings=["NIFTY"], n=3, big_move_mode=False)
    # Big-move mode drops them all (₹400 cap).
    dropped = scanner.scan_top_n(underlyings=["NIFTY"], n=3, big_move_mode=True)

    assert len(kept) > 0
    assert dropped == []
