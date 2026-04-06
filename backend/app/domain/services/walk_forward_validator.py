"""Walk-Forward Validator — Stub.

Planned feature: Walk-forward validation for trading strategies,
rolling train/test splits to evaluate out-of-sample performance.

Status: Stub — types defined but not fully implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class WalkForwardWindow:
    """A single walk-forward train/test window."""
    train_start: str = ""
    train_end: str = ""
    test_start: str = ""
    test_end: str = ""
    train_data: list = field(default_factory=list)
    test_data: list = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of walk-forward validation."""
    windows: int = 0
    mean_return: float = 0.0
    std_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    is_valid: bool = False
    detail: str = ""


class WalkForwardValidator:
    """Walk-forward validation engine.

    Stub implementation — generates empty results.
    """

    def generate_windows(
        self,
        data: list,
        train_size: int = 100,
        test_size: int = 20,
        step: int = 10,
    ) -> list[WalkForwardWindow]:
        """Generate walk-forward train/test windows."""
        return []

    def validate(
        self,
        strategy: Any,
        data: list,
        train_size: int = 100,
        test_size: int = 20,
    ) -> ValidationResult:
        """Run walk-forward validation on a strategy."""
        return ValidationResult()
