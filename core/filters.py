from __future__ import annotations

from dataclasses import dataclass, field

from scraper.models import Listing
from scraper.normalize import contains_any


@dataclass(slots=True)
class Filters:
    price_min: int | None = None
    price_max: int | None = None
    rooms: list[int] = field(default_factory=list)
    area_min: float | None = None
    area_max: float | None = None
    floor_min: int | None = None
    floor_max: int | None = None
    exclude_first_floor: bool = False
    # exclude_last_floor не реализован: общая этажность дома отсутствует в
    # данных ленты объявлений somon.tj (только этаж конкретной квартиры),
    # получить её можно только запросом страницы объявления — вне бюджета
    # запросов из ТЗ §1.13. Поле оставлено в модели для совместимости команд.
    exclude_last_floor: bool = False
    districts_include: list[str] = field(default_factory=list)
    districts_exclude: list[str] = field(default_factory=list)
    keywords_exclude: list[str] = field(default_factory=list)
    only_with_photo: bool = False
    skip_promoted: bool = True
    blocked_authors: list[str] = field(default_factory=list)


def matches_filters(listing: Listing, filters: Filters) -> bool:
    """True, если объявление проходит ВСЕ активные фильтры.

    Незаданный фильтр не применяется. Если поле объявления не распарсилось
    (None), фильтр по нему не отсекает объявление (ТЗ §1.4).
    """
    if filters.skip_promoted and listing.is_promoted:
        return False

    if _is_blocked_author(listing, filters.blocked_authors):
        return False

    if listing.price is not None:
        if filters.price_min is not None and listing.price < filters.price_min:
            return False
        if filters.price_max is not None and listing.price > filters.price_max:
            return False

    if listing.rooms is not None and filters.rooms and listing.rooms not in filters.rooms:
        return False

    if listing.area is not None:
        if filters.area_min is not None and listing.area < filters.area_min:
            return False
        if filters.area_max is not None and listing.area > filters.area_max:
            return False

    if listing.floor is not None:
        if filters.floor_min is not None and listing.floor < filters.floor_min:
            return False
        if filters.floor_max is not None and listing.floor > filters.floor_max:
            return False
        if filters.exclude_first_floor and listing.floor == 1:
            return False

    if listing.district is not None:
        if filters.districts_include and not contains_any(listing.district, filters.districts_include):
            return False
        if filters.districts_exclude and contains_any(listing.district, filters.districts_exclude):
            return False

    if filters.keywords_exclude and contains_any(listing.title, filters.keywords_exclude):
        return False

    if filters.only_with_photo and not listing.image_url:
        return False

    return True


def _is_blocked_author(listing: Listing, blocked_authors: list[str]) -> bool:
    if not blocked_authors:
        return False
    candidates = {listing.author_url, listing.author_name}
    return any(candidate in blocked_authors for candidate in candidates if candidate is not None)
