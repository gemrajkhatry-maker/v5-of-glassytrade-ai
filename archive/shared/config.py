"""
Unified configuration management for GlassyTrade AI.
Consolidates backend and broker configuration.
"""

import os
from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict

class SharedSettings(BaseSettings):
    """
    Base settings shared across all modules.
    Automatically loads from .env in the project root.
    """
    # Dhan Credentials
    DHAN_CLIENT_ID: str = ""
    DHAN_ACCESS_TOKEN: str = ""
    
    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    
    # Market Defaults
    DEFAULT_EXCHANGE: str = "NFO"
    TRADING_MODE: str = "PAPER"
    DRY_RUN: bool = False

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding='utf-8',
        extra='ignore'
    )

    @classmethod
    def load(cls) -> "SharedSettings":
        return cls()

settings = SharedSettings.load()
