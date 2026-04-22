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
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from config.config import Configuration

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

    # --- Domain Services ---
    container.register_singleton(
        _volume_profile_service(),
        lambda c: _create_volume_profile_service(c),
    )

    # --- Application Services ---
    container.register_singleton(
        _trading_session_service(),
        lambda c: _create_trading_session(c, config),
    )

    return container


# ---------------------------------------------------------------------------
# Port type getters (lazy to avoid circular imports)
# ---------------------------------------------------------------------------

def _market_data_port():
    from app.domain.ports.market_data import IMarketData
    return IMarketData


def _broker_port():
    from app.domain.ports.broker import IBroker
    return IBroker


def _storage_port():
    from app.domain.ports.storage import IStorage
    return IStorage


def _llm_inference_port():
    from app.domain.ports.llm_inference import ILLMInference
    return ILLMInference


def _probability_inference_port():
    from app.domain.ports.probability_inference import IProbabilityInference
    return IProbabilityInference


def _volume_profile_service():
    from app.domain.services.volume_profile_service import VolumeProfileService
    return VolumeProfileService


def _trading_session_service():
    from app.application.services.trading_session import TradingSessionService
    return TradingSessionService


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def _create_market_data_adapter(container: DIContainer, config: "Configuration"):
    from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
    return DhanMarketDataAdapter(config)


def _create_broker_adapter(container: DIContainer, config: "Configuration"):
    live_mode = _is_live_mode()
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
        from app.domain.ports.llm_inference import LLMNotReadyError
        raise LLMNotReadyError("LLM config not available")

    model_path = getattr(llm_config, "model_path", "") or os.environ.get("MLX_MODEL_PATH", "")
    model_path = model_path.strip()

    if model_path.lower().endswith(".gguf"):
        from app.infrastructure.adapters.gguf_inference_adapter import GGUFInferenceAdapter
        return GGUFInferenceAdapter(model_path=model_path)

    from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
    return MLXInferenceAdapter(
        model_path=model_path,
        temperature=getattr(llm_config, "temperature", 0.7),
        max_new_tokens=getattr(llm_config, "max_new_tokens", 512),
    )


def _create_probability_adapter(container: DIContainer, config: "Configuration"):
    model_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "models"
    )
    model_dir = os.path.normpath(model_dir)

    try:
        from app.infrastructure.adapters.lgbm_probability_adapter import LGBMProbabilityAdapter
        return LGBMProbabilityAdapter(model_dir)
    except Exception as exc:
        if _is_live_mode():
            raise RuntimeError(
                "Probability model failed in live mode"
            ) from exc
        from app.domain.ports.probability_inference import NoOpProbabilityAdapter
        return NoOpProbabilityAdapter()


def _create_volume_profile_service(container: DIContainer):
    from app.domain.services.volume_profile_service import VolumeProfileService
    return VolumeProfileService()


def _create_trading_session(container: DIContainer, config: "Configuration"):
    """Create TradingSessionService with all dependencies from the container."""
    from app.domain.ports.broker import IBroker
    from app.domain.ports.storage import IStorage
    from app.domain.ports.llm_inference import ILLMInference
    from app.domain.ports.probability_inference import IProbabilityInference

    broker = container.resolve(IBroker)
    storage = container.resolve(IStorage)
    llm_adapter = container.resolve(ILLMInference)
    probability_engine = container.resolve(IProbabilityInference)

    # Build GenerativeAIService wrapper
    try:
        from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
        gen_ai_service = GenerativeAIService(llm_adapter=llm_adapter)
    except Exception:
        gen_ai_service = None

    # Exchange config
    exchange_config = None
    try:
        from app.domain.models.exchange_config import ExchangeConfig
        from app.domain.models.exchange import Exchange

        exchange = Exchange.normalize(
            getattr(config, "default_exchange", "MCX") or "MCX"
        )
        exchange_config = ExchangeConfig.for_exchange(exchange.value)
    except Exception:
        logger.warning("Exchange config loading failed — using defaults", exc_info=True)

    # Allow short config
    allow_short = False
    try:
        from app.config import settings as _settings
        allow_short = bool(getattr(_settings, "ALLOW_SHORT", False))
    except Exception:
        logger.debug("ALLOW_SHORT setting not available — defaulting to False")

    from app.application.services.trading_session import TradingSessionService
    return TradingSessionService(
        broker=broker,
        gen_ai_service=gen_ai_service,
        storage=storage,
        probability_engine=probability_engine,
        exchange_config=exchange_config,
        allow_short=allow_short,
    )


def _is_live_mode() -> bool:
    env_mode = (os.getenv("GLASSYTRADE_ENV", "") or "").strip().lower()
    trading_mode = (os.getenv("TRADING_MODE", "") or "").strip().lower()
    return env_mode == "live" or trading_mode == "live"
