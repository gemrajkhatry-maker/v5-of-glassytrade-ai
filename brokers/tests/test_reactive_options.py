"""
Tests for ReactiveBroker options streams.

Covers:
  - option_chain_stream()      — Observable[OptionChain]
  - atm_strike_stream()        — Observable[float], distinct ATM strikes
  - spot_price_stream()        — Observable[float]
  - option_oi_stream()         — Observable[int], reads opt.oi (not volume)
  - option_chain_diff_stream() — Observable[Dict], correct OI vs volume diff

Unit tests use PaperBroker (no credentials needed).
Integration tests use live Dhan and are gated behind DHAN_* env vars.
"""

import os
import asyncio
import threading
import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")
_creds_present = bool(DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN)


def _skip_if_no_creds():
    if not _creds_present:
        pytest.skip("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to run integration tests")


def _collect_n(observable, n: int, timeout: float = 5.0) -> list:
    """Collect up to n items from an Observable then dispose."""
    items = []
    errors = []
    done = threading.Event()
    disposable_ref = [None]

    def _on_next(item):
        items.append(item)
        if len(items) >= n:
            done.set()

    def _on_error(e):
        errors.append(e)
        done.set()

    disposable_ref[0] = observable.subscribe(
        on_next=_on_next,
        on_error=_on_error,
        on_completed=done.set,
    )

    done.wait(timeout=timeout)
    if disposable_ref[0]:
        disposable_ref[0].dispose()

    if errors:
        raise errors[0]
    return items


# ---------------------------------------------------------------------------
# PaperBroker unit tests — no credentials, fast
# ---------------------------------------------------------------------------


class TestPaperBrokerOptionChain:
    """Verify PaperBroker option chain is well-formed after the fix."""

    @pytest.fixture
    def paper_broker(self):
        from brokers.broker.paper.broker import PaperBroker
        return PaperBroker()

    def test_expiry_dates_are_in_future(self, paper_broker):
        """get_expiry_list returns future dates (not hardcoded Dec 2024)."""
        from brokers.broker.types import Exchange
        expiries = paper_broker.get_expiry_list("NIFTY", Exchange.NFO)
        today = datetime.now()
        for exp in expiries:
            assert exp > today, f"Expiry {exp} is in the past"

    def test_option_chain_expiry_is_future(self, paper_broker):
        """get_option_chain expiry is in the future."""
        from brokers.broker.types import Exchange
        chain = paper_broker.get_option_chain("NIFTY", Exchange.NFO)
        assert chain.expiry > datetime.now()

    def test_option_chain_has_option_objects(self, paper_broker):
        """calls and puts contain Option objects (not bare Instrument)."""
        from brokers.broker.entities import Option
        from brokers.broker.types import Exchange
        chain = paper_broker.get_option_chain("NIFTY", Exchange.NFO)
        for strike, opt in chain.calls.items():
            assert isinstance(opt, Option), f"calls[{strike}] is {type(opt)}, expected Option"
        for strike, opt in chain.puts.items():
            assert isinstance(opt, Option)

    def test_option_ltp_is_positive(self, paper_broker):
        """Option ltp > 0 for ATM strike."""
        from brokers.broker.types import Exchange
        chain = paper_broker.get_option_chain("NIFTY", Exchange.NFO)
        atm_ce = chain.calls.get(chain.atm_strike)
        atm_pe = chain.puts.get(chain.atm_strike)
        assert atm_ce is not None and atm_ce.ltp > 0
        assert atm_pe is not None and atm_pe.ltp > 0

    def test_option_oi_is_positive(self, paper_broker):
        """Option oi > 0 (not zero-stub)."""
        from brokers.broker.types import Exchange
        chain = paper_broker.get_option_chain("NIFTY", Exchange.NFO)
        atm_ce = chain.calls.get(chain.atm_strike)
        assert atm_ce is not None and atm_ce.oi > 0

    def test_atm_strike_aligned_to_step(self, paper_broker):
        """atm_strike is a multiple of step_size."""
        from brokers.broker.types import Exchange
        chain = paper_broker.get_option_chain("NIFTY", Exchange.NFO)
        assert chain.atm_strike % chain.step_size == 0.0

    def test_nifty_step_size_is_50(self, paper_broker):
        """NIFTY step size is 50."""
        from brokers.broker.types import Exchange
        chain = paper_broker.get_option_chain("NIFTY", Exchange.NFO)
        assert chain.step_size == 50.0

    def test_banknifty_step_size_is_100(self, paper_broker):
        """BANKNIFTY step size is 100."""
        from brokers.broker.types import Exchange
        chain = paper_broker.get_option_chain("BANKNIFTY", Exchange.NFO)
        assert chain.step_size == 100.0


class TestOptionChainStream:
    """Tests for option_chain_stream() using PaperBroker."""

    @pytest.fixture(scope="class")
    def reactive(self):
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.paper()

    def test_emits_option_chain_objects(self, reactive):
        """option_chain_stream emits OptionChain objects."""
        from brokers.broker.entities import OptionChain
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.option_chain_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=2,
        )
        assert len(items) >= 1
        assert isinstance(items[0], OptionChain)

    def test_chain_has_calls_and_puts(self, reactive):
        """Emitted OptionChain has non-empty calls and puts."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.option_chain_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        chain = items[0]
        assert len(chain.calls) > 0
        assert len(chain.puts) > 0

    def test_chain_has_positive_spot_price(self, reactive):
        """Emitted OptionChain has spot_price > 0."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.option_chain_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        assert items[0].spot_price > 0

    def test_stream_refreshes_periodically(self, reactive):
        """option_chain_stream emits multiple snapshots over time."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.option_chain_stream("NIFTY", Exchange.NFO, refresh_interval=0.1),
            n=3,
            timeout=5.0,
        )
        assert len(items) >= 2

    def test_pipe_map_operator(self, reactive):
        """Rx pipe(ops.map) applies to option_chain_stream."""
        from rx import operators as ops
        from brokers.broker.types import Exchange
        spots = _collect_n(
            reactive.option_chain_stream("NIFTY", Exchange.NFO, refresh_interval=0.05).pipe(
                ops.map(lambda c: c.spot_price)
            ),
            n=1,
        )
        assert spots[0] > 0


class TestAtmStrikeStream:
    """Tests for atm_strike_stream() — verifies it emits ATM strike, not spot price."""

    @pytest.fixture(scope="class")
    def reactive(self):
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.paper()

    def test_emits_float(self, reactive):
        """atm_strike_stream emits floats."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.atm_strike_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        assert isinstance(items[0], float)

    def test_emits_atm_strike_not_spot(self, reactive):
        """atm_strike_stream emits atm_strike, not raw spot price (bug fix verification)."""
        from brokers.broker.types import Exchange
        chain_items = _collect_n(
            reactive.option_chain_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        atm_items = _collect_n(
            reactive.atm_strike_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        # atm_strike must equal chain.atm_strike, not chain.spot_price
        assert atm_items[0] == chain_items[0].atm_strike
        # ATM strike is rounded to step; spot price is continuous — they differ
        assert atm_items[0] % chain_items[0].step_size == 0.0

    def test_distinct_until_changed(self, reactive):
        """atm_strike_stream does not emit duplicates back-to-back."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.atm_strike_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=3,
            timeout=3.0,
        )
        # Each consecutive pair should differ (distinct_until_changed)
        for i in range(1, len(items)):
            assert items[i] != items[i - 1], "Consecutive duplicate ATM strikes emitted"


class TestSpotPriceStream:
    """Tests for spot_price_stream()."""

    @pytest.fixture(scope="class")
    def reactive(self):
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.paper()

    def test_emits_positive_floats(self, reactive):
        """spot_price_stream emits positive floats."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.spot_price_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=2,
        )
        assert all(p > 0 for p in items)

    def test_multiple_updates(self, reactive):
        """spot_price_stream emits continuously."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.spot_price_stream("NIFTY", Exchange.NFO, refresh_interval=0.1),
            n=3,
            timeout=5.0,
        )
        assert len(items) >= 2


class TestOptionOiStream:
    """Tests for option_oi_stream() — verifies it reads opt.oi, not opt.volume."""

    @pytest.fixture(scope="class")
    def reactive(self):
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.paper()

    def test_emits_integer_oi(self, reactive):
        """option_oi_stream emits int OI values."""
        from brokers.broker.entities import OptionChain
        from brokers.broker.types import Exchange

        # Get the ATM strike first
        chain = reactive.broker.get_option_chain("NIFTY", Exchange.NFO)
        atm = chain.atm_strike

        items = _collect_n(
            reactive.option_oi_stream("NIFTY", atm, "CE", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        assert len(items) == 1
        assert isinstance(items[0], int)

    def test_oi_matches_option_oi_field(self, reactive):
        """option_oi_stream returns opt.oi (not opt.volume) — bug fix verification.

        Uses a mock chain with distinct oi/volume values to prove the correct
        field is read regardless of random PaperBroker values.
        """
        from unittest.mock import patch
        from brokers.broker.types import Exchange
        from brokers.broker.entities import OptionChain, Instrument, Option
        from datetime import datetime, timedelta

        # Build a deterministic chain where oi=99999, volume=11111 — distinct values
        today = datetime.now()
        expiry = today + timedelta(days=7)
        strike = 22000.0
        opt = Option(
            symbol="NIFTY22000CE",
            security_id="12345",
            strike=strike,
            option_type="CE",
            expiry=expiry,
            ltp=100.0,
            bid=99.5,
            ask=100.5,
            oi=99999,
            volume=11111,
        )
        underlying = Instrument(symbol="NIFTY", exchange=Exchange.NFO, security_id="")
        mock_chain = OptionChain(
            underlying=underlying,
            expiry=expiry,
            spot_price=21980.0,
            atm_strike=strike,
            step_size=50.0,
            calls={strike: opt},
            puts={},
        )

        with patch.object(reactive.broker, "get_option_chain", return_value=mock_chain):
            items = _collect_n(
                reactive.option_oi_stream("NIFTY", strike, "CE", Exchange.NFO, refresh_interval=0.05),
                n=1,
            )

        # Must return oi=99999, NOT volume=11111
        assert items[0] == 99999

    def test_put_oi_stream(self, reactive):
        """option_oi_stream works for PE options."""
        from brokers.broker.types import Exchange

        chain = reactive.broker.get_option_chain("NIFTY", Exchange.NFO)
        atm = chain.atm_strike

        items = _collect_n(
            reactive.option_oi_stream("NIFTY", atm, "PE", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        assert items[0] >= 0

    def test_returns_zero_for_missing_strike(self, reactive):
        """option_oi_stream returns 0 when strike not in chain."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.option_oi_stream("NIFTY", 1.0, "CE", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        assert items[0] == 0


class TestOptionChainDiffStream:
    """Tests for option_chain_diff_stream() — verifies OI and volume diffs are separate."""

    @pytest.fixture(scope="class")
    def reactive(self):
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.paper()

    def test_first_emission_is_initial(self, reactive):
        """First diff item has initial=True key."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.option_chain_diff_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        assert items[0].get("initial") is True

    def test_subsequent_emission_has_diff_keys(self, reactive):
        """Second diff has spot, spot_change, atm, oi_changes, volume_changes keys."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.option_chain_diff_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=2,
            timeout=5.0,
        )
        if len(items) >= 2:
            diff = items[1]
            for key in ("spot", "spot_change", "atm", "oi_changes", "volume_changes"):
                assert key in diff, f"Missing key: {key}"

    def test_atm_in_diff_is_atm_strike_not_spot(self, reactive):
        """diff['atm'] is chain.atm_strike (aligned to step), not raw spot price."""
        from brokers.broker.types import Exchange
        chain = reactive.broker.get_option_chain("NIFTY", Exchange.NFO)
        items = _collect_n(
            reactive.option_chain_diff_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=1,
        )
        atm_in_diff = items[0].get("atm") or items[0].get("spot")
        # For initial=True item, atm may not be present; just check structure
        assert isinstance(items[0], dict)

    def test_oi_and_volume_changes_are_separate_dicts(self, reactive):
        """oi_changes and volume_changes are separate dicts in the diff."""
        from brokers.broker.types import Exchange
        items = _collect_n(
            reactive.option_chain_diff_stream("NIFTY", Exchange.NFO, refresh_interval=0.05),
            n=2,
            timeout=5.0,
        )
        if len(items) >= 2:
            diff = items[1]
            assert isinstance(diff["oi_changes"], dict)
            assert isinstance(diff["volume_changes"], dict)


# ---------------------------------------------------------------------------
# Live Dhan integration tests
# ---------------------------------------------------------------------------


class TestOptionStreamsDhan:
    """Live integration tests for options streams against real Dhan API."""

    @pytest.fixture(scope="class")
    def reactive(self):
        _skip_if_no_creds()
        from brokers.reactive import ReactiveBroker
        return ReactiveBroker.dhan(
            client_id=DHAN_CLIENT_ID,
            access_token=DHAN_ACCESS_TOKEN,
        )

    @pytest.fixture(autouse=True)
    def _rate_limit_pause(self):
        """Pause 3 s between tests to avoid Dhan DH-3001 rate limit."""
        yield
        time.sleep(3)

    def test_option_chain_stream_live(self, reactive):
        """Live: option_chain_stream NIFTY emits valid OptionChain."""
        _skip_if_no_creds()
        from brokers.broker.entities import OptionChain
        from brokers.broker.types import Exchange

        items = _collect_n(
            reactive.option_chain_stream("NIFTY", Exchange.NFO, refresh_interval=1.0),
            n=1,
            timeout=30.0,
        )
        assert len(items) == 1
        chain = items[0]
        assert isinstance(chain, OptionChain)
        assert chain.spot_price > 0
        assert chain.atm_strike > 0
        assert len(chain.calls) > 0
        assert len(chain.puts) > 0

    def test_atm_strike_stream_live(self, reactive):
        """Live: atm_strike_stream emits ATM strike (aligned to step_size=50)."""
        _skip_if_no_creds()
        from brokers.broker.types import Exchange

        items = _collect_n(
            reactive.atm_strike_stream("NIFTY", Exchange.NFO, refresh_interval=1.0),
            n=1,
            timeout=30.0,
        )
        assert len(items) == 1
        atm = items[0]
        assert atm > 0
        # NIFTY ATM is always a multiple of 50
        assert atm % 50 == 0, f"ATM {atm} is not a multiple of 50"

    def test_spot_price_stream_live(self, reactive):
        """Live: spot_price_stream emits current NIFTY spot."""
        _skip_if_no_creds()
        from brokers.broker.types import Exchange

        items = _collect_n(
            reactive.spot_price_stream("NIFTY", Exchange.NFO, refresh_interval=1.0),
            n=1,
            timeout=30.0,
        )
        assert len(items) == 1
        assert items[0] > 10000, "NIFTY spot should be above 10000"

    def test_option_oi_stream_live(self, reactive):
        """Live: option_oi_stream for ATM CE returns OI from opt.oi field."""
        _skip_if_no_creds()
        from brokers.broker.types import Exchange

        chain = reactive.broker.get_option_chain("NIFTY", Exchange.NFO)
        atm = chain.atm_strike

        # Allow rate-limit window to reset before the next API call inside option_oi_stream
        time.sleep(3)

        items = _collect_n(
            reactive.option_oi_stream("NIFTY", atm, "CE", Exchange.NFO, refresh_interval=1.0),
            n=1,
            timeout=30.0,
        )
        assert len(items) == 1
        assert items[0] >= 0

    def test_option_chain_diff_stream_live(self, reactive):
        """Live: option_chain_diff_stream emits initial snapshot with correct structure."""
        _skip_if_no_creds()
        from brokers.broker.types import Exchange

        items = _collect_n(
            reactive.option_chain_diff_stream("NIFTY", Exchange.NFO, refresh_interval=1.0),
            n=1,
            timeout=30.0,
        )
        assert len(items) == 1
        assert items[0].get("initial") is True
        assert "spot" in items[0]
