from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JobCreate(BaseModel):
    keyword: str = Field(min_length=2, max_length=64)
    time_range: Literal["7d", "30d", "90d", "180d", "all"] = "90d"
    depth: Literal["light", "standard", "deep"] = "standard"
    analysis_mode: Literal["local", "enhanced"] = "local"
    official_bilibili_url: str | None = Field(default=None, max_length=300)
    official_mid: str | None = Field(default=None, max_length=40)
    include_discovery: bool = True
    include_taptap: bool = True
    taptap_app_id: str | None = None
    taptap_app_url: str | None = Field(default=None, max_length=300)

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @model_validator(mode="after")
    def normalize_source_urls(self) -> JobCreate:
        if self.official_bilibili_url:
            match = re.search(r"(?:space\.bilibili\.com/)?(\d{5,})", self.official_bilibili_url)
            if not match:
                raise ValueError("B站官号地址中未找到有效 MID")
            self.official_mid = match.group(1)
            self.official_bilibili_url = f"https://space.bilibili.com/{self.official_mid}"
        elif self.official_mid:
            if not self.official_mid.isdigit():
                raise ValueError("B站官号 MID 只能包含数字")
            self.official_bilibili_url = f"https://space.bilibili.com/{self.official_mid}"
        if self.taptap_app_url:
            match = re.search(r"taptap\.cn/app/(\d+)", self.taptap_app_url)
            if not match:
                raise ValueError("TapTap 地址格式应为 https://www.taptap.cn/app/<ID>")
            self.taptap_app_id = match.group(1)
            self.taptap_app_url = f"https://www.taptap.cn/app/{self.taptap_app_id}"
        return self


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
    official_bilibili_url: str | None
    official_mid: str | None
    include_discovery: bool
    include_taptap: bool
    taptap_app_id: str | None
    taptap_app_url: str | None
    taptap_candidates: list[dict[str, Any]]
    collection_metrics: dict[str, Any]
    warnings: list[str]
    partial: bool
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class TapTapSelection(BaseModel):
    app_id: str = Field(min_length=1, max_length=40)


class BrowserSessionRead(BaseModel):
    platform: Literal["bilibili", "taptap"] = "bilibili"
    running: bool
    authenticated: bool
    user_id_hint: str | None = None
    login_method: Literal["window", "qr"] = "window"
    qr_ready: bool = False
    qr_expires_at: datetime | None = None
    message: str
    workspace_ready: bool = False
    current_url: str | None = None
    page_title: str | None = None
    risk_detected: bool = False


class BrowserInput(BaseModel):
    type: Literal["click", "pointer", "wheel", "key", "text", "reload", "back", "forward"]
    x: float | None = None
    y: float | None = None
    action: Literal["down", "move", "up"] | None = None
    delta_y: float | None = None
    key: str | None = Field(default=None, max_length=40)
    text: str | None = Field(default=None, max_length=500)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=300)


class AuthSessionRead(BaseModel):
    authenticated: bool
    username: str | None = None


class ShareCreate(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=90)


class ShareRead(BaseModel):
    id: str
    url: str
    expires_at: datetime


class HealthRead(BaseModel):
    status: str
    model_configured: bool
    llm_configured: bool
    deployment_mode: Literal["local", "server"] = "local"
    access_protected: bool = False
