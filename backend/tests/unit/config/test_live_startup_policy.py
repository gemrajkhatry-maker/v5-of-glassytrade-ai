import pytest

from glassytrade.bootstrap.runtime_config import RuntimeConfig, StartupError


def _live_values(**overrides):
    values = {
        "mode": "live",
        "account_id": "live-account",
        "exchange": "NSE",
        "database_path": "/tmp/live.sqlite3",
        "evidence_policy": "EXACT_ONLY",
        "risk_policy": {},
        "broker_capabilities": frozenset({"native_stop", "order_lookup", "fills"}),
        "config_fingerprint": "live-test",
    }
    values.update(overrides)
    return values


def test_live_config_accepts_explicit_safe_values():
    config = RuntimeConfig.from_mapping(_live_values())
    assert config.mode == "live"
    assert config.exchange == "NSE"
    assert config.broker_capabilities == frozenset(
        {"native_stop", "order_lookup", "fills"}
    )


def test_live_config_rejects_each_destructive_flag():
    for key in (
        "clear_positions_on_restart",
        "reconcile_delete_stale",
        "allow_proxy_cvd",
    ):
        with pytest.raises(StartupError, match="unsafe live settings enabled"):
            RuntimeConfig.from_mapping(_live_values(**{key: True}))


def test_live_config_rejects_string_false_flags_as_enabled_only_when_truthy():
    config = RuntimeConfig.from_mapping(
        _live_values(
            clear_positions_on_restart="false",
            reconcile_delete_stale="0",
            allow_proxy_cvd="off",
        )
    )
    assert config.mode == "live"


def test_live_config_requires_identity_database_and_evidence_policy():
    for missing in ("account_id", "database_path", "evidence_policy", "config_fingerprint"):
        values = _live_values()
        values.pop(missing)
        with pytest.raises(StartupError, match="missing runtime config"):
            RuntimeConfig.from_mapping(values)


def test_shadow_mode_is_valid_but_target_engine_is_explicit():
    config = RuntimeConfig.from_mapping(
        {
            "mode": "shadow",
            "account_id": "shadow-account",
            "exchange": "NSE",
            "database_path": "/tmp/shadow.sqlite3",
            "evidence_policy": "EXACT_ONLY",
            "risk_policy": {},
            "broker_capabilities": frozenset(),
            "config_fingerprint": "shadow-test",
            "runtime_engine": "target",
        }
    )
    assert config.mode == "shadow"
    assert config.runtime_engine == "target"


def test_application_factory_refuses_live_without_explicit_capabilities(monkeypatch):
    from app.main import _runtime_config_from_environment

    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    for name in (
        "GLASSYTRADE_ACCOUNT_ID",
        "GLASSYTRADE_DATABASE_PATH",
        "GLASSYTRADE_EVIDENCE_POLICY",
        "GLASSYTRADE_CONFIG_FINGERPRINT",
        "GLASSYTRADE_BROKER_CAPABILITIES",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(StartupError, match="broker_capabilities"):
        _runtime_config_from_environment(object(), "live")
