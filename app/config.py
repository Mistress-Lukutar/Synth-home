"""Application configuration."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    port: int = 8080
    host: str = "127.0.0.1"
    log_level: str = "INFO"
    cors_origins: list[str] = []
    auto_connect_port: Optional[str] = None
    api_key: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
