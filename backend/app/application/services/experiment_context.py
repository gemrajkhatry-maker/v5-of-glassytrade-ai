"""Run-level experiment context for paper-trading attribution and evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.shared.config_features import Feature, feature_enabled
from app.config import settings
from app.domain.fabio_ai.services.llm_contract import (
    CANONICAL_RUNTIME_MODEL_FAMILY,
    ENTRY_CONTRACT_VERSION,
)
from app.domain.probability.features import PROBABILITY_FEATURE_SCHEMA_VERSION


@dataclass(frozen=True)
class ExperimentContext:
    run_id: str
    created_at: str
    config_fingerprint: str
    trading_mode: str
    exchange: str
    stream_interval: str
    allow_short: bool
    llm_execution_enabled: bool
    scanner_mode: str
    llm_model_family: str
    llm_entry_contract_version: str
    probability_feature_schema_version: str

    def as_metadata(self) -> dict[str, str | bool]:
        return asdict(self)


def build_experiment_context() -> ExperimentContext:
    """Build a stable experiment context for the current backend run."""
    created_at = datetime.now(timezone.utc).isoformat()
    fingerprint_payload = {
        "trading_mode": settings.TRADING_MODE,
        "exchange": settings.DEFAULT_EXCHANGE,
        "stream_interval": settings.STREAM_INTERVAL,
        "allow_short": feature_enabled(settings, Feature.ALLOW_SHORT),
        "llm_execution_enabled": feature_enabled(settings, Feature.LLM_EXECUTION),
        "scanner_mode": settings.SCANNER_MODE,
        "llm_model_family": CANONICAL_RUNTIME_MODEL_FAMILY,
        "llm_entry_contract_version": ENTRY_CONTRACT_VERSION,
        "probability_feature_schema_version": PROBABILITY_FEATURE_SCHEMA_VERSION,
        "llm_model_path": settings.MLX_MODEL_PATH,
    }
    fingerprint = hashlib.sha1(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{fingerprint}"
    return ExperimentContext(
        run_id=run_id,
        created_at=created_at,
        config_fingerprint=fingerprint,
        trading_mode=settings.TRADING_MODE,
        exchange=settings.DEFAULT_EXCHANGE,
        stream_interval=settings.STREAM_INTERVAL,
        allow_short=feature_enabled(settings, Feature.ALLOW_SHORT),
        llm_execution_enabled=feature_enabled(settings, Feature.LLM_EXECUTION),
        scanner_mode=settings.SCANNER_MODE,
        llm_model_family=CANONICAL_RUNTIME_MODEL_FAMILY,
        llm_entry_contract_version=ENTRY_CONTRACT_VERSION,
        probability_feature_schema_version=PROBABILITY_FEATURE_SCHEMA_VERSION,
    )
