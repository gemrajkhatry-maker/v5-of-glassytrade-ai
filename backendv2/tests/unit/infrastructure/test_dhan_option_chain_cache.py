"""Unit tests for DhanAdapter option-chain caching."""
from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.adapters.dhan_adapter import DhanAdapter
from app.infrastructure.adapters.option_chain_cache import OptionChainCache


@dataclass
class _MockResponse:
    status_code: int
    payload: dict

    def json(self):
        return self.payload


def _option_chain_payload():
    return {
        "data": {
            "expiryDate": "2099-01-01T00:00:00",
            "spot": 23400.0,
            "atm": 23400,
            "calls": {
                23400: {"symbol": "NIFTY 20 MAR 23400 CE", "ltp": 120.0, "oi": 120000, "volume": 10000, "bid": 119.9, "ask": 120.1},
            },
            "puts": {
                23400: {"symbol": "NIFTY 20 MAR 23400 PE", "ltp": 118.0, "oi": 130000, "volume": 9000, "bid": 117.9, "ask": 118.1},
            },
        }
    }


def test_option_chain_ttl_cache_reuses_response(monkeypatch):
    adapter = DhanAdapter(client_id="c", access_token="t")
    call_count = {"count": 0}

    def _fake_run_sync(awaitable):
        call_count["count"] += 1
        return _MockResponse(200, _option_chain_payload())

    monkeypatch.setattr(adapter, "_run_sync", _fake_run_sync)
    adapter._option_chain_cache = OptionChainCache(ttl_sec=30)

    first = adapter.get_option_chain("NIFTY", exchange="NFO")
    second = adapter.get_option_chain("NIFTY", exchange="NFO")

    assert first is second
    assert call_count["count"] == 1


def test_option_chain_ttl_cache_disabled_hits_network_each_call(monkeypatch):
    adapter = DhanAdapter(client_id="c", access_token="t")
    call_count = {"count": 0}

    def _fake_run_sync(awaitable):
        call_count["count"] += 1
        return _MockResponse(200, _option_chain_payload())

    monkeypatch.setattr(adapter, "_run_sync", _fake_run_sync)
    adapter._option_chain_cache = OptionChainCache(ttl_sec=0)
    adapter.get_option_chain("NIFTY", exchange="NFO")
    adapter.get_option_chain("NIFTY", exchange="NFO")

    assert call_count["count"] == 2
