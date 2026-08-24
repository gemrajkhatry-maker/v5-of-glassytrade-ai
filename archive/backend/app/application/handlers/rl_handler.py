"""RL Handler — RL training coordination (optional)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from quant.inference.rl.trainer import ValentiniTrainer
    _RL_AVAILABLE = True
except ImportError:
    _RL_AVAILABLE = False
    logger.info("RL dependencies not installed — RL signals disabled")


class RLHandler:
    """Handles RL training status (optional)."""

    def __init__(self) -> None:
        self._rl_trainer = ValentiniTrainer() if _RL_AVAILABLE else None

    def get_status(self) -> dict:
        """Get RL training status for state snapshot."""
        if not _RL_AVAILABLE or not self._rl_trainer:
            return {
                "state": "unavailable",
                "modelLoaded": False,
                "timestepsDone": 0,
                "totalTimesteps": 0,
                "episodeCount": 0,
                "meanReward": 0.0,
                "meanSharpe": 0.0,
                "totalTrades": 0,
                "elapsedSeconds": 0.0,
            }

        rl_st = self._rl_trainer.status
        return {
            "state": rl_st.state,
            "modelLoaded": bool(rl_st.model_path),
            "timestepsDone": rl_st.timesteps_done,
            "totalTimesteps": rl_st.total_timesteps,
            "episodeCount": rl_st.episode_count,
            "meanReward": rl_st.mean_reward,
            "meanSharpe": rl_st.mean_sharpe,
            "totalTrades": rl_st.total_trades,
            "elapsedSeconds": rl_st.elapsed_seconds,
        }

    @property
    def trainer(self):
        """Access to RL trainer (for REST endpoints)."""
        return self._rl_trainer
