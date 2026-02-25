"""Application configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3090", "http://127.0.0.1:3090", "http://localhost:5190", "http://127.0.0.1:5190"]

    # Dhan Broker Config
    DHAN_CLIENT_ID: str = os.getenv("DHAN_CLIENT_ID", "")
    DHAN_ACCESS_TOKEN: str = os.getenv("DHAN_ACCESS_TOKEN", "").strip("'")
    DEFAULT_SYMBOL: str = os.getenv("DEFAULT_SYMBOL", "NIFTY 27 FEB 25500 CALL")
    DEFAULT_EXCHANGE: str = os.getenv("DEFAULT_EXCHANGE", "NFO")
    DHAN_SYMBOLS: list[str] = os.getenv("DHAN_SYMBOLS", "NIFTY,BANKNIFTY").split(",")
    SCANNER_UNDERLYING: str = os.getenv("SCANNER_UNDERLYING", "NIFTY")
    SCANNER_OPTION_TYPE: str = os.getenv("SCANNER_OPTION_TYPE", "")  # Empty = auto-detect from momentum
    SCANNER_EXPIRY_INDEX: int = int(os.getenv("SCANNER_EXPIRY_INDEX", "0"))  # 0=current week (max gamma for scalping)

    # Trading settings
    TRADING_MODE: str = os.getenv("TRADING_MODE", "PAPER")
    STREAM_INTERVAL: str = os.getenv("STREAM_INTERVAL", "5m")
    TICK_POLL_SECONDS: float = float(os.getenv("TICK_POLL_SECONDS", "5"))

    # LLM Inference Paths (fine-tuned model)
    LLM_BASE_MODEL_PATH: str = os.getenv(
        "LLM_BASE_MODEL_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "poc", "models", "Nanbeige4.1-3B"),
    )
    LLM_ADAPTER_PATH: str = os.getenv(
        "LLM_ADAPTER_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "poc", "lora_adapter_mac"),
    )

    # LLM Backend Selection ("mlx" for Apple Silicon, "none" to disable)
    LLM_BACKEND: str = os.getenv("LLM_BACKEND", "mlx")
    MLX_MODEL_PATH: str = os.getenv(
        "MLX_MODEL_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "poc", "models", "glassytrade-mlx-4bit"),
    )

    # LLM Inference Settings
    LLM_INSTRUCTION: str = (
        "You are trading using Fabio Valentini's Auction Market Theory model. "
        "You are not predicting — you are READING the auction. "
        "Read the narrative: market state, location, order flow. "
        "If the story is clear and all three align, state your conviction and direction. "
        "If you don't see the setup, STAY FLAT. Never trade without conviction."
    )
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_ENTRY_TEMPERATURE: float = float(os.getenv("LLM_ENTRY_TEMPERATURE", "0.4"))
    LLM_OVERSEER_TEMPERATURE: float = float(os.getenv("LLM_OVERSEER_TEMPERATURE", "0.3"))
    LLM_MAX_NEW_TOKENS: int = int(os.getenv("LLM_MAX_NEW_TOKENS", "80"))
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "60.0"))

    # Notifications
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")


settings = Settings()
