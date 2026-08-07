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


def _trading_session_service():
    from app.application.services.trading_session import TradingSessionService
    return TradingSessionService


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class _OverseerBroadcastBridge:
    """Lazily-bound bridge so the overseer can push immediate UI updates.

    The ``TradingEngine`` is constructed AFTER the ``TradingSessionService``
    (main.py builds the engine from the container), so we inject a settable
    bridge at composition time and bind the real engine in
    ``TradingEngine.__init__`` via ``bridge.bind(engine)``.
    """

    def __init__(self) -> None:
        self._target = None

    def bind(self, engine) -> None:
        self._target = engine

    def trigger_immediate_update(self, symbol: str) -> None:
        target = self._target
        if target is not None:
            target.trigger_immediate_update(symbol)


def _wire_overseer_broadcast(session_service) -> None:
    """Inject a lazily-bound broadcast bridge into the overseer handler.

    The overseer's ``_engine`` slot was previously never populated, so
    ``trigger_immediate_update`` was dead. We give it a bridge here (non-None)
    and expose it on the session service so ``TradingEngine.__init__`` can bind
    the real engine reference after construction.
    """
    bridge = _OverseerBroadcastBridge()
    overseer = getattr(session_service, "_overseer_handler", None)
    if overseer is not None:
        if hasattr(overseer, "set_engine"):
            overseer.set_engine(bridge)
        else:
            overseer._engine = bridge
    session_service._overseer_broadcast_bridge = bridge


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

    from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
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


def _create_trading_session(container: DIContainer, config: "Configuration"):
    """Create TradingSessionService with all dependencies from the container."""
    from quant.contracts.ports.broker import IBroker
    from quant.contracts.ports.storage import IStorage
    from quant.contracts.ports.llm_inference import ILLMInference
    from quant.contracts.ports.probability_inference import IProbabilityInference

    broker = container.resolve(IBroker)
    storage = container.resolve(IStorage)
    llm_adapter = container.resolve(ILLMInference)
    probability_engine = container.resolve(IProbabilityInference)

    # Build GenerativeAIService wrapper
    try:
        from quant.inference.generative_ai import GenerativeAIService
        gen_ai_service = GenerativeAIService(llm_adapter=llm_adapter)
    except Exception as exc:
        if is_live_mode():
            raise RuntimeError(
                "GenerativeAIService failed in live mode"
            ) from exc
        logger.error("GenerativeAIService failed to initialize — LLM features disabled", exc_info=True)
        gen_ai_service = None

    # Exchange config
    exchange_config = None
    try:
        from quant.contracts.exchange_config import ExchangeConfig
        from app.domain.models.exchange import Exchange

        exchange = Exchange.normalize(
            getattr(config, "default_exchange", None) or _settings.DEFAULT_EXCHANGE or "MCX"
        )
        exchange_config = ExchangeConfig.for_exchange(exchange.value)
    except Exception:
        logger.warning("Exchange config loading failed — using defaults", exc_info=True)

    # Allow short config
    allow_short = _resolve_allow_short()

    # Observability trackers
    from app.domain.ops.gate_rejection_tracker import GateRejectionTracker
    from app.domain.ops.latency_tracker import LatencyTracker
    gate_tracker = GateRejectionTracker()
    latency_tracker = LatencyTracker()

    from app.application.services.trading_session import TradingSessionService
    session_service = TradingSessionService(
        broker=broker,
        gen_ai_service=gen_ai_service,
        storage=storage,
        probability_engine=probability_engine,
        exchange_config=exchange_config,
        allow_short=allow_short,
        gate_tracker=gate_tracker,
        latency_tracker=latency_tracker,
    )
    _wire_overseer_broadcast(session_service)
    return session_service


# ---------------------------------------------------------------------------
# Additional port type getters
# ---------------------------------------------------------------------------

def _resolve_allow_short() -> bool:
    """Resolve the ALLOW_SHORT feature flag, defaulting to False on error.

    Reads the flag through ``app.shared.config_features`` (the live registry);
    historically this imported the nonexistent ``app.config.features`` module,
    which the try/except silently swallowed and pinned ``allow_short`` False.
    """
    from app.shared.config_features import Feature, feature_enabled
    try:
        return feature_enabled(_settings, Feature.ALLOW_SHORT)
    except Exception:
        logger.debug("ALLOW_SHORT setting not available — defaulting to False", exc_info=True)
        return False


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


