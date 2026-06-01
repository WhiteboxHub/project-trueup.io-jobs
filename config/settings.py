import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    CHROME_USER_DATA_DIR: str = "./chrome_profile"
    HEADLESS: bool = False
    PROXY_URL: str | None = None

    AUTH_URL: str | None = None
    AUTH_USERNAME: str | None = None
    AUTH_PASSWORD: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def chrome_profile_path(self) -> str:
        return str(Path(self.CHROME_USER_DATA_DIR).resolve())


settings = Settings()
