from pathlib import Path
import os
import socket
import subprocess

import pytest

from tests.helpers.hermetic import (
    HermeticViolation,
    apply_hermetic_environment,
    assert_paper_subprocess,
    is_external_address,
    should_load_dotenv,
)


def test_apply_hermetic_environment_clears_live_secrets_and_redirects_paths(tmp_path):
    environment = {
        "GLASSYTRADE_ENV": "live",
        "GLASSYTRADE_HERMETIC": "0",
        "DHAN_CLIENT_ID": "client",
        "DHAN_ACCESS_TOKEN": "token",
        "DHAN_ALLOW_PROXY_CVD": "true",
        "GLASSYTRADE_DATABASE_PATH": "/var/lib/glassytrade/live.sqlite3",
        "GLASSYTRADE_JOURNAL_PATH": "/var/lib/glassytrade/live.jsonl",
    }

    apply_hermetic_environment(environment, tmp_path)

    assert environment["GLASSYTRADE_ENV"] == "paper"
    assert environment["GLASSYTRADE_HERMETIC"] == "1"
    assert "DHAN_CLIENT_ID" not in environment
    assert "DHAN_ACCESS_TOKEN" not in environment
    assert "DHAN_ALLOW_PROXY_CVD" not in environment
    assert Path(environment["GLASSYTRADE_DATABASE_PATH"]).parent == tmp_path
    assert Path(environment["GLASSYTRADE_JOURNAL_PATH"]).parent == tmp_path


def test_hermetic_mode_never_loads_user_dotenv():
    assert should_load_dotenv({"GLASSYTRADE_HERMETIC": "1"}) is False
    assert should_load_dotenv({"GLASSYTRADE_HERMETIC": "0"}) is True


def test_live_subprocess_is_blocked_even_if_requested_by_a_test():
    with pytest.raises(HermeticViolation, match="live-mode subprocess"):
        assert_paper_subprocess(
            ["python", "-m", "runtime"],
            {"GLASSYTRADE_ENV": "live"},
        )


def test_paper_subprocess_is_allowed():
    assert_paper_subprocess(
        ["python", "-m", "runtime"],
        {"GLASSYTRADE_ENV": "paper"},
    )


def test_only_loopback_addresses_are_allowed_in_hermetic_mode():
    assert is_external_address("127.0.0.1") is False
    assert is_external_address("::1") is False
    assert is_external_address("example.com") is True


def test_registered_profile_redirects_runtime_storage_when_enabled():
    if os.environ.get("GLASSYTRADE_HERMETIC") != "1":
        pytest.skip("profile is opt-in")
    assert os.environ["GLASSYTRADE_ENV"] == "paper"
    assert Path(os.environ["GLASSYTRADE_DATABASE_PATH"]).parent.exists()


def test_registered_profile_blocks_external_socket_and_live_subprocess():
    if os.environ.get("GLASSYTRADE_HERMETIC") != "1":
        pytest.skip("profile is opt-in")
    with pytest.raises(HermeticViolation):
        socket.create_connection(("example.com", 443))
    with pytest.raises(HermeticViolation):
        subprocess.run(["python", "-c", "pass"], env={"GLASSYTRADE_ENV": "live"})
