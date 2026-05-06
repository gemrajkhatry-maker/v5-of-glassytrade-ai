"""Tests for ISignalService port — domain interface for signal generation.

Behavior: ISignalService should be defined in domain layer as an abstract
interface (port). Infrastructure adapters implement this interface.
"""
from __future__ import annotations

import pytest
from abc import ABC, abstractmethod

from app.domain.shared.port.signal import ISignalService


class TestISignalServicePort:
    """Tests for ISignalService port definition."""

    def test_is_abstract_class(self):
        """ISignalService should be an abstract class."""
        assert issubclass(ISignalService, ABC)

    def test_has_generate_method(self):
        """ISignalService should define generate method."""
        assert hasattr(ISignalService, 'generate')
        assert callable(getattr(ISignalService, 'generate'))

    def test_generate_is_abstract(self):
        """Generate method should be abstract."""
        assert getattr(ISignalService.generate, '__isabstractmethod__', False)

    def test_cannot_instantiate_directly(self):
        """Should not be able to instantiate ISignalService directly."""
        with pytest.raises(TypeError):
            ISignalService()

    def test_can_create_concrete_implementation(self):
        """Should be able to create concrete implementation."""
        class MockSignalService(ISignalService):
            def generate(self, **kwargs):
                return {"action": "BUY", "confidence": 0.8}
        
        service = MockSignalService()
        result = service.generate()
        
        assert result["action"] == "BUY"
        assert result["confidence"] == 0.8

    def test_generate_signature_accepts_phase_results(self):
        """Generate should accept phase results and market data."""
        class MockSignalService(ISignalService):
            def generate(
                self,
                phase1_result: dict,
                phase2_result: dict,
                phase3_result: dict,
                absorptions: list,
                current_price: float,
                vwap: float
            ):
                return {
                    "action": "BUY",
                    "phases": [phase1_result, phase2_result, phase3_result],
                    "price": current_price,
                }
        
        service = MockSignalService()
        result = service.generate(
            phase1_result={"trend": "up"},
            phase2_result={"support": 100.0},
            phase3_result={"resistance": 110.0},
            absorptions=[],
            current_price=105.0,
            vwap=104.0,
        )
        
        assert result["action"] == "BUY"
        assert result["price"] == 105.0
        assert len(result["phases"]) == 3
