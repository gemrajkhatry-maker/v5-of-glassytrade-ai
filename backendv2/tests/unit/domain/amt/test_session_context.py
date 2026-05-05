"""Tests for Session Context."""

import pytest
from datetime import datetime

from app.domain.amt.service.session_context import (
    SessionContextEngine,
    SessionContext,
    GapSize,
    OpeningBias,
    SessionPhase,
)


class TestSessionContextEngine:
    """Tests for session context analysis."""

    def test_gap_classification_small(self):
        """Gap < threshold -> SMALL."""
        engine = SessionContextEngine(gap_medium_pct=0.5, gap_large_pct=1.0)
        
        context = engine.analyze(open_price=100.2, prior_close=100.0, prior_poc=100.0)
        
        assert context.gap_size == GapSize.SMALL

    def test_gap_classification_medium(self):
        """Gap > threshold -> MEDIUM."""
        engine = SessionContextEngine(gap_medium_pct=0.5, gap_large_pct=1.0)
        
        context = engine.analyze(open_price=101.0, prior_close=100.0, prior_poc=100.0)
        
        assert context.gap_size == GapSize.MEDIUM

    def test_gap_classification_large(self):
        """Gap >> threshold -> LARGE."""
        engine = SessionContextEngine(gap_medium_pct=0.5, gap_large_pct=1.0)
        
        context = engine.analyze(open_price=102.5, prior_close=100.0, prior_poc=100.0)
        
        assert context.gap_size == GapSize.LARGE

    def test_opening_bias_long(self):
        """Price above prior POC -> LONG_BIAS."""
        engine = SessionContextEngine()
        
        context = engine.analyze(open_price=102.0, prior_close=100.0, prior_poc=100.0)
        
        assert context.opening_bias == OpeningBias.LONG_BIAS

    def test_opening_bias_short(self):
        """Price below prior POC -> SHORT_BIAS."""
        engine = SessionContextEngine()
        
        context = engine.analyze(open_price=98.0, prior_close=100.0, prior_poc=100.0)
        
        assert context.opening_bias == OpeningBias.SHORT_BIAS

    def test_opening_bias_neutral(self):
        """Price at prior POC -> NEUTRAL."""
        engine = SessionContextEngine()
        
        context = engine.analyze(open_price=100.0, prior_close=100.0, prior_poc=100.0)
        
        assert context.opening_bias == OpeningBias.NEUTRAL

    def test_session_phase_morning(self):
        """Before noon -> MORNING."""
        engine = SessionContextEngine()
        
        ts = datetime(2024, 1, 1, 10, 0)
        context = engine.analyze(
            open_price=100.0, prior_close=100.0, prior_poc=100.0, timestamp=ts
        )
        
        assert context.session_phase == SessionPhase.MORNING

    def test_session_phase_afternoon(self):
        """After noon -> AFTERNOON."""
        engine = SessionContextEngine()
        
        ts = datetime(2024, 1, 1, 13, 0)
        context = engine.analyze(
            open_price=100.0, prior_close=100.0, prior_poc=100.0, timestamp=ts
        )
        
        assert context.session_phase == SessionPhase.AFTERNOON

    def test_day_type_classification(self):
        """Day type from price action."""
        engine = SessionContextEngine()
        
        context = engine.analyze(open_price=100.0, prior_close=100.0, prior_poc=100.0)
        
        assert context.day_type == "NORMAL"

    def test_session_context_frozen(self):
        """SessionContext is frozen dataclass."""
        context = SessionContext(
            gap_size=GapSize.SMALL,
            opening_bias=OpeningBias.NEUTRAL,
            session_phase=SessionPhase.MORNING,
            day_type="NORMAL",
            gap_pct=0.2,
            open_price=100.2,
            prior_close=100.0
        )
        
        with pytest.raises(Exception):
            context.gap_size = GapSize.LARGE