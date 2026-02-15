"""Dependency injection — service graph factory.

Creates and wires the full service graph once at application startup.
FastAPI dependencies pull from the singleton graph.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.adapters.binance_adapter import BinanceMarketDataAdapter
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.adapters.gemini_adapter import GeminiAIAdapter
from app.application.services.trading_session import TradingSessionService
from app.application.services.trading_session import TradingSessionService
from app.domain.ports.market_data import MarketDataPort
from app.domain.ports.ai_model import AIModelPort
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService


class ServiceGraph:
    """Holds the singleton service instances."""

    def __init__(self) -> None:
        self.event_bus = InMemoryEventBus()
        self.market_data: MarketDataPort = BinanceMarketDataAdapter(
            base_url=settings.BINANCE_BASE_URL,
        )
        self.broker = PaperBrokerAdapter()
        self.ai_model: AIModelPort = GeminiAIAdapter(
            api_key=settings.GEMINI_API_KEY,
        )
        self.gen_ai_service = GenerativeAIService()
        self.trading_session = TradingSessionService(
            event_bus=self.event_bus,
            broker=self.broker,
            gen_ai_service=self.gen_ai_service,
        )


@lru_cache(maxsize=1)
def get_service_graph() -> ServiceGraph:
    """Singleton service graph created once."""
    return ServiceGraph()


# FastAPI dependency helpers

def get_market_data() -> MarketDataPort:
    return get_service_graph().market_data


def get_trading_session() -> TradingSessionService:
    return get_service_graph().trading_session


def get_ai_model() -> AIModelPort:
    return get_service_graph().ai_model


def get_gen_ai_service() -> GenerativeAIService:
    return get_service_graph().gen_ai_service
