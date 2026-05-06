"""Contract tests for RL parity and runtime observability."""

from __future__ import annotations

import csv
from dataclasses import fields
import tempfile

import os

import pytest

from app.domain.ai.rl.data_loader import generate_synthetic, load_from_csv
from app.domain.ai.rl.trainer import TrainingConfig, ValentiniTrainer
from app.domain.ai.rl.valentini_env import AMTObservation, ACTION_DIM, OBSERVATION_DIM, ValentiniAMTEnv
from app.api.routers.rl import PredictRequest


def test_valentini_env_observation_and_action_contract() -> None:
    data = generate_synthetic(count=260, seed=99)
    env = ValentiniAMTEnv(data=data)
    observation, _ = env.reset()

    assert len(fields(AMTObservation)) == OBSERVATION_DIM
    assert len(observation) == OBSERVATION_DIM
    assert env.action_masks().shape[0] == ACTION_DIM
    assert all(map(lambda v: isinstance(v, (int, float)) and v == v, observation))


def test_predict_request_contract() -> None:
    req = PredictRequest(
        observation=[0.0] * OBSERVATION_DIM,
        action_mask=[True] * ACTION_DIM,
    )
    assert len(req.observation) == OBSERVATION_DIM
    assert len(req.action_mask) == ACTION_DIM

    with pytest.raises(ValueError):
        PredictRequest(
            observation=[0.0] * (OBSERVATION_DIM - 1),
            action_mask=[True] * ACTION_DIM,
        )


def test_load_from_csv_parses_expected_ohlc_schema() -> None:
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "ohlc.csv")
        with open(path, "w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["time", "open", "high", "low", "close", "volume", "vwap", "taker_buy_volume", "delta"],
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "time": "2025-01-01T09:00:00+00:00",
                        "open": "100",
                        "high": "101",
                        "low": "99",
                        "close": "100.5",
                        "volume": "1200",
                        "vwap": "100.2",
                        "taker_buy_volume": "620",
                        "delta": "8",
                    },
                    {
                        "time": "2025-01-01T09:01:00+00:00",
                        "open": "100.5",
                        "high": "101.2",
                        "low": "100",
                        "close": "100.9",
                        "volume": "1400",
                        "vwap": "100.6",
                        "taker_buy_volume": "700",
                        "delta": "10",
                    },
                ]
            )

        rows = load_from_csv(path)
        assert len(rows) == 2
        assert float(rows[0].open) == 100.0
        assert float(rows[1].close) == 100.9


def test_train_status_and_predict_contract(tmp_path) -> None:
    pytest.importorskip("sb3_contrib")

    data = generate_synthetic(count=420, seed=101)
    trainer = ValentiniTrainer(
        TrainingConfig(
            total_timesteps=64,
            n_steps=16,
            batch_size=8,
            n_epochs=1,
            checkpoint_freq=32,
            model_dir=str(tmp_path / "rl_models"),
            log_dir=str(tmp_path / "rl_logs"),
        )
    )

    status = trainer.train(data=data, verbose=0)
    assert status.state == "completed"
    assert status.timesteps_done == status.total_timesteps
    assert status.model_ready
    assert status.model_loaded_at is not None
    assert status.model_path is not None
    assert os.path.exists(status.model_path)

    env = ValentiniAMTEnv(data=data)
    observation, _ = env.reset()
    action = trainer.predict(observation, env.action_masks())
    assert 0 <= action < ACTION_DIM
