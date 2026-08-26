from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Listing:
    id: int
    url: str
    title: str
    price: int | None
    currency: str
    price_old: int | None = None
    rooms: int | None = None
    floor: int | None = None
    area: float | None = None
    district: str | None = None
    image_url: str | None = None
    photos_count: int | None = None
    author_name: str | None = None
    author_url: str | None = None
    is_promoted: bool = False
    posted_raw: str | None = None
    found_at: datetime = field(default_factory=datetime.now)
    raw_json: str | None = None
