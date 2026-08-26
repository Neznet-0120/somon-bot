"""Фикстуры содержат живые куски HTML с somon.tj, а сайт встраивает в них
сторонние ключи (Google Maps, Mapbox) для своих виджетов. Если такой ключ
попадёт в репозиторий — GitHub push protection заблокирует пуш, а если всё же
проскочит — это утечка чужого работающего ключа. Этот тест — граница: он
падает, если в фикстурах снова появится нераспознанный секрет.

Если тест упал после обновления фикстур — прогони
`python scripts/sanitize_fixtures.py`, он же тут и используется.
"""

from pathlib import Path

import pytest

from scripts.sanitize_fixtures import FIXTURES_DIR, find_matches


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.html")) + sorted(FIXTURES_DIR.glob("*.json"))


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_has_no_known_secrets(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    matches = find_matches(text)
    assert matches == [], (
        f"{path.name} содержит незачищенные секреты: {matches}. "
        f"Прогони: python scripts/sanitize_fixtures.py"
    )


def test_at_least_one_fixture_file_is_checked() -> None:
    # Страховка от опечатки в пути/маске — чтобы parametrize молча не собрал 0 тестов.
    assert len(_fixture_files()) >= 3
