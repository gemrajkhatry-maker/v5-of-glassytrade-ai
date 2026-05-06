"""Domain ports (interfaces) — domain-to-infrastructure boundary.

Ports are defined in the domain layer. Infrastructure adapters implement them.
This ensures dependency inversion: domain has zero dependencies on infrastructure.
"""

from app.domain.shared.port.broker import IBroker
from app.domain.shared.port.market_data import IMarketData
from app.domain.shared.port.delta_profile import IDeltaProfile
from app.domain.shared.port.npoc import INPOC
from app.domain.shared.port.storage import IStorage, IKeyValueStorage
from app.domain.shared.port.llm_inference import ILLMInference, LLMNotReadyError
from app.domain.shared.port.notifications import INotification
from app.domain.shared.port.probability import IProbabilityInference
from app.domain.shared.port.signal import ISignalService

__all__ = [
    "IBroker",
    "IMarketData",
    "IDeltaProfile",
    "INPOC",
    "IStorage",
    "IKeyValueStorage",
    "ILLMInference",
    "LLMNotReadyError",
    "INotification",
    "IProbabilityInference",
    "ISignalService",
]
