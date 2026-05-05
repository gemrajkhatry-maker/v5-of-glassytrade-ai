from __future__ import annotations

import logging
import os

from config.consolidated import ConsolidatedConfig as Configuration

from app.domain.ports.market_data import IMarketData
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.llm_inference import ILLMInference
from app.domain.ports.probability_inference import IProbabilityInference
from app.domain.ports.notifications import INotification
from app.domain.ports.delta_profile import IDeltaProfile
from app.domain.ports.npoc import INPOC
from app.domain.ports.exchange_strategy import IExchangeStrategy

from app.domain.fabio_ai.services.gate_pipeline import GatePipeline
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService

from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.infrastructure.adapters.gguf_inference_adapter import GGUFInferenceAdapter
from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
from app.infrastructure.adapters.lgbm_probability_adapter import LGBMProbabilityAdapter
from app.infrastructure.adapters.null_notification_adapter import NullNotificationAdapter
from app.infrastructure.adapters.delta_profile_adapter import DeltaProfileAdapter
from app.infrastructure.adapters.npoc_adapter import NPOCAdapter
from app.infrastructure.strategies.nse_strategy import NSEExchangeStrategy
from app.infrastructure.strategies.mcx_strategy import MCXExchangeStrategy

logger = logging.getLogger(__name__)


def create_llm_inference(config: Configuration, mode: str) -> ILLMInference:
    """Create LLM inference adapter based on configuration and mode."""
    llm_config = getattr(config, "llm", None)
    if llm_config is None:
        from app.domain.ports.llm_inference import LLMNotReadyError
        raise LLMNotReadyError("LLM config not available")

    model_path = getattr(llm_config, "model_path", "") or os.environ.get("MLX_MODEL_PATH", "")
    model_path = model_path.strip()

    if model_path.lower().endswith(".gguf"):
        return GGUFInferenceAdapter(model_path=model_path)

    return MLXInferenceAdapter(
        model_path=model_path,
        temperature=getattr(llm_config, "temperature", 0.7),
        max_new_tokens=getattr(llm_config, "max_new_tokens", 512),
    )


def create_broker(config: Configuration, mode: str) -> IBroker:
    """Create broker adapter based on mode."""
    if mode == "live":
        return DhanBrokerAdapter(config)
    return PaperBrokerAdapter()


def create_market_data(config: Configuration, mode: str) -> IMarketData:
    """Create market data adapter."""
    # Always use Dhan for market data in all modes
    return DhanMarketDataAdapter(config)


def create_storage(config: Configuration, mode: str) -> IStorage:
    """Create storage adapter."""
    db_path = getattr(config, "db_path", "glassytrade.db")
    return SQLiteStorageAdapter(db_path)


def create_probability_engine(config: Configuration, mode: str) -> IProbabilityInference:
    """Create probability engine adapter."""
    model_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "models"
    )
    model_dir = os.path.normpath(model_dir)

    try:
        return LGBMProbabilityAdapter(model_dir)
    except Exception as exc:
        if mode == "live":
            raise RuntimeError(
                "Probability model failed in live mode"
            ) from exc
        from app.domain.ports.probability_inference import NoOpProbabilityAdapter
        return NoOpProbabilityAdapter()


def create_notification() -> INotification:
    """Create notification adapter."""
    return NullNotificationAdapter()


def create_delta_profile() -> IDeltaProfile:
    """Create delta profile adapter."""
    return DeltaProfileAdapter()


def create_npoc() -> INPOC:
    """Create NPOC adapter."""
    return NPOCAdapter()


def create_exchange_strategy(config: Configuration, mode: str) -> IExchangeStrategy:
    """Create exchange strategy adapter."""
    from app.domain.models.exchange_config import ExchangeConfig
    from app.domain.models.exchange import Exchange

    exchange_name = (getattr(config, "default_exchange", None) or "MCX").upper()
    exchange = Exchange.normalize(exchange_name)
    exc_config = ExchangeConfig.for_exchange(exchange.value)

    # NFO (NSE F&O) uses same strategy as NSE
    if exchange_name in ("NSE", "NFO"):
        return NSEExchangeStrategy(exc_config)
    else:
        return MCXExchangeStrategy(exc_config)


def create_gate_pipeline(
    config: Configuration,
    mode: str,
    market_data: IMarketData,
    storage: IStorage,
    llm: ILLMInference,
    probability: IProbabilityInference,
) -> GatePipeline:
    """Create gate pipeline service."""
    return GatePipeline(
        config=config,
        market_data=market_data,
        storage=storage,
        llm=llm,
        probability=probability,
    )


def create_generative_ai_service(llm: ILLMInference) -> GenerativeAIService:
    """Create generative AI service."""
    return GenerativeAIService(llm_adapter=llm)
