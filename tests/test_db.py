from datetime import datetime

import pytest

from core import db
from core.filters import Filters
from scraper.models import Listing


def make_listing(id: int, price: int | None = 5000) -> Listing:
    return Listing(
        id=id,
        url=f"https://somon.tj/adv/{id}_test/",
        title="2-комн. квартира, 5 этаж, 60м², Сино",
        price=price,
        currency="TJS",
        found_at=datetime.now(),
    )


@pytest.fixture
async def conn(tmp_path):
    default_filters = Filters(price_min=1000, price_max=9000, rooms=[1, 2, 3])
    connection = await db.init_db(str(tmp_path / "test.db"), default_filters)
    yield connection
    await connection.close()


async def test_cold_start_true_on_empty_db(conn) -> None:
    assert await db.is_cold_start(conn) is True


async def test_cold_start_false_after_recording(conn) -> None:
    await db.record_listings(conn, [(make_listing(1), True)])
    assert await db.is_cold_start(conn) is False


async def test_default_filters_seeded_from_config(conn) -> None:
    filters = await db.get_filters(conn)
    assert filters.price_min == 1000
    assert filters.price_max == 9000
    assert filters.rooms == [1, 2, 3]


async def test_get_seen_ids_returns_only_existing(conn) -> None:
    await db.record_listings(conn, [(make_listing(1), True), (make_listing(2), False)])
    seen = await db.get_seen_ids(conn, [1, 2, 3])
    assert seen == {1, 2}


async def test_record_listings_is_idempotent(conn) -> None:
    await db.record_listings(conn, [(make_listing(1), True)])
    await db.record_listings(conn, [(make_listing(1), True)])
    cursor = await conn.execute("SELECT COUNT(*) AS n FROM listings")
    row = await cursor.fetchone()
    assert row["n"] == 1


async def test_max_seen_id(conn) -> None:
    await db.record_listings(conn, [(make_listing(5), True), (make_listing(9), True)])
    assert await db.get_max_seen_id(conn) == 9


async def test_mark_notified(conn) -> None:
    await db.record_listings(conn, [(make_listing(1), True)])
    await db.mark_notified(conn, 1)
    cursor = await conn.execute("SELECT notified FROM listings WHERE id = 1")
    row = await cursor.fetchone()
    assert row["notified"] == 1


async def test_set_and_unset_filter_value(conn) -> None:
    await db.set_setting_raw(conn, "price_max", 6000)
    filters = await db.get_filters(conn)
    assert filters.price_max == 6000

    await db.set_setting_raw(conn, "area_min", None)
    filters = await db.get_filters(conn)
    assert filters.area_min is None


async def test_blocked_authors_roundtrip(conn) -> None:
    await db.add_blocked_author(conn, "/items/author/1/", "Агентство X")
    filters = await db.get_filters(conn)
    assert "/items/author/1/" in filters.blocked_authors


async def test_get_last_matched_orders_by_found_at_desc(conn) -> None:
    await db.record_listings(conn, [(make_listing(1), True), (make_listing(2), True)])
    rows = await db.get_last_matched(conn, limit=5)
    assert [row["id"] for row in rows] == [2, 1]
