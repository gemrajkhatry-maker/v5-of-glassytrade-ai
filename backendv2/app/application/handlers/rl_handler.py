"""Application handler wrapper for RL trainer lifecycle."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.domain.ai.rl.data_loader import load_from_csv
from app.domain.ai.rl.trainer import TrainingConfig, TrainingStatus, ValentiniTrainer


class RLHandler:
    """Simple wrapper over trainer instance."""

    def __init__(self) -> None:
        self._trainer: ValentiniTrainer | None = None

    @property
    def trainer(self) -> ValentiniTrainer:
        if self._trainer is None:
            self._trainer = ValentiniTrainer()
        return self._trainer

    def get_status(self) -> TrainingStatus:
        return self.trainer.status

    def ensure_data(self, data_source: str) -> list:
        data = load_from_csv(data_source)
        if not data:
            raise ValueError(f"No data found at: {data_source}")
        if len(data) < 300:
            raise ValueError(
                f"Insufficient RL data: {len(data)} rows. Minimum 300 candles required."
            )
        return data

    def start_training_with_data(
        self,
        data: list[Any],
        *,
        learning_rate: float,
        total_timesteps: int,
        initial_equity: float,
        max_risk_pct: float,
        tick_size: float,
        verbose: int = 1,
    ) -> TrainingStatus:
        self._trainer = ValentiniTrainer(
            TrainingConfig(
                total_timesteps=total_timesteps,
                learning_rate=learning_rate,
                initial_equity=initial_equity,
                max_risk_pct=max_risk_pct,
                tick_size=tick_size,
            )
        )
        return self._trainer.train(data=data, verbose=verbose)

    def predict(self, observation: np.ndarray, action_mask: np.ndarray) -> int:
        return self.trainer.predict(observation, action_mask)

