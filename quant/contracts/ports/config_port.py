"""Domain ports for configuration access.

Application layer provides concrete implementations.
Domain layer depends only on these Protocol interfaces.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ISymbolConfig(Protocol):
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
