"""RL Router — API endpoints for Valentini AMT RL training and inference.

Provides endpoints to start training, check status, run inference,
and list saved model checkpoints.

All RL imports are lazy — endpoints return 503 if numpy/gymnasium are not
installed, allowing the rest of the FastAPI app to start normally.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/rl", tags=["reinforcement-learning"])
log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)

# Lazy singleton — created on first use
_trainer = None


def _get_trainer():
    """Lazy-init the ValentiniTrainer singleton."""
    global _trainer
    if _trainer is None:
        try:
            from app.domain.fabio_ai.rl.trainer import ValentiniTrainer
            _trainer = ValentiniTrainer()
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"RL dependencies not installed: {exc}",
            )
    return _trainer


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class TrainRequest(BaseModel):
    total_timesteps: int = Field(100_000, ge=1_000, le=10_000_000)
    learning_rate: float = Field(3e-4, gt=0, le=1.0)
    initial_equity: float = Field(100_000.0, gt=0)
    max_risk_pct: float = Field(0.5, gt=0, le=5.0)
    tick_size: float = Field(0.01, gt=0)
    data_source: str = Field(..., description="Path to CSV file with real market data")
    verbose: int = Field(0, ge=0, le=2)


class PredictRequest(BaseModel):
    observation: list[float] = Field(..., min_length=12, max_length=12)
    action_mask: list[bool] = Field(..., min_length=5, max_length=5)


class PredictResponse(BaseModel):
    action: int
    action_name: str


class StatusResponse(BaseModel):
    state: str
    timesteps_done: int
    total_timesteps: int
    episode_count: int
    mean_reward: float
    mean_sharpe: float
    total_trades: int
    elapsed_seconds: float
    error: str | None = None
    model_path: str | None = None


class ModelInfo(BaseModel):
    name: str
    path: str
    size_mb: float
    modified: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/train", response_model=StatusResponse)
async def start_training(req: TrainRequest, background_tasks: BackgroundTasks):
    """Start an RL training run in the background."""
    from app.domain.fabio_ai.rl.trainer import ValentiniTrainer, TrainingConfig
    from app.domain.fabio_ai.rl.data_loader import load_from_csv

    global _trainer
    trainer = _get_trainer()

    if trainer.status.state == "training":
        raise HTTPException(
            status_code=409,
            detail="Training already in progress. Check /api/rl/status.",
        )

    config = TrainingConfig(
        total_timesteps=req.total_timesteps,
        learning_rate=req.learning_rate,
        initial_equity=req.initial_equity,
        max_risk_pct=req.max_risk_pct,
        tick_size=req.tick_size,
    )
    _trainer = ValentiniTrainer(config=config)
    trainer = _trainer

    # Load data — only real market data from CSV
    data = load_from_csv(req.data_source)
    if not data:
        raise HTTPException(
            status_code=400,
            detail=f"No data found at: {req.data_source}",
        )

    def _run_training():
        trainer.train(data=data, verbose=req.verbose)

    # Run training in background thread
    background_tasks.add_task(
        asyncio.get_event_loop().run_in_executor,
        _executor, _run_training,
    )

    return StatusResponse(
        state="training",
        timesteps_done=0,
        total_timesteps=req.total_timesteps,
        episode_count=0,
        mean_reward=0.0,
        mean_sharpe=0.0,
        total_trades=0,
        elapsed_seconds=0.0,
    )


@router.get("/status", response_model=StatusResponse)
async def get_training_status():
    """Get current training status."""
    trainer = _get_trainer()
    s = trainer.status
    return StatusResponse(
        state=s.state,
        timesteps_done=s.timesteps_done,
        total_timesteps=s.total_timesteps,
        episode_count=s.episode_count,
        mean_reward=s.mean_reward,
        mean_sharpe=s.mean_sharpe,
        total_trades=s.total_trades,
        elapsed_seconds=s.elapsed_seconds,
        error=s.error,
        model_path=s.model_path,
    )


@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    """Run inference with the trained model."""
    import numpy as np
    from app.domain.fabio_ai.rl.valentini_env import ACTION_NAMES

    trainer = _get_trainer()
    obs = np.array(req.observation, dtype=np.float32)
    mask = np.array(req.action_mask, dtype=bool)

    action = trainer.predict(obs, mask)
    return PredictResponse(
        action=action,
        action_name=ACTION_NAMES.get(action, "UNKNOWN"),
    )


@router.get("/models", response_model=list[ModelInfo])
async def list_models():
    """List saved model checkpoints."""
    trainer = _get_trainer()
    models = trainer.list_models()
    return [ModelInfo(**m) for m in models]


@router.post("/load/{model_name}")
async def load_model(model_name: str):
    """Load a specific model checkpoint."""
    import os
    trainer = _get_trainer()
    path = os.path.join(trainer.config.model_dir, model_name)
    if not os.path.exists(path) and not os.path.exists(path + ".zip"):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_name}")
    try:
        trainer.load_model(path)
        return {"message": f"Loaded model: {model_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
