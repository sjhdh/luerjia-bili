from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobCreate(BaseModel):
    keyword: str = Field(min_length=2, max_length=64)
    time_range: Literal["7d", "30d", "90d", "180d", "all"] = "90d"
    depth: Literal["light", "standard", "deep"] = "standard"
    analysis_mode: Literal["local", "enhanced"] = "local"
    taptap_app_id: str | None = None

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str) -> str:
        return " ".join(value.strip().split())


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    keyword: str
    status: str
    stage: str
    progress: int
    message: str
    analysis_mode: str
    time_range: str
    depth: str
    taptap_app_id: str | None
    taptap_candidates: list[dict[str, Any]]
    warnings: list[str]
    partial: bool
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class TapTapSelection(BaseModel):
    app_id: str = Field(min_length=1, max_length=40)


class BrowserSessionRead(BaseModel):
    running: bool
    authenticated: bool
    user_id_hint: str | None = None
    message: str


class HealthRead(BaseModel):
    status: str
    model_configured: bool
    llm_configured: bool
