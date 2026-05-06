"""Reinforcement-learning control endpoints."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.domain.ai.rl.valentini_env import ACTION_DIM, OBSERVATION_DIM

router = APIRouter(prefix="/rl", tags=["reinforcement-learning"])
log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)
_handler: object | None = None


def _get_handler():
    global _handler
    if _handler is None:
        try:
            from app.application.handlers.rl_handler import RLHandler
        except Exception as exc:  # pragma: no cover - dependency guard
            raise HTTPException(
                status_code=503,
                detail=f"RL dependencies not available: {exc}",
            ) from exc
        _handler = RLHandler()
    return _handler


class TrainRequest(BaseModel):
    total_timesteps: int = Field(100_000, ge=1_000, le=10_000_000)
    learning_rate: float = Field(3e-4, gt=0, le=1.0)
    initial_equity: float = Field(100_000.0, gt=0)
    max_risk_pct: float = Field(0.5, gt=0, le=5.0)
    tick_size: float = Field(0.01, gt=0)
    data_source: str
    verbose: int = Field(0, ge=0, le=2)


class PredictRequest(BaseModel):
    observation: list[float] = Field(..., min_length=OBSERVATION_DIM, max_length=OBSERVATION_DIM)
    action_mask: list[bool] = Field(..., min_length=ACTION_DIM, max_length=ACTION_DIM)


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
    model_ready: bool = False
    model_loaded_at: float | None = None
    error: str | None = None
    model_path: str | None = None


class ModelInfo(BaseModel):
    name: str
    path: str
    size_mb: float
    modified: float


class LoadModelResponse(BaseModel):
    message: str
    model_ready: bool
    model_loaded_at: float | None = None


@router.post("/train", response_model=StatusResponse)
async def start_training(req: TrainRequest):
    handler = _get_handler()
    try:
        data = handler.ensure_data(req.data_source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _run() -> None:
        status = handler.start_training_with_data(
            data=data,
            learning_rate=req.learning_rate,
            total_timesteps=req.total_timesteps,
            initial_equity=req.initial_equity,
            max_risk_pct=req.max_risk_pct,
            tick_size=req.tick_size,
            verbose=req.verbose,
        )
        log.info("RL training finished: %s", status.state)

    status = handler.get_status()
    if status.state == "training":
        raise HTTPException(status_code=409, detail="Training already in progress.")
    asyncio.get_running_loop().run_in_executor(_executor, _run)
    return StatusResponse(
        state="training",
        timesteps_done=0,
        total_timesteps=req.total_timesteps,
        episode_count=0,
        mean_reward=0.0,
        mean_sharpe=0.0,
        total_trades=0,
        elapsed_seconds=0.0,
        model_ready=False,
        model_loaded_at=None,
    )


@router.get("/status", response_model=StatusResponse)
async def get_training_status():
    status = _get_handler().get_status()
    return StatusResponse(
        state=status.state,
        timesteps_done=status.timesteps_done,
        total_timesteps=status.total_timesteps,
        episode_count=status.episode_count,
        mean_reward=status.mean_reward,
        mean_sharpe=status.mean_sharpe,
        total_trades=status.total_trades,
        elapsed_seconds=status.elapsed_seconds,
        model_ready=status.model_ready,
        model_loaded_at=status.model_loaded_at,
        error=status.error,
        model_path=status.model_path,
    )


@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    from app.domain.ai.rl.valentini_env import ACTION_NAMES
    import numpy as np

    obs = np.array(req.observation, dtype=np.float32)
    mask = np.array(req.action_mask, dtype=bool)
    try:
        action = _get_handler().predict(obs, mask)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return PredictResponse(action=action, action_name=ACTION_NAMES.get(int(action), "UNKNOWN"))


@router.get("/models", response_model=list[ModelInfo])
async def list_models():
    models = _get_handler().trainer.list_models()
    return [ModelInfo(**m) for m in models]


@router.post("/load/{model_name}", response_model=LoadModelResponse)
async def load_model(model_name: str):
    import os
    handler = _get_handler()
    model_dir = handler.trainer.config.model_dir
    path = os.path.join(model_dir, model_name)
    if not os.path.exists(path) and not os.path.exists(path + ".zip"):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_name}")
    try:
        if os.path.isdir(path):
            raise HTTPException(status_code=400, detail="Model path cannot be a directory.")

        if not path.endswith(".zip"):
            zip_path = path + ".zip"
            if os.path.exists(zip_path):
                path = zip_path
            elif not os.path.exists(path):
                raise HTTPException(status_code=404, detail=f"Model file not found: {model_name}")

        if not os.path.splitext(path)[1] == ".zip":
            raise HTTPException(status_code=400, detail="Model must be a Zip archive path.")

        handler.trainer.load_model(path)
        return LoadModelResponse(
            message=f"Loaded model: {model_name}",
            model_ready=handler.trainer.status.model_ready,
            model_loaded_at=handler.trainer.status.model_loaded_at,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

