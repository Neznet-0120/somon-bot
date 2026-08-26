#!/usr/bin/env python3
"""Вычищает сторонние API-ключи/токены из тестовых фикстур somon.tj.

somon.tj встраивает в HTML живые ключи карт (Google Maps, Mapbox) для своих
виджетов — это не наши секреты, но GitHub push protection блокирует пуш,
если они попадут в репозиторий. Каждое совпадение заменяется строкой из "x"
ТОЙ ЖЕ ДЛИНЫ, чтобы не сдвинуть байтовые смещения JSON внутри RSC-чанков
(self.__next_f.push(...)) — обычная замена другой длины ломает JSON и роняет
парсер в fallback-режим (см. README, "Как обновлять фикстуры").

Использование:
    python scripts/sanitize_fixtures.py [--check]

    --check   ничего не меняет, только проверяет и возвращает ненулевой код
              выхода, если найдены незачищенные секреты (для CI/pre-commit).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# (паттерн, человекочитаемое имя) — используются и здесь, и в
# tests/test_fixtures_clean.py, держите оба списка в синхроне.
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk\.ey[A-Za-z0-9._-]+"), "Mapbox secret token"),
    (re.compile(r"pk\.ey[A-Za-z0-9._-]+"), "Mapbox public token"),
    (re.compile(r"AIzaSy[A-Za-z0-9_-]{20,}"), "Google API key"),
]


def redact(text: str) -> tuple[str, int]:
    """Возвращает (очищенный_текст, число_замен). Длина текста не меняется."""
    total_replacements = 0

    for pattern, _name in SECRET_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            nonlocal total_replacements
            total_replacements += 1
            return "x" * len(match.group(0))

        text = pattern.sub(_replace, text)

    return text, total_replacements


def find_matches(text: str) -> list[str]:
    """Список имён паттернов, для которых в тексте есть хотя бы одно совпадение."""
    return [name for pattern, name in SECRET_PATTERNS if pattern.search(text)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="только проверить, не изменять файлы",
    )
    args = parser.parse_args()

    fixture_files = sorted(FIXTURES_DIR.glob("*.html")) + sorted(FIXTURES_DIR.glob("*.json"))
    if not fixture_files:
        print(f"Фикстуры не найдены в {FIXTURES_DIR}")
        return 0

    found_dirty = False

    for path in fixture_files:
        original = path.read_text(encoding="utf-8")

        if args.check:
            matches = find_matches(original)
            if matches:
                found_dirty = True
                print(f"❌ {path.relative_to(FIXTURES_DIR.parent.parent)}: найдены {', '.join(matches)}")
            else:
                print(f"✅ {path.relative_to(FIXTURES_DIR.parent.parent)}: чисто")
            continue

        cleaned, count = redact(original)
        if count > 0:
            if len(cleaned) != len(original):
                print(f"⚠️  {path}: длина изменилась ({len(original)} -> {len(cleaned)}), пропускаю запись!")
                found_dirty = True
                continue
            path.write_text(cleaned, encoding="utf-8")
            print(f"🧹 {path.relative_to(FIXTURES_DIR.parent.parent)}: заменено вхождений: {count}")
        else:
            print(f"✅ {path.relative_to(FIXTURES_DIR.parent.parent)}: секретов не найдено")

    if args.check and found_dirty:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
