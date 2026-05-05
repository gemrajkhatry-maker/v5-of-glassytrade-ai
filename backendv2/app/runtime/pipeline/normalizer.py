"""Tick normalizer stage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional
import logging

from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import SequencedTick, NormalizedTick

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SymbolProfile:
    symbol: str
    tick_size: float = 0.05
    lot_size: int = 1
    multiplier: float = 1.0


class TickNormalizer:
    """Normalize sequenced raw ticks into canonical fields."""

    def __init__(
        self,
        symbol_profiles: dict[str, _SymbolProfile] | None = None,
        symbols: Iterable[str] | None = None,
        strict_symbol_mode: bool = False,
    ):
        self._profiles: dict[str, _SymbolProfile] = {
            p.symbol: p for p in (symbol_profiles or {}).values()
        }
        self._allowed_symbols = set(symbols or [])
        self._strict_symbol_mode = strict_symbol_mode
        self._metrics = StageMetrics(stage_name="TickNormalizer")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    @property
    def known_symbols(self) -> set[str]:
        return set(self._profiles.keys())

    @property
    def profiles(self) -> list[_SymbolProfile]:
        return list(self._profiles.values())

    def _ensure_profile(self, symbol: str) -> _SymbolProfile:
        profile = self._profiles.get(symbol)
        if self._strict_symbol_mode:
            if self._allowed_symbols and symbol not in self._allowed_symbols:
                raise ValueError(f"Unknown symbol '{symbol}' in normalizer strict mode")
            if not self._allowed_symbols:
                if profile is None:
                    raise ValueError(f"Unknown symbol '{symbol}' in normalizer strict mode")
            if profile is not None:
                return profile
        if profile is not None:
            return profile
        profile = _SymbolProfile(symbol=symbol)
        self._profiles[symbol] = profile
        return profile

    def register_symbol(self, symbol: str, profile: _SymbolProfile | None = None) -> None:
        if not symbol:
            return
        self._profiles[symbol] = profile or _SymbolProfile(symbol=symbol)

    def register_symbols(self, symbols: Iterable[str]) -> None:
        for symbol in symbols:
            self.register_symbol(symbol)

    def unregister_symbol(self, symbol: str) -> None:
        self._profiles.pop(symbol, None)

    def snapshot(self) -> dict:
        return {
            "profiles": {
                symbol: {
                    "tick_size": profile.tick_size,
                    "lot_size": profile.lot_size,
                    "multiplier": profile.multiplier,
                }
                for symbol, profile in self._profiles.items()
            },
            "allowed_symbols": sorted(self._allowed_symbols),
            "strict_symbol_mode": self._strict_symbol_mode,
        }

    def restore(self, payload: dict[str, object]) -> None:
        if not payload:
            return
        self._allowed_symbols = set(payload.get("allowed_symbols", []))
        self._strict_symbol_mode = bool(payload.get("strict_symbol_mode", self._strict_symbol_mode))
        profiles = payload.get("profiles") or {}
        restored: dict[str, _SymbolProfile] = {}
        for symbol, raw in profiles.items():
            if not isinstance(raw, dict):
                continue
            restored[symbol] = _SymbolProfile(
                symbol=symbol,
                tick_size=float(raw.get("tick_size", 0.05)),
                lot_size=int(raw.get("lot_size", 1)),
                multiplier=float(raw.get("multiplier", 1.0)),
            )
        if restored:
            self._profiles = restored

    def set_allowed_symbols(self, symbols: Iterable[str]) -> None:
        self._allowed_symbols = set(symbols)

    def process(self, event: SequencedTick) -> Optional[NormalizedTick]:
        if event is None or event.tick.price < 0:
            self._metrics.record_error()
            return None
        try:
            profile = self._ensure_profile(event.tick.symbol)
            bid = event.tick.bid if event.tick.bid > 0 else event.tick.price
            ask = event.tick.ask if event.tick.ask > 0 else event.tick.price
            norm = NormalizedTick(
                symbol=event.tick.symbol,
                price=float(event.tick.price),
                volume=float(event.tick.volume),
                timestamp=float(event.tick.timestamp),
                bid=float(bid),
                ask=float(ask),
                bid_volume=float(event.tick.bid_volume),
                ask_volume=float(event.tick.ask_volume),
                sequence=event.sequence,
                tick_size=profile.tick_size,
                lot_size=profile.lot_size,
                multiplier=profile.multiplier,
            )
            self._metrics.record(0)
            return norm
        except Exception:
            self._metrics.record_error()
            logger.exception("Failed to normalize tick")
            return None

    def warmup(self) -> None:
        self._metrics.reset()

    def teardown(self) -> None:
        self._metrics.reset()

    def reset(self) -> None:
        self._profiles = {}
        self._metrics.reset()
