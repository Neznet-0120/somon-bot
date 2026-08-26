from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    bot_token: str = Field(alias="BOT_TOKEN")
    admin_chat_id: int = Field(alias="ADMIN_CHAT_ID")

    # Мониторинг
    poll_interval: int = Field(default=45, alias="POLL_INTERVAL")
    track_urls: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["https://somon.tj/nedvizhimost/arenda-kvartir/dushanbe/"],
        alias="TRACK_URLS",
    )
    max_pages: int = Field(default=1, alias="MAX_PAGES")
    request_timeout: int = Field(default=15, alias="REQUEST_TIMEOUT")
    proxy_url: str | None = Field(default=None, alias="PROXY_URL")

    # Фильтры по умолчанию
    price_min: int | None = Field(default=2000, alias="PRICE_MIN")
    price_max: int | None = Field(default=7000, alias="PRICE_MAX")
    rooms: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [1, 2, 3], alias="ROOMS")
    area_min: float | None = Field(default=40, alias="AREA_MIN")
    area_max: float | None = Field(default=None, alias="AREA_MAX")
    floor_min: int | None = Field(default=2, alias="FLOOR_MIN")
    floor_max: int | None = Field(default=12, alias="FLOOR_MAX")
    districts_include: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="DISTRICTS_INCLUDE")
    districts_exclude: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="DISTRICTS_EXCLUDE")
    keywords_exclude: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "посуточно", "суточно", "на сутки", "комната", "койко", "хостел", "общежитие",
        ],
        alias="KEYWORDS_EXCLUDE",
    )
    only_with_photo: bool = Field(default=True, alias="ONLY_WITH_PHOTO")
    skip_promoted: bool = Field(default=True, alias="SKIP_PROMOTED")

    # Прочее
    db_path: str = Field(default="./data/bot.db", alias="DB_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    tz: str = Field(default="Asia/Dushanbe", alias="TZ")

    # Ограничения из ТЗ §1.13 / §1.7
    min_poll_interval: int = 20
    backoff_steps_minutes: list[int] = Field(default_factory=lambda: [1, 2, 4, 8, 16, 30])
    silence_threshold_cycles: int = 3
    admin_alert_cooldown_minutes: int = 60
    new_page_burst_ratio: float = 0.8

    @field_validator(
        "track_urls", "districts_include", "districts_exclude", "keywords_exclude", mode="before"
    )
    @classmethod
    def _parse_str_list(cls, value: object) -> object:
        if isinstance(value, str):
            return _split_csv(value)
        return value

    @field_validator("rooms", mode="before")
    @classmethod
    def _parse_rooms(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item) for item in _split_csv(value)]
        return value

    @field_validator(
        "price_min", "price_max", "area_min", "area_max", "floor_min", "floor_max", mode="before"
    )
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("proxy_url", mode="before")
    @classmethod
    def _empty_proxy_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("poll_interval")
    @classmethod
    def _enforce_min_poll_interval(cls, value: int) -> int:
        if value < 20:
            raise ValueError("POLL_INTERVAL не может быть меньше 20 секунд (см. ТЗ §1.13)")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
