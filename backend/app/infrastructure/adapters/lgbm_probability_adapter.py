"""LightGBM adapter for first-passage probability inference."""

from __future__ import annotations

import logging
import os
import pickle

import numpy as np

from app.domain.ports.probability_inference import (
    ProbabilityEstimate,
    IProbabilityInference,
)
from app.domain.probability.features import (
    FEATURE_NAMES,
    PROBABILITY_FEATURE_SCHEMA_VERSION,
    active_model_features,
)

logger = logging.getLogger(__name__)


class LGBMProbabilityAdapter(IProbabilityInference):
    """Loads pre-trained LightGBM models and predicts first-passage probabilities."""

    def __init__(self, model_dir: str) -> None:
        self._model_dir = model_dir
        self._model_long = None
        self._model_short = None
        self._mfe_long = None
        self._mfe_short = None
        self._calibrators: dict[str, object] = {}  # direction -> fitted LogisticRegression
        self._ready = False
        self._feature_names: tuple[str, ...] = FEATURE_NAMES
        self._schema_version = PROBABILITY_FEATURE_SCHEMA_VERSION
        self._load_models()

    def _load_models(self) -> None:
        long_path = os.path.join(self._model_dir, "fp_long.txt")
        short_path = os.path.join(self._model_dir, "fp_short.txt")

        if not os.path.exists(long_path) or not os.path.exists(short_path):
            logger.warning(
                "Probability models not found at %s — adapter will return neutral estimates",
                self._model_dir,
            )
            return

        try:
            import lightgbm as lgb

            self._model_long = lgb.Booster(model_file=long_path)
            self._model_short = lgb.Booster(model_file=short_path)
            self._feature_names = tuple(self._model_long.feature_name()) or FEATURE_NAMES
            self._ready = True
            logger.info("Loaded probability models from %s", self._model_dir)
            if tuple(self._feature_names) != FEATURE_NAMES:
                logger.warning(
                    "Probability feature schema mismatch: runtime=%s model=%s",
                    list(FEATURE_NAMES),
                    list(self._feature_names),
                )

            # Optional Platt scaling calibrators
            self._load_calibrators()

            # Optional MFE quantile models for dynamic TP
            mfe_long_path = os.path.join(self._model_dir, "mfe_long_q50.txt")
            mfe_short_path = os.path.join(self._model_dir, "mfe_short_q50.txt")
            if os.path.exists(mfe_long_path) and os.path.exists(mfe_short_path):
                self._mfe_long = lgb.Booster(model_file=mfe_long_path)
                self._mfe_short = lgb.Booster(model_file=mfe_short_path)
                logger.info("Loaded MFE quantile models for dynamic TP")
        except Exception as e:
            logger.error("Failed to load probability models: %s", e)

    def _load_calibrators(self) -> None:
        """Load Platt scaling calibrators if available."""
        for direction, filename in [("long", "fp_long_calibrator.pkl"), ("short", "fp_short_calibrator.pkl")]:
            cal_path = os.path.join(self._model_dir, filename)
            if os.path.exists(cal_path):
                try:
                    with open(cal_path, "rb") as f:
                        self._calibrators[direction] = pickle.load(f)
                    logger.info("Loaded Platt calibrator for %s from %s", direction, cal_path)
                except Exception as e:
                    logger.warning("Failed to load calibrator %s: %s", cal_path, e)

    def _calibrate(self, raw_prob: float, direction: str) -> float:
        """Apply Platt scaling if calibrator is available."""
        cal = self._calibrators.get(direction)
        if cal is None:
            return raw_prob
        try:
            return float(cal.predict_proba(np.array([[raw_prob]]))[0, 1])
        except (TypeError, ValueError):
            return raw_prob

    @staticmethod
    def train_calibrator(y_true: list, y_pred_proba: list, output_path: str) -> None:
        """Train and save a Platt scaling calibrator from historical predictions.

        Args:
            y_true: Binary ground-truth labels (1=target hit, 0=stop hit).
            y_pred_proba: Raw predicted probabilities from the LightGBM model.
            output_path: File path to write the pickled LogisticRegression calibrator.
        """
        from sklearn.linear_model import LogisticRegression

        X = np.array(y_pred_proba).reshape(-1, 1)
        y = np.array(y_true)
        lr = LogisticRegression()
        lr.fit(X, y)
        with open(output_path, "wb") as f:
            pickle.dump(lr, f)
        logger.info("Saved Platt calibrator to %s (%d samples)", output_path, len(y_true))

    def estimate(self, features: dict[str, float]) -> ProbabilityEstimate:
        if not self._ready:
            return ProbabilityEstimate(
                p_long_target=0.5,
                p_short_target=0.5,
                expected_mfe_long=0.0,
                expected_mfe_short=0.0,
            )

        feature_payload = active_model_features(features)
        arr = np.array([[feature_payload.get(name, 0.0) for name in self._feature_names]])

        p_long_raw = float(self._model_long.predict(arr)[0])
        p_short_raw = float(self._model_short.predict(arr)[0])

        # Clamp to [0, 1]
        p_long_raw = max(0.0, min(1.0, p_long_raw))
        p_short_raw = max(0.0, min(1.0, p_short_raw))

        # Apply Platt scaling calibration (identity if no calibrator loaded)
        p_long = self._calibrate(p_long_raw, "long")
        p_short = self._calibrate(p_short_raw, "short")

        # MFE predictions for dynamic TP
        mfe_long_val = 0.0
        mfe_short_val = 0.0
        if self._mfe_long is not None and self._mfe_short is not None:
            mfe_long_val = max(0.0, float(self._mfe_long.predict(arr)[0]))
            mfe_short_val = max(0.0, float(self._mfe_short.predict(arr)[0]))

        return ProbabilityEstimate(
            p_long_target=p_long,
            p_short_target=p_short,
            expected_mfe_long=mfe_long_val,
            expected_mfe_short=mfe_short_val,
            calibrated=bool(self._calibrators),
        )

    def is_ready(self) -> bool:
        return self._ready

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    @property
    def schema_version(self) -> str:
        return self._schema_version
