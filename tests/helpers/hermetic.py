"""Safety helpers for the opt-in hermetic test profile.

The profile is enabled with ``GLASSYTRADE_HERMETIC=1``.  It isolates test
storage, removes broker credentials, prevents live subprocesses, and blocks
non-loopback network connections without changing normal development imports.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

import pytest

HERMETIC_ENV = "GLASSYTRADE_HERMETIC"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_SENSITIVE_ENV_PREFIXES = ("DHAN_", "LIVE_")
_SENSITIVE_ENV_KEYS = frozenset(
    {
        "CLEAR_POSITIONS_ON_RESTART",
        "RECONCILE_DELETE_STALE",
        "GLASSYTRADE_LIVE",
        "TRADING_MODE",
    }
)
_PATH_ENV_KEYS = (
    "GLASSYTRADE_DATABASE_PATH",
    "GLASSYTRADE_STORAGE_PATH",
    "GLASSYTRADE_JOURNAL_PATH",
    "DATABASE_PATH",
    "EVENT_STORE_PATH",
)


class HermeticViolation(RuntimeError):
    """Raised when a hermetic test attempts a prohibited side effect."""


def _is_enabled(environment: Mapping[str, str]) -> bool:
    return str(environment.get(HERMETIC_ENV, "")).strip().lower() in _TRUTHY


def should_load_dotenv(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether importing the application may read a user ``.env``."""

    env = os.environ if environment is None else environment
    return not _is_enabled(env)


def apply_hermetic_environment(
    environment: MutableMapping[str, str], tmp_path: Path
) -> None:
    """Make an environment mapping safe for isolated tests."""

    for key in tuple(environment):
        if key in _SENSITIVE_ENV_KEYS or key.startswith(_SENSITIVE_ENV_PREFIXES):
            environment.pop(key, None)

    isolated_root = Path(tmp_path)
    environment[HERMETIC_ENV] = "1"
    environment["GLASSYTRADE_ENV"] = "paper"
    for key in _PATH_ENV_KEYS:
        environment[key] = str(isolated_root / Path(key).name)


def is_external_address(address: str) -> bool:
    """Return whether an address must be blocked by the hermetic profile."""

    normalized = address.strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        return not ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return True


def _command_from_call(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> Sequence[Any]:
    if args:
        candidate = args[0]
    else:
        candidate = kwargs.get("args", ())
    if isinstance(candidate, (str, bytes)):
        return (candidate,)
    return candidate


def assert_paper_subprocess(
    command: Sequence[Any], environment: Mapping[str, str] | None = None
) -> None:
    """Reject a subprocess that requests live mode."""

    env = os.environ if environment is None else environment
    mode = str(env.get("GLASSYTRADE_ENV", "paper")).strip().lower()
    live_flag = str(env.get("GLASSYTRADE_LIVE", "")).strip().lower() in _TRUTHY
    command_text = " ".join(str(part) for part in command).lower()
    if mode == "live" or live_flag or "--live" in command_text:
        raise HermeticViolation("live-mode subprocess is forbidden in hermetic tests")


def _address_host(address: Any) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


@pytest.fixture(autouse=True)
def hermetic_test_profile(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Apply hermetic protections only when the profile is explicitly enabled."""

    if not _is_enabled(os.environ):
        yield
        return

    apply_hermetic_environment(os.environ, tmp_path)
    original_popen = subprocess.Popen
    original_run = subprocess.run
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    threads_before = {
        thread.ident
        for thread in __import__("threading").enumerate()
        if thread.is_alive() and not thread.daemon
    }

    def guarded_popen(*args: Any, **kwargs: Any) -> Any:
        assert_paper_subprocess(
            _command_from_call(args, kwargs), kwargs.get("env")
        )
        return original_popen(*args, **kwargs)

    def guarded_run(*args: Any, **kwargs: Any) -> Any:
        assert_paper_subprocess(
            _command_from_call(args, kwargs), kwargs.get("env")
        )
        return original_run(*args, **kwargs)

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if is_external_address(_address_host(address)):
            raise HermeticViolation("external network access is forbidden")
        return original_connect(self, address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        if is_external_address(_address_host(address)):
            raise HermeticViolation("external network access is forbidden")
        return original_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)

    yield

    leaked_threads = {
        thread.ident
        for thread in __import__("threading").enumerate()
        if thread.is_alive() and not thread.daemon and thread.ident not in threads_before
    }
    if leaked_threads:
        raise RuntimeError("hermetic test leaked non-daemon threads")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: tests excluded from hermetic profile")
    config.addinivalue_line("markers", "live: tests requiring an isolated live fixture")
    config.addinivalue_line("markers", "e2e: end-to-end tests excluded from hermetic profile")
