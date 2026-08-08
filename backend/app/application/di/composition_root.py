"""Composition Root — builds the dependency graph.

This module is the ONLY place in the application where concrete
implementations are imported. Everything else depends on ports.

Usage:
    container = compose_container(config)
    session = container.resolve(TradingSessionService)
"""

from __future__ import annotations

import logging
import os

from app.config_models import SystemConfig as Configuration
from app.config import settings as _settings

from app.shared.mode import is_live_mode

logger = logging.getLogger(__name__)

from app.application.di.container import DIContainer


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
        _probability_inference_port(),
        lambda c: _create_probability_adapter(c, config),
    )

    container.register_singleton(
        _quant_coordinator(),
        lambda c: _create_quant_coordinator(c, config),
    )

    # --- Additional Infrastructure Adapters ---
    container.register_singleton(
        _delta_profile_port(),
        lambda c: _create_delta_profile_adapter(c),
    )

    container.register_singleton(
        _exchange_strategy_port(),
        lambda c: _create_exchange_strategy(c, config),
    )

    # --- Domain Services ---
    container.register_singleton(
        _gate_pipeline(),
        lambda c: _create_gate_pipeline(c, config),
    )

    container.register_singleton(
        _generative_ai_service(),
        lambda c: _create_generative_ai_service(c),
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


def _probability_inference_port():
    from quant.contracts.ports.probability_inference import IProbabilityInference
    return IProbabilityInference


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


def _create_llm_adapter(container: DIContainer, config: "Configuration"):
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


def _create_probability_adapter(container: DIContainer, config: "Configuration"):
    model_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "models"
    )
    model_dir = os.path.normpath(model_dir)

    try:
        from app.infrastructure.adapters.lgbm_probability_adapter import LGBMProbabilityAdapter
        return LGBMProbabilityAdapter(model_dir)
    except Exception as exc:
        if is_live_mode():
            raise RuntimeError(
                "Probability model failed in live mode"
            ) from exc
        from quant.contracts.ports.probability_inference import NoOpProbabilityAdapter
        return NoOpProbabilityAdapter()


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
    # the coordinator's llm_sink signature (single dict argument).
    try:
        storage = container.resolve(IStorage)
        llm_sink = storage.save_llm_decision
    except Exception:
        logger.warning(
            "QuantCoordinator: storage unavailable — LLM decisions not persisted",
            exc_info=True,
        )
        llm_sink = None

    candle_minutes = int(getattr(config, "candle_timeframe_minutes", 5) or 5)
    coord_config = {
        "underlyings": list(_settings.SCANNER_UNDERLYINGS or []),
        "n": int(_settings.SCANNER_TOP_N or 4),
        "exchange": _settings.DEFAULT_EXCHANGE or "NSE",
        "expiry_index": int(_settings.SCANNER_EXPIRY_INDEX or 0),
        "strikes_around_atm": int(_settings.STRIKES_AROUND_ATM or 2),
        "interval_seconds": candle_minutes * 60,
    }
    logger.info(
        "QuantCoordinator config: underlyings=%s n=%d exchange=%s expiry_index=%d "
        "strikes_around_atm=%d interval_seconds=%d",
        coord_config["underlyings"],
        coord_config["n"],
        coord_config["exchange"],
        coord_config["expiry_index"],
        coord_config["strikes_around_atm"],
        coord_config["interval_seconds"],
    )
    return QuantCoordinator(
        market_data=market_data,
        inference=llm_adapter,
        broker=broker,
        config=coord_config,
        llm_sink=llm_sink,
    )


# ---------------------------------------------------------------------------
# Additional port type getters
# ---------------------------------------------------------------------------

def _delta_profile_port():
    from quant.contracts.ports.delta_profile import IDeltaProfile
    return IDeltaProfile


def _exchange_strategy_port():
    from quant.contracts.ports.exchange_strategy import IExchangeStrategy
    return IExchangeStrategy


def _gate_pipeline():
    from quant.decision.gates.legacy_gate_pipeline import GatePipeline
    return GatePipeline


def _generative_ai_service():
    from quant.inference.generative_ai import GenerativeAIService
    return GenerativeAIService


# ---------------------------------------------------------------------------
# Additional factory functions
# ---------------------------------------------------------------------------

def _create_delta_profile_adapter(container: DIContainer):
    from app.infrastructure.adapters.delta_profile_adapter import DeltaProfileAdapter
    return DeltaProfileAdapter()


def _create_exchange_strategy(container: DIContainer, config: "Configuration"):
    from quant.contracts.exchange_config import ExchangeConfig
    from app.domain.models.exchange import Exchange

    exchange_name = (getattr(config, "default_exchange", None) or _settings.DEFAULT_EXCHANGE or "MCX").upper()
    exchange = Exchange.normalize(exchange_name)
    exc_config = ExchangeConfig.for_exchange(exchange.value)

    # NFO (NSE F&O) uses same strategy as NSE
    if exchange_name in ("NSE", "NFO"):
        from app.infrastructure.strategies.nse_strategy import NSEExchangeStrategy
        return NSEExchangeStrategy(exc_config)
    else:
        from app.infrastructure.strategies.mcx_strategy import MCXExchangeStrategy
        return MCXExchangeStrategy(exc_config)


def _create_gate_pipeline(container: DIContainer, config: "Configuration"):
    from quant.decision.gates.legacy_gate_pipeline import GatePipeline
    from quant.contracts.ports.market_data import IMarketData
    from quant.contracts.ports.storage import IStorage
    from quant.contracts.ports.llm_inference import ILLMInference
    from quant.contracts.ports.probability_inference import IProbabilityInference

    return GatePipeline(
        config=config,
        market_data=container.resolve(IMarketData),
        storage=container.resolve(IStorage),
        llm=container.resolve(ILLMInference),
        probability=container.resolve(IProbabilityInference),
    )


def _create_generative_ai_service(container: DIContainer):
    from quant.inference.generative_ai import GenerativeAIService
    from quant.contracts.ports.llm_inference import ILLMInference

    llm_adapter = container.resolve(ILLMInference)
    return GenerativeAIService(llm_adapter=llm_adapter)


