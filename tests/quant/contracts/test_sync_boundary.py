"""Tests for quant.contracts.sync_boundary — sync/async adapter result guards."""

from __future__ import annotations

import asyncio

import pytest

from quant.contracts.sync_boundary import (
    ensure_sync_adapter_result,
    ensure_async_adapter_result,
)


def _sync_fn(*args, **kwargs):
    return ("ok", args, kwargs)


async def _async_fn(*args, **kwargs):
    return ("ok", args, kwargs)


def _returns_coroutine():
    return _async_fn()


class TestEnsureSyncAdapterResult:
    def test_sync_callable_passthrough(self):
        assert ensure_sync_adapter_result("x", _sync_fn, 1, a=2) == ("ok", (1,), {"a": 2})

    def test_coroutine_function_raises(self):
        with pytest.raises(RuntimeError):
            ensure_sync_adapter_result("x", _async_fn, 1)

    def test_awaitable_return_raises(self):
        with pytest.raises(RuntimeError):
            ensure_sync_adapter_result("x", _returns_coroutine)

    def test_non_callable_passthrough(self):
        class FakeStorage:
            def __init__(self):
                self.called = False

            def kv_get(self, key):
                self.called = True
                return {"v": 1}

        storage = FakeStorage()
        assert ensure_sync_adapter_result("storage.kv_get", storage.kv_get, "k") == {"v": 1}
        assert storage.called


class TestEnsureAsyncAdapterResult:
    def test_async_callable_passthrough(self):
        assert asyncio.run(ensure_async_adapter_result("x", _async_fn, 1, a=2)) == (
            "ok",
            (1,),
            {"a": 2},
        )

    def test_sync_function_raises(self):
        with pytest.raises(RuntimeError):
            ensure_async_adapter_result("x", _sync_fn, 1)
