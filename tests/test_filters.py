from datetime import datetime

from core.filters import Filters, matches_filters
from scraper.models import Listing


def make_listing(**overrides: object) -> Listing:
    defaults: dict[str, object] = dict(
        id=1,
        url="https://somon.tj/adv/1_test/",
        title="2-комн. квартира, 5 этаж, 60м², Сино",
        price=5000,
        currency="TJS",
        price_old=None,
        rooms=2,
        floor=5,
        area=60.0,
        district="Сино",
        image_url="https://cdntj.somon.tj/img.webp",
        author_name="Иван",
        author_url="/items/author/1/",
        is_promoted=False,
        found_at=datetime.now(),
    )
    defaults.update(overrides)
    return Listing(**defaults)  # type: ignore[arg-type]


def test_empty_filters_pass_everything() -> None:
    assert matches_filters(make_listing(), Filters()) is True


def test_price_range_filters() -> None:
    filters = Filters(price_min=3000, price_max=6000)
    assert matches_filters(make_listing(price=5000), filters) is True
    assert matches_filters(make_listing(price=2000), filters) is False
    assert matches_filters(make_listing(price=7000), filters) is False


def test_unparsed_price_is_not_filtered_out() -> None:
    filters = Filters(price_min=3000, price_max=6000)
    assert matches_filters(make_listing(price=None), filters) is True


def test_rooms_filter() -> None:
    filters = Filters(rooms=[1, 2])
    assert matches_filters(make_listing(rooms=2), filters) is True
    assert matches_filters(make_listing(rooms=3), filters) is False
    assert matches_filters(make_listing(rooms=None), filters) is True


def test_area_filter() -> None:
    filters = Filters(area_min=40, area_max=80)
    assert matches_filters(make_listing(area=60.0), filters) is True
    assert matches_filters(make_listing(area=30.0), filters) is False
    assert matches_filters(make_listing(area=None), filters) is True


def test_floor_filter_and_exclude_first_floor() -> None:
    filters = Filters(floor_min=2, floor_max=12, exclude_first_floor=True)
    assert matches_filters(make_listing(floor=5), filters) is True
    assert matches_filters(make_listing(floor=1), filters) is False
    assert matches_filters(make_listing(floor=15), filters) is False
    assert matches_filters(make_listing(floor=None), filters) is True


def test_districts_include_requires_keyword_match() -> None:
    filters = Filters(districts_include=["Сино", "Шохмансур"])
    assert matches_filters(make_listing(district="Сино"), filters) is True
    assert matches_filters(make_listing(district="Шоҳмансур"), filters) is True  # диакритика
    assert matches_filters(make_listing(district="Центр"), filters) is False
    assert matches_filters(make_listing(district=None), filters) is True


def test_districts_exclude() -> None:
    filters = Filters(districts_exclude=["Сино"])
    assert matches_filters(make_listing(district="Сино"), filters) is False
    assert matches_filters(make_listing(district="Центр"), filters) is True


def test_keywords_exclude_checks_title() -> None:
    filters = Filters(keywords_exclude=["посуточно", "хостел"])
    assert matches_filters(make_listing(title="Сдам квартиру посуточно"), filters) is False
    assert matches_filters(make_listing(title="2-комн. квартира, 5 этаж, 60м², Сино"), filters) is True


def test_only_with_photo() -> None:
    filters = Filters(only_with_photo=True)
    assert matches_filters(make_listing(image_url="https://x/img.webp"), filters) is True
    assert matches_filters(make_listing(image_url=None), filters) is False


def test_skip_promoted() -> None:
    filters = Filters(skip_promoted=True)
    assert matches_filters(make_listing(is_promoted=True), filters) is False
    assert matches_filters(make_listing(is_promoted=False), filters) is True

    filters_allow = Filters(skip_promoted=False)
    assert matches_filters(make_listing(is_promoted=True), filters_allow) is True


def test_blocked_authors_by_url_and_name() -> None:
    filters = Filters(blocked_authors=["/items/author/1/"])
    assert matches_filters(make_listing(author_url="/items/author/1/"), filters) is False
    assert matches_filters(make_listing(author_url="/items/author/2/"), filters) is True

    filters_by_name = Filters(blocked_authors=["Агентство X"])
    assert matches_filters(make_listing(author_name="Агентство X"), filters_by_name) is False


def test_all_filters_combined() -> None:
    filters = Filters(
        price_min=3000,
        price_max=6000,
        rooms=[2, 3],
        area_min=40,
        floor_min=2,
        floor_max=12,
        districts_include=["Сино"],
        keywords_exclude=["посуточно"],
        only_with_photo=True,
        skip_promoted=True,
    )
    assert matches_filters(make_listing(), filters) is True
    assert matches_filters(make_listing(price=10000), filters) is False
