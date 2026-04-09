"""Domain ports for configuration access.

Application layer provides concrete implementations.
Domain layer depends only on these Protocol interfaces.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SymbolConfigPort(Protocol):
    """Port for symbol-specific trading configuration.

    This is the canonical location for the SymbolConfigLike protocol.
    Domain services should depend on this Protocol, not on infrastructure
    config models.
    """

    @property
    def tick_size(self) -> float:
        """Minimum price increment for the symbol."""
        ...

    @property
    def lot_size(self) -> int:
        """Number of units per lot."""
        ...

    @property
    def aggression_persistence_bars(self) -> int:
        """Number of bars for aggression persistence scoring."""
        ...

    @property
    def min_aggression_score(self) -> float:
        """Minimum aggression score to confirm entry."""
        ...

    @property
    def pyramid_aggression_score(self) -> float:
        """Aggression score threshold for pyramid entries."""
        ...


@runtime_checkable
class GlobalsPort(Protocol):
    """Port for accessing global trading constants.

    These values are loaded from config/base.yaml globals section.
    Domain should receive these via injection, not load directly.
    """

    # Volume Profile (FR-02)
    @property
    def lvn_threshold(self) -> float: ...
    @property
    def hvn_threshold(self) -> float: ...
    @property
    def value_area_pct(self) -> float: ...
    @property
    def lvn_smoothing(self) -> int: ...
    @property
    def lvn_min_persistence_bars(self) -> int: ...
    @property
    def lvn_removal_threshold(self) -> float: ...

    # Order Flow Metrics (FR-03)
    @property
    def cvd_slope_window(self) -> int: ...
    @property
    def cvd_strong_slope(self) -> float: ...

    # Market State (FR-04)
    @property
    def balance_ratio_threshold(self) -> float: ...
    @property
    def displacement_multiplier(self) -> float: ...

    # Risk Management (FR-10)
    @property
    def risk_per_trade_pct(self) -> float: ...
    @property
    def max_daily_loss_pct(self) -> float: ...
    @property
    def max_consecutive_losses(self) -> int: ...

    # Analysis Parameters
    @property
    def ib_minutes(self) -> int: ...
    @property
    def displacement_lookback(self) -> int: ...


@runtime_checkable
class ConfigPort(Protocol):
    """Main port for accessing trading configuration.

    Provides access to symbol configs, global constants, and settings.
    Application layer implements this with concrete config loader.
    """

    def get_symbol_config(self, symbol: str) -> SymbolConfigPort | None:
        """Get configuration for a specific trading symbol.

        Args:
            symbol: Trading symbol (e.g., "NIFTY", "BANKNIFTY").

        Returns:
            SymbolConfigPort if found, None otherwise.
        """
        ...

    def get_active_symbols(self) -> list[str]:
        """Get list of currently active trading symbols."""
        ...

    def get_global(self, key: str, default=None) -> float | int | str | None:
        """Get a global configuration value by key.

        Args:
            key: Configuration key (e.g., "lvn_threshold").
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        ...

    @property
    def globals(self) -> GlobalsPort:
        """Access to global constants."""
        ...
