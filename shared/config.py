"""
Unified configuration management for GlassyTrade AI.
Consolidates backend and broker configuration.
"""

import os
from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class SharedSettings(BaseSettings):
    """
    Base settings shared across all modules.
    Automatically loads from .env in the project root.
    """
    # Dhan Credentials
    DHAN_CLIENT_ID: str = Field(default="", env="DHAN_CLIENT_ID")
    DHAN_ACCESS_TOKEN: str = Field(default="", env="DHAN_ACCESS_TOKEN")
    
    # Environment
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    DEBUG: bool = Field(default=False, env="DEBUG")
    
    # Market Defaults
    DEFAULT_EXCHANGE: str = Field(default="NFO", env="DEFAULT_EXCHANGE")
    TRADING_MODE: str = Field(default="PAPER", env="TRADING_MODE")
    DRY_RUN: bool = Field(default=False, env="DRY_RUN")

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding='utf-8',
        extra='ignore'
    )

    @classmethod
    def load(cls) -> "SharedSettings":
        return cls()

settings = SharedSettings.load()
