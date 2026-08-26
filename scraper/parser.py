from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum

from scraper.models import Listing
from scraper.normalize import parse_price, parse_slug, parse_title

_RSC_CHUNK_RE = re.compile(r"self\.__next_f\.push\(\[\d+,(.*?)\]\)</script>", re.DOTALL)
_ADV_LINK_RE = re.compile(r"/adv/(\d+)_([a-z0-9-]+)/")

_PROMOTED_AD_TYPES = {"premium", "top"}
_BAN_BANNER_TEXT = "аккаунт был заблокирован"


class ParseMode(str, Enum):
    JSON = "json"
    FALLBACK = "fallback"


def _find_adverts_payload(html: str) -> list[dict] | None:
    """Ищет среди RSC-чанков self.__next_f.push тот, что содержит ключ 'adverts'."""
    for match in _RSC_CHUNK_RE.finditer(html):
        try:
            chunk_text = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(chunk_text, str) or ":" not in chunk_text:
            continue
        _, _, payload_text = chunk_text.partition(":")
        try:
            payload = json.loads(payload_text)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict) and "adverts" in payload:
            return payload["adverts"]
    return None


def _listing_from_advert(advert: dict) -> Listing:
    parsed_title = parse_title(advert.get("title", ""))
    user = advert.get("user") or {}
    author_id = user.get("id")
    return Listing(
        id=advert["id"],
        url=f"https://somon.tj{advert['url']}",
        title=advert.get("title", ""),
        price=parse_price(advert.get("price")),
        price_old=parse_price(advert.get("start_price")),
        currency=advert.get("currency", "TJS"),
        rooms=parsed_title["rooms"],
        floor=parsed_title["floor"],
        area=parsed_title["area"],
        district=parsed_title["district"],
        image_url=advert.get("first_thumb"),
        photos_count=advert.get("img_count"),
        author_name=user.get("name"),
        author_url=f"/items/author/{author_id}/" if author_id else None,
        is_promoted=advert.get("ad_type", {}).get("type") in _PROMOTED_AD_TYPES,
        posted_raw=advert.get("published"),
        found_at=datetime.now(),
        raw_json=json.dumps(advert, ensure_ascii=False),
    )


def _listing_from_slug(listing_id: int, slug: str) -> Listing | None:
    """Fallback: восстанавливает частичный Listing из slug ссылки, без цены и автора."""
    parsed = parse_slug(slug)
    if parsed is None:
        return None
    return Listing(
        id=listing_id,
        url=f"https://somon.tj/adv/{listing_id}_{slug}/",
        title=slug.replace("-", " "),
        price=None,
        price_old=None,
        currency="TJS",
        rooms=parsed["rooms"],
        floor=parsed["floor"],
        area=parsed["area"],
        district=parsed["district"],
        is_promoted=False,
        found_at=datetime.now(),
    )


def detect_ban_banner(html: str) -> bool:
    """Реальный баннер антибота, а не строка-шаблон i18n внутри RSC-чанков.

    Фраза "аккаунт был заблокирован" встречается в бандле переводов на КАЖДОЙ
    странице как ключ i18n (youBlocked) — это ложное срабатывание. Поэтому
    сначала вырезаем все self.__next_f.push(...) чанки и ищем фразу только
    в оставшейся, видимой части HTML.
    """
    visible_html = _RSC_CHUNK_RE.sub("", html)
    return _BAN_BANNER_TEXT in visible_html


def parse_listing_page(html: str) -> tuple[list[Listing], ParseMode]:
    """Основная точка входа. Возвращает (объявления, режим_парсинга).

    Сначала пробует найти RSC JSON-payload с ключом 'adverts' — основной, надёжный путь.
    Если сайт изменил структуру и payload не нашёлся — деградирует в fallback-режим:
    вытаскивает id+slug из ссылок /adv/{id}_{slug}/ регуляркой, без цены/автора.
    """
    adverts = _find_adverts_payload(html)
    if adverts is not None:
        listings = [_listing_from_advert(a) for a in adverts]
        return listings, ParseMode.JSON

    listings = []
    seen_ids: set[int] = set()
    for listing_id_str, slug in _ADV_LINK_RE.findall(html):
        listing_id = int(listing_id_str)
        if listing_id in seen_ids:
            continue
        listing = _listing_from_slug(listing_id, slug)
        if listing is not None:
            seen_ids.add(listing_id)
            listings.append(listing)
    return listings, ParseMode.FALLBACK
