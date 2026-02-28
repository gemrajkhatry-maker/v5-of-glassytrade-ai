"""Tests for SymbolCircuitBreaker in gameloop."""

import time
from unittest.mock import patch

from app.application.engine import SymbolCircuitBreaker


class TestSymbolCircuitBreaker:
    def test_starts_closed(self):
        cb = SymbolCircuitBreaker(max_failures=3, cooldown_secs=10)
        assert not cb.is_open("GOLD")

    def test_opens_after_max_failures(self):
        cb = SymbolCircuitBreaker(max_failures=3, cooldown_secs=60)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        assert not cb.is_open("GOLD")
        cb.record_failure("GOLD")  # 3rd failure → open
        assert cb.is_open("GOLD")

    def test_success_resets_failures(self):
        cb = SymbolCircuitBreaker(max_failures=3, cooldown_secs=60)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        cb.record_success("GOLD")
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        assert not cb.is_open("GOLD")  # only 2 consecutive failures

    def test_isolates_symbols(self):
        cb = SymbolCircuitBreaker(max_failures=2, cooldown_secs=60)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        assert cb.is_open("GOLD")
        assert not cb.is_open("SILVER")

    def test_closes_after_cooldown(self):
        cb = SymbolCircuitBreaker(max_failures=2, cooldown_secs=1)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        assert cb.is_open("GOLD")
        time.sleep(1.1)
        assert not cb.is_open("GOLD")  # cooldown expired → half-open

    def test_half_open_reopens_on_one_more_failure(self):
        cb = SymbolCircuitBreaker(max_failures=2, cooldown_secs=0.1)
        cb.record_failure("GOLD")
        cb.record_failure("GOLD")
        time.sleep(0.2)  # cooldown expires
        assert not cb.is_open("GOLD")  # half-open
        cb.record_failure("GOLD")  # one more failure re-opens
        assert cb.is_open("GOLD")
