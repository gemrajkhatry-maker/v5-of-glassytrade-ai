"""Exchange-specific configuration model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Any


@dataclass(frozen=True)
class ExchangeConfig:
    """Immutable configuration for a specific exchange context."""

    exchange: str
    underlyings: FrozenSet[str]
    default_symbol: str
    scanner_underlying: str
    scanner_underlyings: FrozenSet[str]
    aggression_sigma: float
    displacement_multiplier: float
    balance_ratio_threshold: float
    big_trade_multiplier: float
    big_trade_cluster_count: int
    big_trade_cluster_ticks: int
    warm_up_minutes: int
    cvd_block_threshold: float
    max_distance_to_level_ticks: float = 3.0
    llm_instruction: str = ""
    eia_symbols: FrozenSet[str] = frozenset()
    eia_suppression_minutes: int = 15
    tick_sizes: Dict[str, float] = field(default_factory=dict)
    lot_sizes: Dict[str, int] = field(default_factory=dict)
    point_values: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def for_exchange(cls, exchange: str) -> "ExchangeConfig":
        """Return defaults for a known exchange name."""
        ex = exchange.upper()
        if ex == "MCX":
            return cls._mcx_defaults()
        return cls._nse_defaults()

    @classmethod
    def from_dict(cls, exchange: str, data: Dict[str, Any]) -> "ExchangeConfig":
        """Build config from dict with fallback to exchange defaults."""
        base = cls.for_exchange(exchange)
        underlyings_raw = data.get("underlyings", [])
        underlyings = (
            frozenset(u.upper() for u in underlyings_raw)
            if underlyings_raw
            else base.underlyings
        )
        eia_raw = data.get("eia_symbols", [])
        eia_symbols = (
            frozenset(s.upper() for s in eia_raw)
            if eia_raw
            else base.eia_symbols
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
            llm_instruction=data.get("llm_instruction", base.llm_instruction),
            eia_symbols=eia_symbols,
            eia_suppression_minutes=int(
                data.get("eia_suppression_minutes", base.eia_suppression_minutes)
            ),
            tick_sizes=data.get("tick_sizes", base.tick_sizes),
            lot_sizes=data.get("lot_sizes", base.lot_sizes),
            point_values=data.get("point_values", base.point_values),
        )

    @classmethod
    def _nse_defaults(cls) -> "ExchangeConfig":
        return cls(
            exchange="NSE",
            underlyings=frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY"}),
            default_symbol="NIFTY",
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
            llm_instruction="Use NSE-specific session structure and options behavior.",
            eia_symbols=frozenset(),
            eia_suppression_minutes=0,
            tick_sizes={"NIFTY": 0.05, "BANKNIFTY": 0.05, "FINNIFTY": 0.05},
            lot_sizes={"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25},
            point_values={"NIFTY": 1.0, "BANKNIFTY": 1.0, "FINNIFTY": 1.0},
        )

    @classmethod
    def _mcx_defaults(cls) -> "ExchangeConfig":
        return cls(
            exchange="MCX",
            underlyings=frozenset(
                {
                    "CRUDEOIL",
                    "GOLD",
                    "SILVER",
                    "NATURALGAS",
                    "COPPER",
                    "ZINC",
                    "ALUMINIUM",
                    "LEAD",
                    "NICKEL",
                    "GOLDM",
                    "SILVERM",
                }
            ),
            default_symbol="CRUDEOIL",
            scanner_underlying="CRUDEOIL",
            scanner_underlyings=frozenset({"CRUDEOIL", "NATURALGAS", "GOLD", "SILVER"}),
            aggression_sigma=2.0,
            displacement_multiplier=1.2,
            balance_ratio_threshold=0.55,
            big_trade_multiplier=5.0,
            big_trade_cluster_count=3,
            big_trade_cluster_ticks=2,
            warm_up_minutes=15,
            cvd_block_threshold=50.0,
            max_distance_to_level_ticks=5.0,
            llm_instruction="Use MCX commodity session behavior and EIA suppression windows.",
            eia_symbols=frozenset({"NATURALGAS", "CRUDEOIL"}),
            eia_suppression_minutes=15,
            tick_sizes={"CRUDEOIL": 1.0, "NATURALGAS": 0.1, "GOLD": 1.0},
            lot_sizes={"CRUDEOIL": 100, "NATURALGAS": 1250, "GOLD": 100},
            point_values={"CRUDEOIL": 100.0, "NATURALGAS": 1250.0, "GOLD": 100.0},
        )

    def is_mcx(self) -> bool:
        return self.exchange == "MCX"

    def is_nse(self) -> bool:
        return self.exchange == "NSE"

    def is_underlying(self, symbol: str) -> bool:
        clean = (
            symbol.replace("NSE:", "")
            .replace("MCX:", "")
            .replace("-", " ")
            .strip()
        )
        return clean.split(" ")[0].upper() in self.underlyings

