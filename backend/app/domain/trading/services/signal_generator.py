"""Signal Generator — domain service that evaluates analysis results and
PREDICTION completions, producing SignalGenerated events when trade setups
are detected.

In the event-driven flow this subscribes to AnalysisCompleted and
PredictionCompleted, but the core logic is a pure function that can be
called directly for testing or non-event usage.
"""

from __future__ import annotations

from app.domain.trading.models.enums import SignalType, Source, SetupType, Sentiment
from app.domain.trading.models.entities import Signal
from app.domain.trading.models.value_objects import AMTResult, OHLC, AIAnalysisResult


class SignalGenerator:
    """Evaluates analysis output and generates trade signals."""

    def evaluate_amt(self, result: AMTResult) -> Signal | None:
        """Extract the signal from an AMT analysis result (if any).

        The AMTAnalyzer already computes the signal internally;
        this method simply extracts it for the event chain.
        """
        return result.signal

    def evaluate_prediction(
        self, analysis: AIAnalysisResult, tick: OHLC, generation: int
    ) -> Signal | None:
        """Generate a signal from AI prediction analysis if confidence is high."""
        if analysis.confidence <= 65:
            return None
        if analysis.sentiment == Sentiment.NEUTRAL.value:
            return None

        sig_type = SignalType.BUY if analysis.sentiment == Sentiment.BULLISH.value else SignalType.SELL
        sl_mult = 0.99 if sig_type == SignalType.BUY else 1.01
        tp = analysis.projected_price

        return Signal(
            type=sig_type,
            price=tick.close,
            reason=f"AI Score: {analysis.quant_score:.0f}",
            setup=SetupType.PREDICTION_ENTRY,
            source=Source.PREDICTION,
            stop_loss=tick.close * sl_mult,
            take_profit=tp,
            timestamp=tick.time,
            metadata={
                "factorBreakdown": {
                    "trend": analysis.factor_breakdown.trend,
                    "momentum": analysis.factor_breakdown.momentum,
                    "delta": analysis.factor_breakdown.delta,
                    "order_book": analysis.factor_breakdown.order_book,
                    "volatility": analysis.factor_breakdown.volatility,
                },
                "generation": generation,
            },
        )
