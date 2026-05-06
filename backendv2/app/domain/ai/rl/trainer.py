"""PPO trainer for Valentini AMT RL experiments."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.domain.ai.rl.data_loader import split_data
from app.domain.ai.rl.valentini_env import ValentiniAMTEnv
from app.domain.trading.model.value_objects import OHLC
from stable_baselines3.common.callbacks import BaseCallback


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
    """Current training progress and summary."""

    state: str = "idle"
    timesteps_done: int = 0
    total_timesteps: int = 0
    episode_count: int = 0
    mean_reward: float = 0.0
    mean_sharpe: float = 0.0
    total_trades: int = 0
    elapsed_seconds: float = 0.0
    model_ready: bool = False
    model_loaded_at: float | None = None
    error: str | None = None
    model_path: str | None = None


class SharpeCallback(BaseCallback):
    """Track rolling Sharpe on completed episode rewards."""

    def __init__(self, check_freq: int = 1000, verbose: int = 0):
        super().__init__(verbose)
        self.check_freq = check_freq
        self.episode_rewards: list[float] = []
        self.sharpe_history: list[float] = []

    def _on_step(self) -> bool:
        infos = self.locals.get("infos", [])
        for info in infos:
            if "episode" in info:
                self.episode_rewards.append(info["episode"]["r"])
        if self.n_calls % self.check_freq == 0 and len(self.episode_rewards) > 10:
            recent = self.episode_rewards[-50:]
            mean_r = float(np.mean(recent))
            std_r = float(np.std(recent)) + 1e-8
            self.sharpe_history.append(mean_r / std_r)
            if self.verbose > 0:
                print(f"[Sharpe] Step {self.n_calls}: mean_reward={mean_r:.2f}, sharpe={mean_r / std_r:.2f}")
        return True


class CheckpointCallback(BaseCallback):
    """Persist intermediate checkpoints."""

    def __init__(self, save_freq: int, save_path: str, verbose: int = 0):
        super().__init__(verbose)
        self.save_freq = save_freq
        self.save_path = save_path
        os.makedirs(save_path, exist_ok=True)

    def _on_step(self) -> bool:
        if self.n_calls % self.save_freq == 0:
            path = os.path.join(self.save_path, f"checkpoint_{self.n_calls}.zip")
            self.model.save(path)
            if self.verbose > 0:
                print(f"[Checkpoint] Saved {path}")
        return True


class ProgressCallback(BaseCallback):
    """Keep training status updated during long running training."""

    def __init__(self, status: TrainingStatus, total_timesteps: int, verbose: int = 0):
        super().__init__(verbose)
        self._status = status
        self._total_timesteps = total_timesteps

    def _on_step(self) -> bool:
        self._status.timesteps_done = min(self._total_timesteps, self.n_calls)
        return True


class ValentiniTrainer:
    """Orchestrates PPO training and validation."""

    def __init__(self, config: TrainingConfig | None = None) -> None:
        self.config = config or TrainingConfig()
        self._status = TrainingStatus()
        self._model = None

    @property
    def status(self) -> TrainingStatus:
        return self._status

    def train(self, data: list[OHLC] | None = None, verbose: int = 1) -> TrainingStatus:
        """Run full training lifecycle."""
        from sb3_contrib import MaskablePPO

        cfg = self.config
        self._status = TrainingStatus(
            state="training",
            total_timesteps=cfg.total_timesteps,
            model_ready=self._model is not None,
        )
        start_time = time.time()

        try:
            if data is None:
                raise ValueError("Real market data (list[OHLC]) is required for training.")
            split = split_data(data)

            env = ValentiniAMTEnv(
                data=split.train,
                initial_equity=cfg.initial_equity,
                max_risk_pct=cfg.max_risk_pct,
                tick_size=cfg.tick_size,
                max_bars_in_trade=cfg.max_bars_in_trade,
            )

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

            sharpe_cb = SharpeCallback(check_freq=1000, verbose=verbose)
            progress_cb = ProgressCallback(self._status, cfg.total_timesteps, verbose=verbose)
            checkpoint_cb = CheckpointCallback(
                save_freq=cfg.checkpoint_freq,
                save_path=cfg.model_dir,
                verbose=verbose,
            )

            model.learn(
                total_timesteps=cfg.total_timesteps,
                callback=[progress_cb, sharpe_cb, checkpoint_cb],
                progress_bar=False,
            )

            final_path = os.path.join(cfg.model_dir, "valentini_final.zip")
            model.save(final_path)

            val_env = ValentiniAMTEnv(
                data=split.validation,
                initial_equity=cfg.initial_equity,
                max_risk_pct=cfg.max_risk_pct,
                tick_size=cfg.tick_size,
            )
            val_rewards = self._evaluate(model, val_env, n_episodes=5)
            elapsed = time.time() - start_time
            mean_reward = float(np.mean(val_rewards)) if val_rewards else 0.0
            std_reward = float(np.std(val_rewards)) + 1e-8 if val_rewards else 1.0
            self._status = TrainingStatus(
                state="completed",
                timesteps_done=cfg.total_timesteps,
                total_timesteps=cfg.total_timesteps,
                episode_count=len(sharpe_cb.episode_rewards),
                mean_reward=mean_reward,
                mean_sharpe=mean_reward / std_reward,
                total_trades=0,
                elapsed_seconds=elapsed,
                model_path=final_path,
                model_ready=True,
                model_loaded_at=time.time(),
            )
            self._model = model
        except Exception as exc:
            self._status = TrainingStatus(
                state="error",
                elapsed_seconds=time.time() - start_time,
                total_timesteps=cfg.total_timesteps,
                error=str(exc),
            )
        return self._status

    def predict(self, observation: np.ndarray, action_mask: np.ndarray) -> int:
        if self._model is None:
            raise RuntimeError("Model is not loaded. Train or load a model first.")
        from sb3_contrib import MaskablePPO
        action, _ = self._model.predict(observation, action_masks=action_mask, deterministic=True)
        return int(action)

    def load_model(self, path: str) -> None:
        from sb3_contrib import MaskablePPO
        self._model = MaskablePPO.load(path)
        self._status = TrainingStatus(
            state=self._status.state,
            timesteps_done=self._status.timesteps_done,
            total_timesteps=self._status.total_timesteps,
            episode_count=self._status.episode_count,
            mean_reward=self._status.mean_reward,
            mean_sharpe=self._status.mean_sharpe,
            total_trades=self._status.total_trades,
            elapsed_seconds=self._status.elapsed_seconds,
            model_ready=True,
            model_loaded_at=time.time(),
            model_path=path,
            error=self._status.error,
        )

    def is_model_ready(self) -> bool:
        return self._model is not None

    def list_models(self) -> list[dict[str, Any]]:
        model_dir = self.config.model_dir
        if not os.path.exists(model_dir):
            return []
        models: list[dict[str, Any]] = []
        for file_name in sorted(os.listdir(model_dir)):
            if file_name.endswith(".zip"):
                path = os.path.join(model_dir, file_name)
                stat = os.stat(path)
                models.append(
                    {
                        "name": file_name.replace(".zip", ""),
                        "path": path,
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "modified": stat.st_mtime,
                    }
                )
        return models

    @staticmethod
    def _evaluate(model, env: ValentiniAMTEnv, n_episodes: int = 5) -> list[float]:
        rewards: list[float] = []
        for _ in range(max(1, n_episodes)):
            obs, info = env.reset()
            total_reward = 0.0
            done = False
            while not done:
                action, _ = model.predict(obs, action_masks=env.action_masks(), deterministic=True)
                obs, reward, terminated, truncated, info = env.step(int(action))
                total_reward += reward
                done = terminated or truncated
            rewards.append(total_reward)
        return rewards

