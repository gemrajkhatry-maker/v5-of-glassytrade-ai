"""StateProjector — folds the quant event stream into the frontend view-state.

Pure and deterministic: feeding the same event sequence always produces the
same per-symbol snapshot. The ``auction`` dict mirrors the camelCase keys the
backend serializer emits (``backend.app.application.services.quant_bridge``),
which is the WS contract the frontend already reads.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant.auction_state import AuctionState
from quant.decision.decision_service import QuantDecision
from quant.events import (
    AgentDecisionProduced,
    AmtUpdated,
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
    DepthUpdated,
    Event,
    LLMAnalysisProduced,
    OverseerProduced,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
)
from quant.execution.order import Fill, Position
from quant.execution.risk import RiskState


@dataclass(frozen=True)
class ViewState:
    symbol: str
    tick: dict | None = None
    ltp: float | None = None
    oi: float | None = None
    auction: dict | None = None
    quant_decision: dict | None = None
    risk_state: dict | None = None
    portfolio: dict | None = None
    depth: dict | None = None
    amt: dict | None = None
    gen_ai: dict | None = None
    overseer_action: str = ""
    overseer_reason: str = ""
    agent_decision: dict | None = None


def _auction_to_view(state: AuctionState) -> dict:
    """Serialize an AuctionState to the camelCase WS ``auction`` DTO.

    Mirrors ``auction_state_to_dto`` in the backend serializer so the keys the
    frontend reads (tripleAPhase, volumeProfile, vwap, orderFlow, ...) match
    exactly.
    """
    vp = state.volume_profile
    vw = state.vwap
    of = state.order_flow
    loc = state.location
    ab = state.absorption
    return {
        "time": state.time,
        "close": round(float(state.close), 4),
        "volumeProfile": {
            "poc": round(vp.poc, 4),
            "vah": round(vp.vah, 4),
            "val": round(vp.val, 4),
            "step": round(vp.step, 4),
            "totalVolume": round(vp.total_volume, 2),
        },
        "vwap": {
            "value": round(vw.value, 4),
            "upper1": round(vw.upper_1, 4),
            "lower1": round(vw.lower_1, 4),
            "upper2": round(vw.upper_2, 4),
            "lower2": round(vw.lower_2, 4),
            "std": round(vw.std, 4),
            "deviationSigmas": round(vw.deviation_sigmas, 4),
        },
        "orderFlow": {
            "delta": round(of.delta, 2),
            "cvd": round(of.cvd, 2),
            "cvdSlope": round(of.cvd_slope, 4),
            "cvdDivergence": of.cvd_divergence,
        },
        "absorption": (
            {
                "side": ab.side,
                "price": round(ab.price, 4),
                "volume": round(ab.volume, 2),
                "strength": round(ab.strength, 4),
                "barAge": ab.bar_age,
            }
            if ab is not None
            else None
        ),
        "location": {
            "ibHigh": round(loc.ib_high, 4),
            "ibLow": round(loc.ib_low, 4),
            "ibComplete": loc.ib_complete,
            "zone": loc.zone,
            "nearestLevel": round(loc.nearest_level, 4),
            "distanceToLevel": round(loc.distance_to_level, 4),
        },
        "tripleAPhase": state.triple_a_phase,
        "tripleASignal": state.triple_a_signal,
    }


def _bar_to_tick(bar) -> dict:
    """Map a closed quant Bar to the frontend OHLCData tick shape.

    ``vwap`` is a required schema field but a Bar carries no vwap — it is left
    as 0.0; the engine/ws-adapter may enrich it later.
    """
    return {
        "time": bar.time,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "vwap": 0.0,
        "takerBuyVolume": float(bar.buy_volume),
        "delta": float(bar.delta),
    }


def _decision_to_view(decision: QuantDecision) -> dict:
    sig = decision.signal
    return {
        "approved": bool(decision.approved),
        "reason": decision.reason,
        "phase": decision.phase,
        "signal": (
            {
                "type": sig.type,
                "entry": round(float(sig.entry), 4),
                "sl": round(float(sig.sl), 4),
                "tp": round(float(sig.tp), 4),
                "rr": round(float(sig.rr), 4),
                "confidence": round(float(sig.confidence), 4),
            }
            if sig is not None
            else None
        ),
    }


def _risk_to_view(risk: RiskState) -> dict:
    return {
        "halted": risk.halted,
        "haltReason": risk.halt_reason,
        "consecutiveLosses": risk.consecutive_losses,
        "dailyPnl": risk.daily_pnl,
    }


def _position_to_view(position: Position, fill: Fill | None = None) -> dict:
    sig = position.order.signal
    dto = {
        "id": position.open_time,
        "symbol": sig.symbol,
        "side": sig.type,
        "source": "AMT",
        "entryPrice": float(position.open_price),
        "size": float(position.size),
        "stopLoss": float(sig.sl),
        "takeProfit": float(sig.tp),
        "pnl": float(fill.pnl if fill is not None else position.realized_pnl),
        "entryTime": position.open_time,
        "status": "CLOSED" if fill is not None else "OPEN",
    }
    if fill is not None:
        dto["exitPrice"] = float(fill.close_price)
        dto["exitTime"] = fill.close_time
        dto["closeReason"] = fill.reason
    return dto


class StateProjector:
    """Fold events per symbol into the latest frontend view-state."""

    def __init__(self) -> None:
        self._state: dict[str, dict] = {}

    def on_event(self, event: Event) -> None:
        s = self._symbol_state(event.symbol)
        if isinstance(event, BarClosed):
            s["ltp"] = float(event.bar.close)
            s["oi"] = float(getattr(event.bar, "oi", 0.0) or 0.0)
            s["tick"] = _bar_to_tick(event.bar)
        elif isinstance(event, AuctionUpdated):
            s["auction"] = _auction_to_view(event.auction)
        elif isinstance(event, DecisionProduced):
            s["quant_decision"] = _decision_to_view(event.decision)
        elif isinstance(event, RiskUpdated):
            s["risk_state"] = _risk_to_view(event.risk)
        elif isinstance(event, PositionOpened):
            s["portfolio"] = self._portfolio(s["portfolio"])
            s["portfolio"]["positions"].append(_position_to_view(event.position))
        elif isinstance(event, PositionClosed):
            s["portfolio"] = self._portfolio(s["portfolio"])
            fill = event.fill
            self._remove_open(fill.position.open_time, s["portfolio"])
            s["portfolio"]["closedTrades"].append(_position_to_view(fill.position, fill))
        elif isinstance(event, DepthUpdated):
            s["depth"] = event.depth
        elif isinstance(event, AmtUpdated):
            s["amt"] = event.amt
        elif isinstance(event, LLMAnalysisProduced):
            s["gen_ai"] = event.analysis
        elif isinstance(event, OverseerProduced):
            s["overseer_action"] = event.action
            s["overseer_reason"] = event.reason
        elif isinstance(event, AgentDecisionProduced):
            s["agent_decision"] = event.decision

    def snapshot(self, symbol: str) -> ViewState:
        s = self._symbol_state(symbol)
        return ViewState(
            symbol=symbol,
            tick=s["tick"],
            ltp=s["ltp"],
            oi=s["oi"],
            auction=s["auction"],
            quant_decision=s["quant_decision"],
            risk_state=s["risk_state"],
            portfolio=s["portfolio"],
            depth=s["depth"],
            amt=s["amt"],
            gen_ai=s["gen_ai"],
            overseer_action=s["overseer_action"],
            overseer_reason=s["overseer_reason"],
            agent_decision=s["agent_decision"],
        )

    def _symbol_state(self, symbol: str) -> dict:
        if symbol not in self._state:
            self._state[symbol] = {
                "tick": None,
                "ltp": None,
                "oi": None,
                "auction": None,
                "quant_decision": None,
                "risk_state": None,
                "portfolio": None,
                "depth": None,
                "amt": None,
                "gen_ai": None,
                "overseer_action": "",
                "overseer_reason": "",
                "agent_decision": None,
            }
        return self._state[symbol]

    @staticmethod
    def _portfolio(current: dict | None) -> dict:
        if current is None:
            return {"positions": [], "closedTrades": []}
        return current

    @staticmethod
    def _remove_open(open_time: str, portfolio: dict) -> None:
        positions = portfolio["positions"]
        for i, p in enumerate(positions):
            if p["entryTime"] == open_time:
                del positions[i]
                break
