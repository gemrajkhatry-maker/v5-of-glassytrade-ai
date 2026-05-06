"""Volume-profile driven contract selector."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VolumeProfile:
    symbol: str
    poc: float
    vah: float
    val: float
    lvns: tuple[float, ...]
    hvns: tuple[float, ...]
    total_volume: float


@dataclass(frozen=True)
class MarketState:
    market_state: str
    price: float
    poc: float
    vah: float
    val: float
    distance_to_vah: float
    distance_to_val: float
    rr_ratio: float = 1.0

    def rr_filter(self, threshold: float = 2.5) -> bool:
        return self.rr_ratio >= threshold


@dataclass(frozen=True)
class VPContractCandidate:
    symbol: str
    underlying: str
    option_type: str
    strike: int
    entry: float
    stop: float
    target: float
    rr_ratio: float
    reason: str


@dataclass(frozen=True)
class VPSelectionResult:
    candidates: tuple[VPContractCandidate, ...]
    market_states: dict[str, MarketState]
    total_contracts: int


class VPContractSelector:
    """Builds near-contract candidates from a volume-profile envelope."""

    NSE_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
    MCX_UNDERLYINGS = ("CRUDEOIL", "NATURALGAS", "GOLD", "SILVER")
    STRIKE_STEP = {
        "NIFTY": 50,
        "BANKNIFTY": 100,
        "FINNIFTY": 50,
        "CRUDEOIL": 50,
        "NATURALGAS": 10,
        "GOLD": 100,
        "SILVER": 1000,
    }

    def __init__(self, data_provider: Any | None = None, exchange: str = "NSE", underlyings: list[str] | None = None) -> None:
        self._provider = data_provider
        self._exchange = exchange
        self._underlyings = underlyings or list(self.NSE_UNDERLYINGS if exchange == "NSE" else self.MCX_UNDERLYINGS)

    def select(self, price_map: dict[str, float] | None = None, min_rr: float = 2.5) -> VPSelectionResult:
        candidates: list[VPContractCandidate] = []
        states: dict[str, MarketState] = {}
        for symbol in self._underlyings:
            vp = self._infer_volume_profile(symbol)
            if vp is None:
                continue
            price = self._resolve_price(symbol, price_map)
            if price <= 0:
                continue
            market_state = self._classify_market_state(price, vp)
            states[symbol] = market_state
            if not market_state.rr_filter(min_rr):
                continue
            candidates.extend(self._build_candidates(symbol, market_state))
        return VPSelectionResult(tuple(candidates), states, len(candidates))

    def _resolve_price(self, symbol: str, price_map: dict[str, float] | None) -> float:
        if price_map:
            for key in (symbol, f"{symbol.upper()}1", symbol.upper()):
                if key in price_map and price_map[key] > 0:
                    return float(price_map[key])
        if self._provider is None or not hasattr(self._provider, "get_ltp"):
            return 0.0
        try:
            return float(self._provider.get_ltp(symbol))
        except Exception:
            return 0.0

    def _infer_volume_profile(self, symbol: str) -> VolumeProfile | None:
        if self._provider is None or not hasattr(self._provider, "get_volume_profile"):
            return None
        try:
            payload = self._provider.get_volume_profile(symbol)
        except Exception as exc:
            logger.debug("vp_provider_error", exc_info=exc)
            return None
        if not payload:
            return None
        poc = float(payload.get("poc", 0.0))
        vah = float(payload.get("vah", 0.0))
        val = float(payload.get("val", 0.0))
        lvns = tuple(float(x) for x in payload.get("lvns", []))
        hvns = tuple(float(x) for x in payload.get("hvns", []))
        total = float(payload.get("total_volume", 0.0))
        return VolumeProfile(symbol=symbol, poc=poc, vah=vah, val=val, lvns=lvns, hvns=hvns, total_volume=total)

    def _classify_market_state(self, price: float, vp: VolumeProfile) -> MarketState:
        vah_gap = abs(price - vp.vah)
        val_gap = abs(price - vp.val)
        market = "BALANCED" if (vp.val <= price <= vp.vah) else "IMBALANCED"
        rr = self._approx_rr(price, vp)
        return MarketState(
            market_state=market,
            price=price,
            poc=vp.poc,
            vah=vp.vah,
            val=vp.val,
            distance_to_vah=vah_gap,
            distance_to_val=val_gap,
            rr_ratio=rr,
        )

    def _approx_rr(self, price: float, vp: VolumeProfile) -> float:
        if price <= 0:
            return 0.0
        if price < vp.poc:
            risk = max(vp.poc - vp.val, 1e-9)
            reward = max(vp.poc - price, 1e-9)
            return reward / risk
        if price > vp.poc:
            risk = max(vp.vah - vp.poc, 1e-9)
            reward = max(price - vp.poc, 1e-9)
            return reward / risk
        return 1.0

    def _build_candidates(self, symbol: str, state: "MarketState") -> list[VPContractCandidate]:
        step = self.STRIKE_STEP.get(symbol, 50)
        underlying = symbol.replace("-", "")
        atm = int(round(state.price / step) * step)
        rr = max(0.0, state.rr_ratio)
        out: list[VPContractCandidate] = []
        if state.market_state == "IMBALANCED":
            if state.price > state.poc:
                strike = int((state.vah + step * 1.5) // step * step)
                out.append(
                    VPContractCandidate(
                        symbol=f"{underlying}{strike}CE",
                        underlying=symbol,
                        option_type="CALL",
                        strike=strike,
                        entry=state.price * 0.01,
                        stop=max(state.poc - 0.5 * step, 1.0),
                        target=max(state.vah + step, state.price + step * 0.8),
                        rr_ratio=rr,
                        reason="LONG at imbalance continuation",
                    )
                )
            else:
                strike = int((state.val - step * 1.5) // step * step)
                out.append(
                    VPContractCandidate(
                        symbol=f"{underlying}{strike}PE",
                        underlying=symbol,
                        option_type="PUT",
                        strike=max(strike, 0),
                        entry=state.price * 0.01,
                        stop=min(state.poc + 0.5 * step, state.price * 10),
                        target=min(state.val - step, max(state.price - step * 0.8, 1.0)),
                        rr_ratio=rr,
                        reason="SHORT at imbalance continuation",
                    )
                )
        else:
            strike = int(round(state.poc / step) * step)
            option = "PE" if state.price < state.poc else "CE"
            out.append(
                VPContractCandidate(
                    symbol=f"{underlying}{strike}{option}",
                    underlying=symbol,
                    option_type="CALL" if option == "CE" else "PUT",
                    strike=max(strike, 0),
                    entry=state.price * 0.01,
                    stop=max(0.5 * step, abs(state.price - state.poc) * 0.5),
                    target=state.poc,
                    rr_ratio=rr,
                    reason="VA fade into POC",
                )
            )
        return out
