"""Map a quant Signal to the domain Signal used by the execution path.

Closest-enum mapping (documented choices):
- SignalType offers only BUY/SELL (no LONG/SHORT): LONG -> BUY, SHORT -> SELL.
- Source has no QUANT value: LLM is the closest (plan: "closest to LLM/QUANT").
- SetupType has no TRIPLE_A/IMBALANCE: TREND_MODEL for Triple-A continuation
  entries, RESPONSIVE_FADE for VA-fade entries.
- phase_from_reason derives a phase label from the quant reason since the
  quant Signal does not carry AuctionState.triple_a_phase.
"""

from quant.contracts.entities import Signal as DomainSignal
from quant.contracts.enums import SetupType, SignalType, Source
from quant.decision.signal_builder import Signal as QuantSignal

_SETUP_BY_REASON: dict[str, SetupType] = {
    "TRIPLE_A": SetupType.TREND_MODEL,
    "VA_FADE": SetupType.RESPONSIVE_FADE,
}


def _normalize_reason(reason: str) -> str:
    return reason.replace("-", "_").replace(" ", "_").upper()


def quant_signal_to_domain(qs: QuantSignal, symbol: str) -> DomainSignal:
    """Map quant.decision.signal_builder.Signal -> quant.contracts.entities.Signal.

    type LONG/SHORT -> SignalType.BUY/SELL; price=entry; stop_loss=sl; take_profit=tp;
    setup = closest SetupType; source = closest Source; metadata = {quant_rr, confidence,
    quant_reason, phase_from_reason}.
    """
    reason_key = _normalize_reason(qs.reason)
    setup = _SETUP_BY_REASON.get(reason_key, SetupType.TREND_MODEL)
    return DomainSignal.create(
        type=SignalType.BUY if qs.type.upper() == "LONG" else SignalType.SELL,
        price=qs.entry,
        reason=qs.reason,
        stop_loss=qs.sl,
        take_profit=qs.tp,
        timestamp=qs.timestamp,
        setup=setup,
        source=Source.LLM,
        metadata={
            "quant_rr": qs.rr,
            "confidence": qs.confidence,
            "quant_reason": qs.reason,
            "phase_from_reason": reason_key,
        },
    )
