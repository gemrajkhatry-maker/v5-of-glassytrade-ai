"""Signal Service port — abstract interface for signal generation.

Domain defines this port. Infrastructure/Application provides the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ISignalService(ABC):
    """Abstract interface for generating trading signals.
    
    This is a domain port that defines the contract for signal generation.
    Implementations may use LLM inference, rule-based logic, or ML models.
    """

    @abstractmethod
    def generate(
        self,
        phase1_result: dict[str, Any],
        phase2_result: dict[str, Any],
        phase3_result: dict[str, Any],
        absorptions: list[dict[str, Any]],
        current_price: float,
        vwap: float,
    ) -> dict[str, Any]:
        """Generate trading signal from analysis results.
        
        Args:
            phase1_result: Market structure analysis results
            phase2_result: Risk evaluation results
            phase3_result: Entry gate evaluation results
            absorptions: List of absorption events detected
            current_price: Current market price
            vwap: Volume-weighted average price
            
        Returns:
            Dictionary containing signal decision:
            - action: "BUY", "SELL", or "WAIT"
            - confidence: Signal confidence score (0.0 to 1.0)
            - reason: Human-readable explanation
            - metadata: Additional context
        """
