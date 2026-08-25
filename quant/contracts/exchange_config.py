"""Exchange-specific configuration — single source of truth for NSE/MCX differences.

This module eliminates scattered exchange-specific constants, duplicated
_MCX_UNDERLYINGS sets, and inline `if DEFAULT_EXCHANGE == "MCX"` branching
across the codebase.

Usage:
    config = ExchangeConfig.for_exchange("MCX")
    config.cvd_block_threshold   # 50
    config.warm_up_minutes       # 15
    config.underlyings           # frozenset({"CRUDEOIL", "GOLD", ...})
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import FrozenSet, Dict, Any, Optional

from quant.contracts.instrument_registry import DEFAULT_REGISTRY


def _tick_sizes_for(underlyings: FrozenSet[str]) -> Dict[str, float]:
    """Derive tick sizes from InstrumentRegistry — single source of truth,
    replacing what used to be a second hardcoded table here."""
    return {u: DEFAULT_REGISTRY.resolve(u).tick_size for u in underlyings}


def _lot_sizes_for(underlyings: FrozenSet[str]) -> Dict[str, int]:
    return {u: DEFAULT_REGISTRY.resolve(u).lot_size for u in underlyings}


def _freeze_limits_for(underlyings: FrozenSet[str]) -> Dict[str, int]:
    return {u: DEFAULT_REGISTRY.resolve(u).freeze_limit for u in underlyings}


@dataclass(frozen=True)
class ExchangeConfig:
    """Immutable configuration for a specific exchange/market.

    All exchange-specific behavior (thresholds, symbols, session rules)
    is encapsulated here. Domain services receive this via constructor
    injection instead of importing app.config directly.
    """

    exchange: str
    underlyings: FrozenSet[str]
    default_symbol: str
    scanner_underlying: str
    scanner_underlyings: FrozenSet[str]

    # AMT thresholds (exchange-specific defaults / YAML overrides)
    aggression_sigma: float
    displacement_multiplier: float
    balance_ratio_threshold: float

    # Big trade thresholds (FR-10-08)
    big_trade_multiplier: float
    big_trade_cluster_count: int
    big_trade_cluster_ticks: int

    # Time-based rules
    warm_up_minutes: int

    # CVD thresholds — exchange-specific due to volume differences
    cvd_block_threshold: float

    # Gate pipeline thresholds — exchange-specific
    max_distance_to_level_ticks: float = (
        3.0  # Max ticks from nearest key level for entry
    )

    # EIA calendar (MCX-specific)
    eia_symbols: FrozenSet[str] = frozenset()
    eia_suppression_minutes: int = 15

    # Instrument-level config — per underlying
    tick_sizes: Dict[str, float] = field(default_factory=dict)  # underlying → tick_size
    lot_sizes: Dict[str, int] = field(default_factory=dict)  # underlying → lot_size
    point_values: Dict[str, float] = field(
        default_factory=dict
    )  # underlying → point_value (INR per tick)
    freeze_limits: Dict[str, int] = field(
        default_factory=dict
    )  # underlying → exchange max order quantity per slice

    def extract_underlying(self, symbol_or_underlying: str) -> str:
        """Extract canonical underlying root from any contract format or symbol prefix.

        Handles:
          - Prefixed exchange symbols: 'NSE:NIFTY24AUG25500CE', 'MCX:CRUDEOIL24AUGFUT'
          - Space-delimited contracts: 'NIFTY 27 FEB 25500 CALL', 'CRUDEOILM 19 MAR 6000 CALL'
          - Hyphen-delimited contracts: 'BANKNIFTY-25700-PE', 'CRUDEOIL-I'
          - Compound roots: distinguishes 'CRUDEOILM' vs 'CRUDEOIL', 'GOLDM' vs 'GOLD',
            'MIDCPNIFTY' / 'FINNIFTY' vs 'NIFTY'.
        """
        if not symbol_or_underlying:
            return ""

        clean = (
            str(symbol_or_underlying)
            .upper()
            .replace("NSE:", "")
            .replace("NFO:", "")
            .replace("MCX:", "")
            .replace("BSE:", "")
            .strip()
        )
        spec = DEFAULT_REGISTRY.try_resolve(clean)
        if spec is not None:
            return spec.root
        if clean in self.underlyings:
            return clean

        for u in sorted(self.underlyings, key=len, reverse=True):
            if clean.startswith(u) and (len(clean) == len(u) or not clean[len(u)].isalpha()):
                return u

        token = re.split(r"[-_\s]+", clean)[0]
        for u in sorted(self.underlyings, key=len, reverse=True):
            if token.startswith(u) and (len(token) == len(u) or not token[len(u)].isalpha()):
                return u
        return token

    def get_freeze_limit(self, symbol_or_underlying: str) -> int:
        """Get exchange order quantity freeze limit. Defaults to 1800 for NSE, 10000 for MCX."""
        underlying = self.extract_underlying(symbol_or_underlying)
        return self.freeze_limits.get(underlying, 1800 if self.is_nse() else 10000)

    def get_tick_size(self, symbol_or_underlying: str) -> float:
        """Get tick size for a symbol or underlying. Defaults to 0.05."""
        underlying = self.extract_underlying(symbol_or_underlying)
        return self.tick_sizes.get(underlying, 0.05)

    def get_lot_size(self, symbol_or_underlying: str) -> int:
        """Get lot size for a symbol or underlying.

        Raises KeyError when the underlying is unknown — lot size is exchange
        metadata; an unknown underlying must be surfaced, not guessed.
        """
        underlying = self.extract_underlying(symbol_or_underlying)
        try:
            return self.lot_sizes[underlying]
        except KeyError:
            raise KeyError(
                f"No lot size configured for underlying {underlying!r} "
                f"(known: {sorted(self.lot_sizes)}). Lot size is exchange "
                "metadata — configure it or query the broker instrument master."
            ) from None

    def get_point_value(self, symbol_or_underlying: str) -> float:
        """Get point value (INR per tick) for a symbol or underlying. Defaults to 1.0."""
        underlying = self.extract_underlying(symbol_or_underlying)
        return self.point_values.get(underlying, 1.0)

    @classmethod
    def for_exchange(cls, exchange: str) -> ExchangeConfig:
        """Factory — returns the correct config for the given exchange.

        Args:
            exchange: "NSE" or "MCX" (case-insensitive).

        Returns:
            ExchangeConfig with exchange-appropriate defaults.
        """
        ex = exchange.upper()
        if ex == "MCX":
            return cls._mcx_defaults()
        return cls._nse_defaults()

    @classmethod
    def from_dict(cls, exchange: str, data: Dict[str, Any]) -> ExchangeConfig:
        """Build from a dictionary (e.g. parsed from market_config.yaml).

        Args:
            exchange: Exchange identifier.
            data: Dictionary of config values (partial — uses defaults for missing keys).

        Returns:
            ExchangeConfig with values from dict, falling back to exchange defaults.
        """
        base = cls.for_exchange(exchange)
        underlyings_raw = data.get("underlyings", [])
        underlyings = (
            frozenset(u.upper() for u in underlyings_raw)
            if underlyings_raw
            else base.underlyings
        )

        eia_raw = data.get("eia_symbols", [])
        eia_symbols = (
            frozenset(s.upper() for s in eia_raw) if eia_raw else base.eia_symbols
        )

        return cls(
            exchange=exchange.upper(),
            underlyings=underlyings,
            default_symbol=data.get("default_symbol", base.default_symbol),
            scanner_underlying=data.get("scanner_underlying", base.scanner_underlying),
            scanner_underlyings=underlyings,
            aggression_sigma=float(data.get("aggression_sigma", base.aggression_sigma)),
            displacement_multiplier=float(
                data.get("displacement_multiplier", base.displacement_multiplier)
            ),
            balance_ratio_threshold=float(
                data.get("balance_ratio_threshold", base.balance_ratio_threshold)
            ),
            big_trade_multiplier=float(
                data.get("big_trade_multiplier", base.big_trade_multiplier)
            ),
            big_trade_cluster_count=int(
                data.get("big_trade_cluster_count", base.big_trade_cluster_count)
            ),
            big_trade_cluster_ticks=int(
                data.get("big_trade_cluster_ticks", base.big_trade_cluster_ticks)
            ),
            warm_up_minutes=int(data.get("warm_up_minutes", base.warm_up_minutes)),
            cvd_block_threshold=float(
                data.get("cvd_block_threshold", base.cvd_block_threshold)
            ),
            max_distance_to_level_ticks=float(
                data.get(
                    "max_distance_to_level_ticks", base.max_distance_to_level_ticks
                )
            ),
            eia_symbols=eia_symbols,
            eia_suppression_minutes=int(
                data.get("eia_suppression_minutes", base.eia_suppression_minutes)
            ),
            tick_sizes=data.get("tick_sizes", base.tick_sizes),
            lot_sizes=data.get("lot_sizes", base.lot_sizes),
            point_values=data.get("point_values", base.point_values),
            freeze_limits=data.get("freeze_limits", base.freeze_limits),
        )

    @classmethod
    def _nse_defaults(cls) -> ExchangeConfig:
        """NSE Index Options defaults."""
        # SENSEX/BANKEX are BSE index options — they trade on BSE/F&O
        # sessions, but Dhan routes their chains through the same NFO-like
        # API surface this system uses for NSE index options, and their
        # session clock matches NSE (09:15–15:30 IST). Registering them
        # here keeps SymbolRegistry from falling through to the MCX
        # "safe default" (audit D-EXCH-07: the same class of bug as the
        # original MIDCPNIFTY misclassification).
        underlyings = DEFAULT_REGISTRY.nse_session_roots()
        return cls(
            exchange="NSE",
            underlyings=underlyings,
            default_symbol="NIFTY 27 FEB 25500 CALL",
            scanner_underlying="NIFTY",
            # Must track `underlyings` exactly — from_dict({}) derives
            # scanner_underlyings from the (possibly overridden) underlyings
            # set, so any classification-registered root left out here is
            # silently unscannable even though exchange_for() resolves it.
            scanner_underlyings=underlyings,
            aggression_sigma=2.5,
            displacement_multiplier=1.5,
            balance_ratio_threshold=0.70,
            big_trade_multiplier=3.0,
            big_trade_cluster_count=3,
            big_trade_cluster_ticks=2,
            warm_up_minutes=15,
            cvd_block_threshold=5000.0,
            max_distance_to_level_ticks=500.0,
            eia_symbols=frozenset(),
            eia_suppression_minutes=0,
            # tick/lot/freeze come from InstrumentRegistry (single source of
            # truth) instead of a second hardcoded table.
            tick_sizes=_tick_sizes_for(underlyings),
            lot_sizes=_lot_sizes_for(underlyings),
            point_values={u: 1.0 for u in underlyings},
            freeze_limits=_freeze_limits_for(underlyings),
        )

    @classmethod
    def _mcx_defaults(cls) -> ExchangeConfig:
        """MCX Commodity defaults."""
        underlyings = DEFAULT_REGISTRY.mcx_roots()
        return cls(
            exchange="MCX",
            underlyings=underlyings,
            default_symbol="CRUDEOIL 19 MAR 6000 CALL",
            scanner_underlying="CRUDEOIL",
            scanner_underlyings=frozenset(
                {"CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "GOLDM", "SILVERM"}
            ),
            aggression_sigma=2.0,
            displacement_multiplier=1.2,
            balance_ratio_threshold=0.55,
            big_trade_multiplier=5.0,
            big_trade_cluster_count=3,
            big_trade_cluster_ticks=2,
            warm_up_minutes=15,
            cvd_block_threshold=50.0,
            max_distance_to_level_ticks=5.0,
            eia_symbols=frozenset({"NATURALGAS", "CRUDEOIL"}),
            eia_suppression_minutes=15,
            # tick/lot come from InstrumentRegistry (single source of truth)
            # instead of a second hardcoded table.
            tick_sizes=_tick_sizes_for(underlyings),
            lot_sizes=_lot_sizes_for(underlyings),
            point_values={
                s.root: float(s.lot_size)
                for s in DEFAULT_REGISTRY.specs()
                if s.root in underlyings
            },
            freeze_limits=_freeze_limits_for(underlyings),
        )

    def is_mcx(self) -> bool:
        return self.exchange == "MCX"

    def is_nse(self) -> bool:
        return self.exchange == "NSE"

    def is_underlying(self, symbol: str) -> bool:
        """Check if a symbol corresponds to any of this exchange's underlyings."""
        root = self.extract_underlying(symbol)
        return root in self.underlyings
