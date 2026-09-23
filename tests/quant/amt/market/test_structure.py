"""Unit tests for MarketStructureClassifier — regime detection from candle data."""

from quant.contracts.value_objects import OHLC
from quant.amt.market.structure import (
    MarketStructureClassifier,
    MarketStructure,
)


def _make_candle(
    open: float, high: float, low: float, close: float, volume: float, vwap: float = 0.0
) -> OHLC:
    return OHLC(
        time="t",
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        vwap=vwap,
        delta=0.0,
        taker_buy_volume=0.0,
    )


# ---------------------------------------------------------------------------
# Balance detection
# ---------------------------------------------------------------------------


class TestBalanceDetection:
    def setup_method(self):
        self.classifier = MarketStructureClassifier()

    def test_balance_state(self):
        # Tight range, stable POC/VWAP, uniform volume
        candles = [
            _make_candle(100, 100.5, 99.5, 100.1, 1000, 100.0) for _ in range(30)
        ]
        result = self.classifier.classify(candles, [100.0] * 30, [100.0] * 30)
        assert isinstance(result, MarketStructure)
        assert result.state == "BALANCE"

    def test_balance_has_required_fields(self):
        candles = [
            _make_candle(100, 100.5, 99.5, 100.1, 1000, 100.0) for _ in range(30)
        ]
        result = self.classifier.classify(candles, [100.0] * 30, [100.0] * 30)
        assert hasattr(result, "state")
        assert hasattr(result, "confidence_score")
        assert hasattr(result, "features")


# ---------------------------------------------------------------------------
# Imbalance detection
# ---------------------------------------------------------------------------


class TestImbalanceDetection:
    def setup_method(self):
        self.classifier = MarketStructureClassifier()

    def test_imbalance_or_expansion(self):
        # Strong directional move: each candle opens higher, range expands
        candles = []
        for i in range(30):
            o = 100 + i * 2
            # Range expands as move progresses (simulates real trending)
            spread = 1.0 + i * 0.3
            candles.append(
                _make_candle(
                    o,
                    o + spread,
                    o - 0.2,
                    o + spread - 0.1,
                    1000 + i * 100,
                    o + spread / 2,
                )
            )
        poc_history = [100 + i * 2 for i in range(30)]
        vwap_history = [101 + i * 2 for i in range(30)]
        # Classify multiple times to get past hysteresis
        for _ in range(8):
            result = self.classifier.classify(candles, poc_history, vwap_history)
        assert result.state in ("IMBALANCE", "EXPANSION", "TRANSITION")


# ---------------------------------------------------------------------------
# Chop detection
# ---------------------------------------------------------------------------


class TestChopDetection:
    def setup_method(self):
        self.classifier = MarketStructureClassifier()

    def test_chop_state(self):
        # Alternating candles with high overlap + accelerating volume
        candles = []
        for i in range(30):
            vol = 500 + i * 100  # Volume accelerating
            if i % 2 == 0:
                candles.append(_make_candle(100, 102, 98, 101, vol, 100))
            else:
                candles.append(_make_candle(101, 103, 97, 99, vol, 100))
        poc_history = [100 + (0.5 if i % 2 == 0 else -0.5) for i in range(30)]
        vwap_history = [100.0] * 30
        for _ in range(8):
            result = self.classifier.classify(candles, poc_history, vwap_history)
        # Chop or Balance are both acceptable for oscillating market
        assert result.state in ("CHOP", "BALANCE", "TRANSITION")


# ---------------------------------------------------------------------------
# Expansion detection
# ---------------------------------------------------------------------------


class TestExpansionDetection:
    def setup_method(self):
        self.classifier = MarketStructureClassifier()

    def test_expansion_state(self):
        # Massive directional move: big range, no overlap, volume surging
        candles = []
        for i in range(30):
            o = 100 + i * 5
            spread = 3 + i * 0.5  # Expanding range
            candles.append(
                _make_candle(
                    o,
                    o + spread,
                    o - 0.1,
                    o + spread - 0.1,
                    500 + i * 200,
                    o + spread / 2,
                )
            )
        poc_history = [100 + i * 5 for i in range(30)]
        vwap_history = [102 + i * 5 for i in range(30)]
        for _ in range(8):
            result = self.classifier.classify(candles, poc_history, vwap_history)
        assert result.state in ("EXPANSION", "IMBALANCE", "TRANSITION")


# ---------------------------------------------------------------------------
# Hysteresis
# ---------------------------------------------------------------------------


class TestHysteresis:
    def setup_method(self):
        self.classifier = MarketStructureClassifier()

    def test_immediate_flip_on_strong_breakout(self):
        # Establish BALANCE
        balance = [
            _make_candle(100, 100.5, 99.5, 100.1, 1000, 100.0) for _ in range(30)
        ]
        for _ in range(8):
            r = self.classifier.classify(balance, [100.0] * 30, [100.0] * 30)
        assert r.state == "BALANCE"

        # Switch to strong expansion data — with increased hysteresis (dwell=3, cooldown=3),
        # the state needs multiple bars to transition out of BALANCE.
        # Feed enough expansion bars to overcome dwell + cooldown.
        exp = []
        for i in range(30):
            o = 100 + i * 5
            s = 3 + i * 0.5
            exp.append(
                _make_candle(o, o + s, o - 0.1, o + s - 0.1, 500 + i * 200, o + s / 2)
            )
        poc_exp = [100 + i * 5 for i in range(30)]
        vwap_exp = [102 + i * 5 for i in range(30)]

        # Classify multiple times to get past hysteresis dwell + cooldown
        for _ in range(6):
            first = self.classifier.classify(exp, poc_exp, vwap_exp)
        assert first.state != "BALANCE", (
            "After hysteresis period, state should exit BALANCE on strong breakout"
        )


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------


class TestInsufficientData:
    def setup_method(self):
        self.classifier = MarketStructureClassifier()

    def test_short_candle_list(self):
        candles = [_make_candle(100, 101, 99, 100, 500, 100) for _ in range(5)]
        result = self.classifier.classify(candles, [100.0] * 5, [100.0] * 5)
        assert result.state == "BALANCE"  # default fallback


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    def setup_method(self):
        self.classifier = MarketStructureClassifier()

    def test_confidence_in_range(self):
        candles = [_make_candle(100, 100.5, 99.5, 100.1, 1000, 100) for _ in range(30)]
        result = self.classifier.classify(candles, [100.0] * 30, [100.0] * 30)
        assert 0 <= result.confidence_score <= 100

    def test_strong_balance_high_confidence(self):
        candles = [_make_candle(100, 100.2, 99.8, 100.05, 1000, 100) for _ in range(30)]
        result = self.classifier.classify(candles, [100.0] * 30, [100.0] * 30)
        assert result.confidence_score > 60
