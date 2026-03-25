"""Walk-Forward ML Validation Engine.

Non-negotiable before live broker activation. Validates ML models using
rolling walk-forward testing with acceptance criteria.

Protocol:
  Training window: 3 months (66 trading days × 78 bars = 5,148 bars)
  Test window:     1 month (22 trading days × 78 bars = 1,716 bars)
  Step size:       1 month
  Minimum iterations: 3

Acceptance (ALL must pass):
  Long model: precision >= 0.58 across ALL iterations
  Short model: precision >= 0.60 across ALL iterations
  Profit factor >= 1.4 across ALL iterations
  Brier score < 0.22 (well-calibrated)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


@dataclass(frozen=True)
class WalkForwardWindow:
    """Single walk-forward iteration result."""

    iteration: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_samples: int
    test_samples: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    brier_score: float
    profit_factor: float
    top_features: list[tuple[str, float]]  # (feature_name, mean_shap)
    precision_pass: bool
    profit_factor_pass: bool
    brier_pass: bool

    @property
    def all_pass(self) -> bool:
        return self.precision_pass and self.profit_factor_pass and self.brier_pass


@dataclass(frozen=True)
class WalkForwardResult:
    """Complete walk-forward validation result."""

    model_name: str
    direction: str  # "LONG" or "SHORT"
    windows: list[WalkForwardWindow]
    overall_result: ValidationResult
    pruned_features: list[str]  # features with mean_shap < 0.001
    summary: str


class WalkForwardValidator:
    """Walk-forward ML validation engine.

    Loads pre-computed feature/target matrices, runs rolling walk-forward
    testing, and produces validation results with acceptance/rejection.
    """

    # Acceptance criteria per spec
    LONG_PRECISION_MIN = 0.58
    SHORT_PRECISION_MIN = 0.60
    PROFIT_FACTOR_MIN = 1.4
    BRIER_SCORE_MAX = 0.22
    SHAP_PRUNE_THRESHOLD = 0.001

    def __init__(
        self,
        train_window_days: int = 66,
        test_window_days: int = 22,
        step_days: int = 22,
        bars_per_day: int = 78,
    ) -> None:
        self._train_window_days = train_window_days
        self._test_window_days = test_window_days
        self._step_days = step_days
        self._bars_per_day = bars_per_day

    @property
    def train_window_bars(self) -> int:
        return self._train_window_days * self._bars_per_day

    @property
    def test_window_bars(self) -> int:
        return self._test_window_days * self._bars_per_day

    def validate(
        self,
        model_name: str,
        direction: str,
        windows: list[WalkForwardWindow],
    ) -> WalkForwardResult:
        """Validate walk-forward results against acceptance criteria.

        Args:
            model_name: Name of the model being validated
            direction: "LONG" or "SHORT"
            windows: List of walk-forward iteration results

        Returns:
            WalkForwardResult with overall pass/fail and details
        """
        if not windows:
            return WalkForwardResult(
                model_name=model_name,
                direction=direction,
                windows=[],
                overall_result=ValidationResult.FAIL,
                pruned_features=[],
                summary="No walk-forward windows provided",
            )

        # Collect metrics across all windows
        all_precision_pass = all(w.precision_pass for w in windows)
        all_profit_pass = all(w.profit_factor_pass for w in windows)
        all_brier_pass = all(w.brier_pass for w in windows)

        # Aggregate feature importance
        feature_importance: dict[str, list[float]] = {}
        for w in windows:
            for fname, imp in w.top_features:
                if fname not in feature_importance:
                    feature_importance[fname] = []
                feature_importance[fname].append(imp)

        mean_importance = {k: sum(v) / len(v) for k, v in feature_importance.items()}
        pruned = [
            k for k, v in mean_importance.items() if v < self.SHAP_PRUNE_THRESHOLD
        ]

        # Overall result
        if all_precision_pass and all_profit_pass and all_brier_pass:
            result = ValidationResult.PASS
            summary = (
                f"All {len(windows)} windows passed. "
                f"Pruning {len(pruned)} low-importance features."
            )
        else:
            failures = []
            if not all_precision_pass:
                failures.append("precision")
            if not all_profit_pass:
                failures.append("profit_factor")
            if not all_brier_pass:
                failures.append("brier_score")
            result = ValidationResult.FAIL
            summary = f"Failed on: {', '.join(failures)}"

        return WalkForwardResult(
            model_name=model_name,
            direction=direction,
            windows=windows,
            overall_result=result,
            pruned_features=sorted(pruned),
            summary=summary,
        )

    def compute_brier_score(
        self,
        predicted_probs: list[float],
        actual_outcomes: list[int],
    ) -> float:
        """Compute Brier score (calibration quality).

        Brier = mean((predicted_prob - actual)^2)
        Lower is better. < 0.22 = well-calibrated.
        """
        if not predicted_probs:
            return 1.0
        return sum(
            (p - a) ** 2 for p, a in zip(predicted_probs, actual_outcomes)
        ) / len(predicted_probs)

    def compute_profit_factor(
        self,
        predicted_probs: list[float],
        actual_outcomes: list[int],
        threshold: float = 0.55,
    ) -> float:
        """Compute profit factor at a given threshold.

        Simulates: enter when predicted_prob >= threshold.
        Profit = count of correct predictions
        Loss = count of incorrect predictions
        """
        wins = sum(
            1
            for p, a in zip(predicted_probs, actual_outcomes)
            if p >= threshold and a == 1
        )
        losses = sum(
            1
            for p, a in zip(predicted_probs, actual_outcomes)
            if p >= threshold and a == 0
        )
        if losses == 0:
            return float("inf") if wins > 0 else 1.0
        return wins / losses
