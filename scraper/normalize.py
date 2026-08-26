from __future__ import annotations

import re

_DIACRITICS_MAP = str.maketrans(
    {
        "ӣ": "и",
        "ӯ": "у",
        "ҳ": "х",
        "қ": "к",
        "ҷ": "ч",
        "ғ": "г",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")
_NBSP_RE = re.compile(r"[  ]")

# Заголовок карточки из JSON: "2-комн. квартира, 9 этаж, 70м², Зарафшон"
TITLE_RE = re.compile(
    r"^(?P<rooms>\d+)-комн\.\s*квартира,\s*"
    r"(?P<floor>\d+)\s*этаж,\s*"
    r"(?P<area>\d+(?:[.,]\d+)?)\s*м²,?\s*"
    r"(?P<district>.*)$"
)

# Slug из ссылки /adv/{id}_{slug}/ для fallback-режима:
# "2-komn-kvartira-10-etazh-90m2-sozidanie-paikar" или "...tsokolnyi-etazh-69-m2-..."
SLUG_RE = re.compile(
    r"^(?P<rooms>\d+)-komn-kvartira-"
    r"(?:tsokolnyi-etazh|(?P<floor>\d+)-etazh)-"
    r"(?P<area>\d+)-?m2-"
    r"(?P<district>.+)$"
)


def normalize_text(value: str) -> str:
    """Нижний регистр + замена таджикских диакритик + схлопывание пробелов."""
    normalized = value.lower().translate(_DIACRITICS_MAP)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def parse_price(raw: str | None) -> int | None:
    """'8 999 c.' -> 8999. Неразрывные пробелы и мусор игнорируются."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def parse_title(title: str) -> dict[str, int | float | str | None]:
    """Комнаты/этаж/площадь/район из заголовка объявления (основной JSON-путь)."""
    match = TITLE_RE.match(title.strip())
    if not match:
        return {"rooms": None, "floor": None, "area": None, "district": None}
    area_raw = match.group("area").replace(",", ".")
    district = match.group("district").strip().rstrip(",").strip() or None
    return {
        "rooms": int(match.group("rooms")),
        "floor": int(match.group("floor")),
        "area": float(area_raw),
        "district": district,
    }


def parse_slug(slug: str) -> dict[str, int | float | str | None] | None:
    """Комнаты/этаж/площадь/район из slug ссылки (fallback-режим). None, если slug не похож на квартиру."""
    match = SLUG_RE.match(slug)
    if not match:
        return None
    floor_raw = match.group("floor")
    district_raw = match.group("district").replace("-", " ").strip()
    return {
        "rooms": int(match.group("rooms")),
        "floor": int(floor_raw) if floor_raw else None,
        "area": float(match.group("area")),
        "district": district_raw or None,
    }


def contains_any(text: str, keywords: list[str]) -> bool:
    """Есть ли хотя бы одно ключевое слово (с нормализацией) в тексте."""
    normalized_text = normalize_text(text)
    return any(normalize_text(keyword) in normalized_text for keyword in keywords)
