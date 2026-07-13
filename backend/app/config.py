from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "路尔嘉舆情分析"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = ROOT_DIR / "data"
    database_url: str | None = None
    browser_headless: bool = False
    browser_slow_mo_ms: int = 0
    lightweight_analysis: bool = False
    local_model_id: str = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
    local_model_revision: str = "cf991100d706c13c0a080c097134c05b7f436c45"
    openai_base_url: str | None = None
    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str | None = None
    raw_retention_days: int = 30
    report_retention_days: int = 180
    crawl_min_delay_seconds: float = 1.2
    crawl_max_delay_seconds: float = 2.2

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{self.data_dir / 'luerjia.db'}"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
