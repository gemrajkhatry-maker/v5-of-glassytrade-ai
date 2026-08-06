"""Unit tests for quant Signal -> domain Signal mapper.

Note: the domain SignalType enum offers only BUY/SELL (no LONG/SHORT), so
quant LONG/SHORT map to SignalType.BUY/SELL respectively.
"""

from decimal import Decimal

from app.application.services.quant_signal_mapper import quant_signal_to_domain
from app.domain.trading.models.enums import SetupType, SignalType, Source
from quant.decision.signal_builder import Signal


def _qs(type="LONG", reason="Triple-A", entry=100.0, sl=99.0, tp=102.0,
        rr=2.0, confidence=0.8, timestamp="t1"):
    return Signal(
        type=type, reason=reason, entry=entry, sl=sl, tp=tp,
        rr=rr, confidence=confidence, symbol="SYM", timestamp=timestamp,
    )


def test_maps_long():
    s = quant_signal_to_domain(_qs(type="LONG"), "SYM")
    assert s.type == SignalType.BUY
    assert float(s.price) == 100.0
    assert float(s.stop_loss) == 99.0
    assert float(s.take_profit) == 102.0
    assert s.metadata["quant_rr"] == 2.0


def test_maps_short():
    s = quant_signal_to_domain(_qs(type="SHORT", entry=200.0, sl=201.0, tp=198.0), "SYM")
    assert s.type == SignalType.SELL


def test_decimal_precision():
    s = quant_signal_to_domain(_qs(), "SYM")
    assert isinstance(s.price, Decimal)
    assert isinstance(s.stop_loss, Decimal)
    assert isinstance(s.take_profit, Decimal)


def test_metadata_carries_quant_fields():
    qs = _qs(reason="Triple-A")
    s = quant_signal_to_domain(qs, "SYM")
    assert s.metadata["confidence"] == qs.confidence
    assert s.metadata["quant_reason"] == "Triple-A"
    assert s.metadata["phase_from_reason"] == "TRIPLE_A"


def test_triple_a_setup_and_source():
    s = quant_signal_to_domain(_qs(reason="Triple-A"), "SYM")
    assert s.setup == SetupType.TREND_MODEL
    assert s.source == Source.LLM


def test_va_fade_setup():
    s = quant_signal_to_domain(_qs(type="SHORT", reason="VA_FADE"), "SYM")
    assert s.setup == SetupType.RESPONSIVE_FADE
