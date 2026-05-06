"""LightGBM adapter for probability inference in backendv2."""

from __future__ import annotations

import logging
import os
import pickle

import numpy as np

from app.domain.shared.port import IProbabilityInference

logger = logging.getLogger(__name__)

# Keep feature schema visible to runtime and tests that introspect adapter state.
PROBABILITY_FEATURE_SCHEMA_VERSION = "fp-42-v1"

try:
    from app.domain.probability.features import (  # type: ignore
        FEATURE_NAMES as _UPSTREAM_FEATURE_NAMES,
        active_model_features,
    )
except Exception:
    # Backend v2 migration may not yet contain v1 probability feature module.
    _UPSTREAM_FEATURE_NAMES: tuple[str, ...] = (
        "close_vs_poc_pct",
        "close_vs_vah_pct",
        "close_vs_val_pct",
        "close_vs_vwap_pct",
        "atr_5",
        "atr_20",
        "atr_ratio",
        "bar_range_pct",
        "body_pct",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "close_position_in_range",
        "delta_normalized",
        "cvd_slope",
        "cvd_divergence_flag",
        "aggression",
        "volume_vs_ema20",
        "delta_acceleration",
        "cumulative_delta_3bar",
        "aggressive_print_imbalance",
        "profile_shape_encoded",
        "balance_ratio",
        "va_width_pct",
        "market_state_encoded",
        "hvn_count",
        "nearest_lvn_distance_pct",
        "bid_ask_spread_bps",
        "book_imbalance_l1",
        "book_imbalance_l5",
        "bid_depth_total",
        "ask_depth_total",
        "book_pressure_ratio",
        "minutes_since_open",
        "session_flag",
        "day_of_week",
        "bars_since_last_displacement",
        "oi_change_pct",
        "option_type_flag",
        "underlying_return_5bar",
        "moneyness_pct",
        "dte_normalized",
        "oi_volume_ratio",
    )

    def active_model_features(features: dict[str, float]) -> dict[str, float]:
        """Return ordered model features when upstream helper is unavailable."""
        return {name: float(features.get(name, 0.0)) for name in _UPSTREAM_FEATURE_NAMES}


class LGBMProbabilityAdapter(IProbabilityInference):
    """Loads pre-trained LightGBM models and emits probability estimates."""

    def __init__(self, model_dir: str) -> None:
        self._model_dir = model_dir
        self._model_long = None
        self._model_short = None
        self._mfe_long = None
        self._mfe_short = None
        self._calibrators: dict[str, object] = {}
        self._ready = False
        self._feature_names: tuple[str, ...] = _UPSTREAM_FEATURE_NAMES
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
            self._feature_names = tuple(self._model_long.feature_name()) or _UPSTREAM_FEATURE_NAMES
            self._ready = True
            if tuple(self._feature_names) != _UPSTREAM_FEATURE_NAMES:
                logger.warning(
                    "Probability feature schema mismatch: runtime=%s model=%s",
                    list(_UPSTREAM_FEATURE_NAMES),
                    list(self._feature_names),
                )

            self._load_calibrators()

            mfe_long_path = os.path.join(self._model_dir, "mfe_long_q50.txt")
            mfe_short_path = os.path.join(self._model_dir, "mfe_short_q50.txt")
            if os.path.exists(mfe_long_path) and os.path.exists(mfe_short_path):
                self._mfe_long = lgb.Booster(model_file=mfe_long_path)
                self._mfe_short = lgb.Booster(model_file=mfe_short_path)
                logger.info("Loaded MFE quantile models for dynamic TP")
        except Exception as e:
            logger.error("Failed to load probability models: %s", e)

    def _load_calibrators(self) -> None:
        for direction, filename in (
            ("long", "fp_long_calibrator.pkl"),
            ("short", "fp_short_calibrator.pkl"),
        ):
            cal_path = os.path.join(self._model_dir, filename)
            if os.path.exists(cal_path):
                try:
                    with open(cal_path, "rb") as f:
                        self._calibrators[direction] = pickle.load(f)
                    logger.info("Loaded calibrator for %s from %s", direction, cal_path)
                except Exception as e:
                    logger.warning("Failed to load calibrator %s: %s", cal_path, e)

    def _calibrate(self, raw_prob: float, direction: str) -> float:
        calibrator = self._calibrators.get(direction)
        if calibrator is None:
            return raw_prob
        try:
            return float(calibrator.predict_proba(np.array([[raw_prob]]))[0, 1])
        except (TypeError, ValueError):
            return raw_prob

    @staticmethod
    def _confidence_from_probability(p: float) -> str:
        p = max(0.0, min(1.0, float(p)))
        if p >= 0.67:
            return "High"
        if p >= 0.55:
            return "Medium"
        return "Low"

    def predict(self, features: dict) -> dict[str, object]:
        if not self._ready or self._model_long is None or self._model_short is None:
            return {
                "direction": "FLAT",
                "confidence": "Low",
                "probability": 0.5,
                "p_long_target": 0.5,
                "p_short_target": 0.5,
                "expected_mfe_long": 0.0,
                "expected_mfe_short": 0.0,
                "calibrated": False,
                "schema_version": self._schema_version,
            }

        feature_payload = active_model_features(features)
        arr = np.array([[feature_payload.get(name, 0.0) for name in self._feature_names]])
        p_long_raw = float(self._model_long.predict(arr)[0])
        p_short_raw = float(self._model_short.predict(arr)[0])
        p_long = max(0.0, min(1.0, p_long_raw))
        p_short = max(0.0, min(1.0, p_short_raw))
        p_long = self._calibrate(p_long, "long")
        p_short = self._calibrate(p_short, "short")
        max_prob = max(p_long, p_short)

        expected_long = 0.0
        expected_short = 0.0
        if self._mfe_long is not None and self._mfe_short is not None:
            expected_long = max(0.0, float(self._mfe_long.predict(arr)[0]))
            expected_short = max(0.0, float(self._mfe_short.predict(arr)[0]))

        direction = "LONG" if p_long >= p_short else "SHORT"
        if abs(p_long - p_short) < 0.01:
            direction = "FLAT"

        return {
            "direction": direction,
            "confidence": self._confidence_from_probability(max_prob),
            "probability": float(max_prob),
            "p_long_target": float(p_long),
            "p_short_target": float(p_short),
            "expected_mfe_long": float(expected_long),
            "expected_mfe_short": float(expected_short),
            "calibrated": bool(self._calibrators),
            "schema_version": self._schema_version,
        }

    def is_ready(self) -> bool:
        return self._ready

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    @property
    def schema_version(self) -> str:
        return self._schema_version
