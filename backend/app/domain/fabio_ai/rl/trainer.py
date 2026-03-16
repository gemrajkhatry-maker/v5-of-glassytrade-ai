"""PPO Trainer — Valentini AMT RL training pipeline.

Uses sb3-contrib MaskablePPO to train the Valentini AMT agent with
action masking, Sharpe Ratio objective, and configurable hyperparameters.
"""

from __future__ import annotations

import os
import time
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Any
from pathlib import Path

import numpy as np
from stable_baselines3.common.callbacks import BaseCallback

from app.domain.trading.models.value_objects import OHLC
from app.domain.fabio_ai.rl.valentini_env import ValentiniAMTEnv
from app.domain.fabio_ai.rl.data_loader import split_data


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TrainingConfig:
    """Hyperparameters for PPO training."""
    total_timesteps: int = 100_000
    learning_rate: float = 3e-4
    n_steps: int = 2048
    batch_size: int = 64
    n_epochs: int = 10
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    ent_coef: float = 0.01
    max_risk_pct: float = 0.5
    initial_equity: float = 100_000.0
    tick_size: float = 0.01
    max_bars_in_trade: int = 50
    checkpoint_freq: int = 10_000
    log_dir: str = "rl_logs"
    model_dir: str = "rl_models"


@dataclass
class TrainingStatus:
    """Current status of a training run."""
    state: str = "idle"          # "idle" | "training" | "completed" | "error"
    timesteps_done: int = 0
    total_timesteps: int = 0
    episode_count: int = 0
    mean_reward: float = 0.0
    mean_sharpe: float = 0.0
    total_trades: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    model_path: str | None = None


# ---------------------------------------------------------------------------
# Sharpe Ratio Callback
# ---------------------------------------------------------------------------

class SharpeCallback(BaseCallback):
    """Custom callback that tracks episode rewards and computes rolling Sharpe."""

    def __init__(self, check_freq: int = 1000, verbose: int = 0):
        super().__init__(verbose)
        self.check_freq = check_freq
        self.episode_rewards: list[float] = []
        self.sharpe_history: list[float] = []

    def _on_step(self) -> bool:
        # Collect episode rewards from info
        infos = self.locals.get("infos", [])
        for info in infos:
            if "episode" in info:
                self.episode_rewards.append(info["episode"]["r"])

        if self.n_calls % self.check_freq == 0 and len(self.episode_rewards) > 10:
            recent = self.episode_rewards[-50:]
            mean_r = np.mean(recent)
            std_r = np.std(recent) + 1e-8
            sharpe = mean_r / std_r
            self.sharpe_history.append(float(sharpe))
            if self.verbose > 0:
                print(f"[Sharpe] Step {self.n_calls}: "
                      f"Mean Reward={mean_r:.2f}, Sharpe={sharpe:.2f}")
        return True


# ---------------------------------------------------------------------------
# Checkpoint Callback
# ---------------------------------------------------------------------------

class CheckpointCallback(BaseCallback):
    """Save model checkpoints at regular intervals."""

    def __init__(self, save_freq: int, save_path: str, verbose: int = 0):
        super().__init__(verbose)
        self.save_freq = save_freq
        self.save_path = save_path
        os.makedirs(save_path, exist_ok=True)

    def _on_step(self) -> bool:
        if self.n_calls % self.save_freq == 0:
            path = os.path.join(self.save_path, f"checkpoint_{self.n_calls}")
            self.model.save(path)
            if self.verbose > 0:
                print(f"[Checkpoint] Saved to {path}")
        return True


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------

class ValentiniTrainer:
    """PPO training pipeline for the Valentini AMT environment."""

    def __init__(self, config: TrainingConfig | None = None) -> None:
        self.config = config or TrainingConfig()
        self._status = TrainingStatus()
        self._model = None

    @property
    def status(self) -> TrainingStatus:
        return self._status

    def train(
        self,
        data: list[OHLC] | None = None,
        verbose: int = 1,
    ) -> TrainingStatus:
        """Run the full training pipeline.

        Requires real market data — no synthetic fallback.
        """
        from sb3_contrib import MaskablePPO

        cfg = self.config
        self._status = TrainingStatus(
            state="training",
            total_timesteps=cfg.total_timesteps,
        )
        start_time = time.time()

        try:
            # 1. Prepare data — real market data required
            if data is None:
                raise ValueError("Real market data (list[OHLC]) is required for RL training. No synthetic fallback.")

            split = split_data(data)

            # 2. Create environment
            env = ValentiniAMTEnv(
                data=split.train,
                initial_equity=cfg.initial_equity,
                max_risk_pct=cfg.max_risk_pct,
                tick_size=cfg.tick_size,
                max_bars_in_trade=cfg.max_bars_in_trade,
            )

            # 3. Create PPO model
            os.makedirs(cfg.log_dir, exist_ok=True)
            os.makedirs(cfg.model_dir, exist_ok=True)

            model = MaskablePPO(
                "MlpPolicy",
                env,
                learning_rate=cfg.learning_rate,
                n_steps=cfg.n_steps,
                batch_size=cfg.batch_size,
                n_epochs=cfg.n_epochs,
                gamma=cfg.gamma,
                gae_lambda=cfg.gae_lambda,
                clip_range=cfg.clip_range,
                ent_coef=cfg.ent_coef,
                verbose=verbose,
                tensorboard_log=cfg.log_dir,
            )

            # 4. Callbacks
            sharpe_cb = SharpeCallback(check_freq=1000, verbose=verbose)
            checkpoint_cb = CheckpointCallback(
                save_freq=cfg.checkpoint_freq,
                save_path=cfg.model_dir,
                verbose=verbose,
            )

            # 5. Train
            model.learn(
                total_timesteps=cfg.total_timesteps,
                callback=[sharpe_cb, checkpoint_cb],
                progress_bar=False,
            )

            # 6. Save final model
            final_path = os.path.join(cfg.model_dir, "valentini_final")
            model.save(final_path)

            # 7. Evaluate on validation set
            val_env = ValentiniAMTEnv(
                data=split.validation,
                initial_equity=cfg.initial_equity,
                max_risk_pct=cfg.max_risk_pct,
                tick_size=cfg.tick_size,
            )
            val_rewards = self._evaluate(model, val_env, n_episodes=5)

            # 8. Update status
            elapsed = time.time() - start_time
            mean_reward = float(np.mean(val_rewards)) if val_rewards else 0.0
            std_reward = float(np.std(val_rewards)) + 1e-8 if val_rewards else 1.0
            mean_sharpe = mean_reward / std_reward

            self._status = TrainingStatus(
                state="completed",
                timesteps_done=cfg.total_timesteps,
                total_timesteps=cfg.total_timesteps,
                episode_count=len(sharpe_cb.episode_rewards),
                mean_reward=mean_reward,
                mean_sharpe=mean_sharpe,
                total_trades=sum(1 for _ in sharpe_cb.episode_rewards),
                elapsed_seconds=elapsed,
                model_path=final_path,
            )
            self._model = model

        except Exception as e:
            self._status = TrainingStatus(
                state="error",
                elapsed_seconds=time.time() - start_time,
                error=str(e),
            )

        return self._status

    def predict(self, observation: np.ndarray, action_mask: np.ndarray) -> int:
        """Run inference with the trained model."""
        if self._model is None:
            return 0  # HOLD

        from sb3_contrib import MaskablePPO
        action, _ = self._model.predict(
            observation,
            action_masks=action_mask,
            deterministic=True,
        )
        return int(action)

    def load_model(self, path: str) -> None:
        """Load a previously saved model."""
        from sb3_contrib import MaskablePPO
        self._model = MaskablePPO.load(path)

    @staticmethod
    def _evaluate(model, env, n_episodes: int = 5) -> list[float]:
        """Run evaluation episodes and return total rewards."""
        from sb3_contrib.common.maskable.utils import get_action_masks

        rewards: list[float] = []
        for _ in range(n_episodes):
            obs, info = env.reset()
            total_reward = 0.0
            done = False
            while not done:
                masks = env.action_masks()
                action, _ = model.predict(obs, action_masks=masks, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(int(action))
                total_reward += reward
                done = terminated or truncated
            rewards.append(total_reward)
        return rewards

    def list_models(self) -> list[dict]:
        """List saved model checkpoints."""
        model_dir = self.config.model_dir
        if not os.path.exists(model_dir):
            return []

        models = []
        for f in sorted(os.listdir(model_dir)):
            if f.endswith(".zip"):
                path = os.path.join(model_dir, f)
                stat = os.stat(path)
                models.append({
                    "name": f.replace(".zip", ""),
                    "path": path,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": stat.st_mtime,
                })
        return models
