"""Tests for the composition root's advisor-enable decision (D-17).

``LLM_ADVISOR_ENABLED`` must mean one thing everywhere: the coordinator's
``advisor_enabled`` flag must agree with what ``quant.wiring_advisor``
(``build_live_advisor``) would actually build.
"""

from __future__ import annotations


def test_advisor_enabled_matches_the_factory(monkeypatch):
    """D-17: composition_root treated LLM_ADVISOR_ENABLED as an OR-enable while
    wiring_advisor treats it as a hard disable, so the two disagreed about
    whether an advisor exists."""
    monkeypatch.setenv("LLM_ADVISOR_ENABLED", "false")
    monkeypatch.setenv("TIMESFM_ADVISOR_ENABLED", "true")

    from app.application.di.composition_root import _advisor_enabled_from_env

    assert _advisor_enabled_from_env() is False


def test_advisor_enabled_true_only_when_factory_would_build(monkeypatch):
    monkeypatch.setenv("LLM_ADVISOR_ENABLED", "true")
    monkeypatch.setenv("TIMESFM_ADVISOR_ENABLED", "false")

    from app.application.di.composition_root import _advisor_enabled_from_env

    assert _advisor_enabled_from_env() is True


def test_advisor_enabled_false_family_hard_disables(monkeypatch):
    """The same false-family token set the authority uses must hard-disable,
    even when TimesFM is enabled."""
    from app.application.di.composition_root import _advisor_enabled_from_env

    for token in ("0", "false", "no", "disable", "disabled", " FALSE ", "No"):
        monkeypatch.setenv("LLM_ADVISOR_ENABLED", token)
        monkeypatch.setenv("TIMESFM_ADVISOR_ENABLED", "true")
        assert _advisor_enabled_from_env() is False, token


def test_advisor_enabled_unset_llm_is_disabled_by_default(monkeypatch):
    """The authority's default for LLM_ADVISOR_ENABLED is "false", which is in
    the false-family set, so it hard-disables even with TimesFM enabled."""
    from app.application.di.composition_root import _advisor_enabled_from_env

    monkeypatch.delenv("LLM_ADVISOR_ENABLED", raising=False)
    monkeypatch.delenv("TIMESFM_ADVISOR_ENABLED", raising=False)
    assert _advisor_enabled_from_env() is False

    monkeypatch.setenv("TIMESFM_ADVISOR_ENABLED", "yes")
    assert _advisor_enabled_from_env() is False

    # TimesFM alone only produces an advisor when the LLM flag is non-disabling.
    monkeypatch.setenv("LLM_ADVISOR_ENABLED", "true")
    assert _advisor_enabled_from_env() is True


def test_advisor_enabled_is_used_by_coordinator_config(monkeypatch):
    """coord_config["advisor_enabled"] must come from the helper, not an inline
    OR-expression."""
    import inspect

    from app.application.di import composition_root

    src = inspect.getsource(composition_root._create_quant_coordinator)
    assert '"advisor_enabled": _advisor_enabled_from_env(),' in src


def test_coordinator_gets_the_host_telemetry_adapter():
    """The brain counts through its port; the host picks the sink.

    quant owns the interface and must not reach for a counter itself (the
    quant->host import direction is gated in tests/architecture), so the
    composition root is the one place that decides where the counts land.
    """
    import inspect

    from app.application.di import composition_root

    src = inspect.getsource(composition_root._create_quant_coordinator)
    assert "telemetry=PrometheusTelemetry()," in src
    assert "from app.infrastructure.telemetry import PrometheusTelemetry" in src
