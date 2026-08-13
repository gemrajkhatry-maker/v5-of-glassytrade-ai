"""Composition Root — builds the dependency graph.

This module is the ONLY place in the application where concrete
implementations are imported. Everything else depends on ports.

Usage:
    container = compose_container(config)
    session = container.resolve(TradingSessionService)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.config_models import SystemConfig as Configuration
from app.config import settings as _settings

from app.shared.mode import is_live_mode

logger = logging.getLogger(__name__)

from app.application.di.container import DIContainer


def _load_llm_history(storage, symbol: str) -> list[dict[str, Any]]:
    """Load durable LLM decisions for a symbol for UI rehydration.

    Normalizes DB rows to match the in-memory live-analysis shape:
    - Drops legacy rows without a usable ``created_at`` (they have no real
      timestamp and would otherwise render as "now" in the UI).
    - Restores the numeric ``timestamp`` (epoch ms) from the ``extra`` JSON so
      hydrated entries sort/dedupe identically to freshly produced ones.
    """
    rows = storage.query_llm_decisions(symbols=[symbol], limit=100)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not (row or {}).get("created_at"):
            continue
        row = dict(row)
        try:
            extra = json.loads(row.get("extra") or "{}")
        except (TypeError, ValueError):
            extra = {}
        ts = extra.get("timestamp")
        if isinstance(ts, (int, float)) and ts > 0:
            row["timestamp"] = int(ts)
        out.append(row)
    return out


def compose_container(config: "Configuration") -> DIContainer:
    """Build the complete dependency graph.

    Args:
        config: Application configuration.

    Returns:
        A fully wired DIContainer ready for resolution.
    """
    container = DIContainer()

    # --- Configuration ---
    container.register_singleton(
        Configuration,
        lambda c: config,
    )

    # --- Infrastructure Adapters ---
    container.register_singleton(
        _market_data_port(),
        lambda c: _create_market_data_adapter(c, config),
    )

    container.register_singleton(
        _broker_port(),
        lambda c: _create_broker_adapter(c, config),
    )

    container.register_singleton(
        _storage_port(),
        lambda c: _create_storage_adapter(c, config),
    )

    container.register_singleton(
        _llm_inference_port(),
        lambda c: _create_llm_adapter(c, config),
    )

    container.register_singleton(
        _quant_coordinator(),
        lambda c: _create_quant_coordinator(c, config),
    )

    return container


# ---------------------------------------------------------------------------
# Port type getters (lazy to avoid circular imports)
# ---------------------------------------------------------------------------

def _market_data_port():
    from quant.contracts.ports.market_data import IMarketData
    return IMarketData


def _broker_port():
    from quant.contracts.ports.broker import IBroker
    return IBroker


def _storage_port():
    from quant.contracts.ports.storage import IStorage
    return IStorage


def _llm_inference_port():
    from quant.contracts.ports.llm_inference import ILLMInference
    return ILLMInference


def _quant_coordinator():
    from quant.coordinator import QuantCoordinator
    return QuantCoordinator


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def _create_market_data_adapter(container: DIContainer, config: "Configuration"):
    from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
    return DhanMarketDataAdapter(config)


def _create_broker_adapter(container: DIContainer, config: "Configuration"):
    live_mode = is_live_mode()
    if live_mode:
        from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
        return DhanBrokerAdapter(config)
    from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
    return PaperBrokerAdapter()


def _create_storage_adapter(container: DIContainer, config: "Configuration"):
    from app.infrastructure.storage.database import SQLiteStorageAdapter
    db_path = getattr(config, "db_path", "glassytrade.db")
    return SQLiteStorageAdapter(db_path)


class NullLLMInference:
    """No-op inference used when LLM_DISABLED=1 — never loads a model and
    reports not-ready, so the engine treats it as "no LLM" everywhere
    (advisory, overseer, health) without touching the MLX/Metal stack."""

    def predict(self, instruction="", input_text="", temperature=None,
                max_tokens=None, prefill=None) -> str:
        return '{"direction": "FLAT", "rationale": "LLM disabled", "confidence": "Low"}'

    def is_ready(self) -> bool:
        return False

    def is_loading(self) -> bool:
        return False

    def validate(self) -> bool:
        return False


def _create_llm_adapter(container: DIContainer, config: "Configuration"):
    if os.environ.get("LLM_DISABLED", "0") == "1":
        logger.info("LLM_DISABLED=1 — running without LLM inference")
        return NullLLMInference()
    llm_config = getattr(config, "llm", None)
    if llm_config is None:
        from quant.contracts.ports.llm_inference import LLMNotReadyError
        raise LLMNotReadyError("LLM config not available")

    model_path = getattr(llm_config, "model_path", "") or os.environ.get("MLX_MODEL_PATH", "")
    model_path = model_path.strip()

    if model_path.lower().endswith(".gguf"):
        from app.infrastructure.adapters.gguf_inference_adapter import GGUFInferenceAdapter
        return GGUFInferenceAdapter(model_path=model_path)

    from quant.inference.mlx_inference_adapter import MLXInferenceAdapter
    return MLXInferenceAdapter(
        model_path=model_path,
        temperature=_resolve_llm_temperature(llm_config),
        max_new_tokens=int(getattr(llm_config, "max_tokens", 512)),
    )


def _resolve_llm_temperature(llm_config) -> float:
    """Resolve LLM temperature from env override or mid of entry/overseer."""
    raw = os.getenv("LLM_TEMPERATURE")
    if raw is not None and str(raw).strip() != "":
        return float(raw)
    entry = float(getattr(llm_config, "temperature_entry", 0.4))
    overseer = float(getattr(llm_config, "temperature_overseer", 0.3))
    return (entry + overseer) / 2.0


def _create_quant_coordinator(container: DIContainer, config: "Configuration"):
    """Build the greenfield QuantCoordinator — the source of truth for the
    WS viewer + REST shell. Reuses the same market-data / LLM / broker
    adapters registered for the legacy engine; the coordinator only starts
    its engines when main.py gates it via GREENFIELD_ENGINE=1."""
    from quant.coordinator import QuantCoordinator
    from quant.contracts.ports.market_data import IMarketData
    from quant.contracts.ports.broker import IBroker
    from quant.contracts.ports.llm_inference import ILLMInference
    from quant.contracts.ports.storage import IStorage

    market_data = container.resolve(IMarketData)
    broker = container.resolve(IBroker)
    try:
        llm_adapter = container.resolve(ILLMInference)
    except Exception:
        logger.warning(
            "QuantCoordinator: LLM adapter unavailable — running without inference",
            exc_info=True,
        )
        llm_adapter = None

    # Persist every live LLM fold-back to the decisions table so the UI history
    # survives restarts. storage.save_llm_decision(symbol, direction, ...) matches
    # the coordinator's llm_sink signature (single dict argument). Also inject a
    # history loader so the coordinator can rehydrate per-symbol history from the
    # DB on restart (durable rows outlive the in-memory engine history).
    try:
        storage = container.resolve(IStorage)
        llm_sink = storage.save_llm_decision
        history_loader = (
            lambda symbol, _storage=storage: _load_llm_history(_storage, symbol)
        )
    except Exception:
        logger.warning(
            "QuantCoordinator: storage unavailable — LLM decisions not persisted",
            exc_info=True,
        )
        llm_sink = None
        history_loader = None

    candle_minutes = int(getattr(config, "candle_timeframe_minutes", 5) or 5)
    coord_config = {
        "underlyings": list(_settings.SCANNER_UNDERLYINGS or []),
        "n": int(_settings.SCANNER_TOP_N or 4),
        "exchange": _settings.DEFAULT_EXCHANGE or "NSE",
        "expiry_index": int(_settings.SCANNER_EXPIRY_INDEX or 0),
        "strikes_around_atm": int(_settings.STRIKES_AROUND_ATM or 2),
        "interval_seconds": candle_minutes * 60,
        "underlying_priority": _settings.SCANNER_UNDERLYING_PRIORITY,
    }
    logger.info(
        "QuantCoordinator config: underlyings=%s n=%d exchange=%s expiry_index=%d "
        "strikes_around_atm=%d interval_seconds=%d priority=%s",
        coord_config["underlyings"],
        coord_config["n"],
        coord_config["exchange"],
        coord_config["expiry_index"],
        coord_config["strikes_around_atm"],
        coord_config["interval_seconds"],
        coord_config["underlying_priority"],
    )
    return QuantCoordinator(
        market_data=market_data,
        inference=llm_adapter,
        broker=broker,
        config=coord_config,
        llm_sink=llm_sink,
        history_loader=history_loader,
    )


