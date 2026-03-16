"""Tests for run-level experiment context."""

from __future__ import annotations

from app.application.services.experiment_context import build_experiment_context


def test_build_experiment_context_contains_contract_metadata():
    ctx = build_experiment_context()

    assert ctx.run_id
    assert ctx.config_fingerprint
    assert ctx.llm_entry_contract_version == "entry-json-v1"
    assert ctx.probability_feature_schema_version == "fp-42-v1"


def test_experiment_context_metadata_round_trip():
    ctx = build_experiment_context()
    meta = ctx.as_metadata()

    assert meta["run_id"] == ctx.run_id
    assert meta["config_fingerprint"] == ctx.config_fingerprint
    assert meta["exchange"] == ctx.exchange
    assert meta["llm_execution_enabled"] == ctx.llm_execution_enabled
