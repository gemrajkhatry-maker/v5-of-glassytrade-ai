"""Application configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    BINANCE_BASE_URL: str = "https://api.binance.com"
    BINANCE_WS_URL: str = "wss://stream.binance.com:9443/ws"
    BINANCE_STREAM_URL: str = "wss://stream.binance.com:9443/stream"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3090", "http://127.0.0.1:3090", "http://localhost:5190", "http://127.0.0.1:5190"]

    # LLM Inference Paths (fine-tuned model)
    LLM_BASE_MODEL_PATH: str = os.getenv(
        "LLM_BASE_MODEL_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "poc", "models", "Nanbeige4.1-3B"),
    )
    LLM_ADAPTER_PATH: str = os.getenv(
        "LLM_ADAPTER_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "poc", "lora_adapter_mac"),
    )

    # LLM Backend Selection ("mlx" for Apple Silicon, "torch" for PyTorch MPS/CPU)
    LLM_BACKEND: str = os.getenv("LLM_BACKEND", "mlx")
    MLX_MODEL_PATH: str = os.getenv(
        "MLX_MODEL_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "poc", "models", "glassytrade-mlx-4bit"),
    )

    # LLM Inference Settings
    LLM_INSTRUCTION: str = (
        "Analyze the trading scenario based on Fabio Valentini's "
        "methodology (Orderflow, Auction Market Theory)."
    )
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_NEW_TOKENS: int = int(os.getenv("LLM_MAX_NEW_TOKENS", "80"))


settings = Settings()
