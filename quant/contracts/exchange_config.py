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
        if clean in self.underlyings:
            return clean

        # Match known underlyings sorted by descending length so compound roots match first
        for u in sorted(self.underlyings, key=len, reverse=True):
            if clean.startswith(u):
                return u

        # Fallback to delimiter tokenization
        token = re.split(r"[-_\s]+", clean)[0]
        for u in sorted(self.underlyings, key=len, reverse=True):
            if token.startswith(u):
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
        return cls(
            exchange="NSE",
            underlyings=frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY"}),
            default_symbol="NIFTY 27 FEB 25500 CALL",
            scanner_underlying="NIFTY",
            scanner_underlyings=frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY"}),
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
            tick_sizes={
                "NIFTY": 0.05,
                "BANKNIFTY": 0.05,
                "FINNIFTY": 0.05,
                "MIDCPNIFTY": 0.05,
            },
            lot_sizes={
                # Current NSE series (exchange-authoritative, Aug 2026):
                # NIFTY=65, BANKNIFTY=30, FINNIFTY=60, MIDCPNIFTY=120.
                "NIFTY": 65,
                "BANKNIFTY": 30,
                "FINNIFTY": 60,
                "MIDCPNIFTY": 120,
            },
            point_values={
                "NIFTY": 1.0,
                "BANKNIFTY": 1.0,
                "FINNIFTY": 1.0,
                "MIDCPNIFTY": 1.0,
            },
            freeze_limits={
                "NIFTY": 1800,
                "BANKNIFTY": 900,
                "FINNIFTY": 1800,
                "MIDCPNIFTY": 4200,
            },
        )

    @classmethod
    def _mcx_defaults(cls) -> ExchangeConfig:
        """MCX Commodity defaults."""
        return cls(
            exchange="MCX",
            underlyings=frozenset(
                {
                    "CRUDEOIL",
                    "GOLD",
                    "SILVER",
                    "NATURALGAS",
                    "COPPER",
                    "GOLDM",
                    "SILVERM",
                    "CRUDEOILM",
                    "ZINC",
                    "ALUMINIUM",
                    "LEAD",
                    "NICKEL",
                    "COTTONCANDY",
                }
            ),
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
            tick_sizes={
                "CRUDEOIL": 1.0,
                "NATURALGAS": 0.1,
                "GOLD": 1.0,
                "GOLDM": 1.0,
                "SILVER": 1.0,
                "SILVERM": 1.0,
                "COPPER": 0.05,
                "ZINC": 0.05,
                "ALUMINIUM": 0.05,
                "LEAD": 0.05,
                "NICKEL": 1.0,
            },
            lot_sizes={
                "CRUDEOIL": 100,
                "NATURALGAS": 1250,
                "GOLD": 100,
                "GOLDM": 100,
                "SILVER": 30,
                "SILVERM": 5,
                "COPPER": 2500,
                "ZINC": 5000,
                "ALUMINIUM": 5000,
                "LEAD": 5000,
                "NICKEL": 1500,
            },
            point_values={
                "CRUDEOIL": 100.0,
                "NATURALGAS": 1250.0,
                "GOLD": 100.0,
                "GOLDM": 100.0,
                "SILVER": 30.0,
                "SILVERM": 5.0,
                "COPPER": 2500.0,
                "ZINC": 5000.0,
                "ALUMINIUM": 5000.0,
                "LEAD": 5000.0,
                "NICKEL": 1500.0,
            },
            freeze_limits={
                "CRUDEOIL": 10000,
                "NATURALGAS": 100000,
                "GOLD": 10000,
                "SILVER": 10000,
                "GOLDM": 10000,
                "SILVERM": 10000,
            },
        )

    def is_mcx(self) -> bool:
        return self.exchange == "MCX"

    def is_nse(self) -> bool:
        return self.exchange == "NSE"

    def is_underlying(self, symbol: str) -> bool:
        """Check if a symbol corresponds to any of this exchange's underlyings."""
        root = self.extract_underlying(symbol)
        return root in self.underlyings
