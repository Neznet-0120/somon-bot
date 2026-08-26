from __future__ import annotations

import json
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import aiosqlite

from core.filters import Filters
from scraper.models import Listing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id            INTEGER PRIMARY KEY,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    price         INTEGER,
    rooms         INTEGER,
    floor         INTEGER,
    area          REAL,
    district      TEXT,
    author_name   TEXT,
    author_url    TEXT,
    image_url     TEXT,
    is_promoted   INTEGER DEFAULT 0,
    posted_raw    TEXT,
    matched       INTEGER DEFAULT 0,
    notified      INTEGER DEFAULT 0,
    found_at      TEXT NOT NULL,
    raw_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_found_at ON listings(found_at);
CREATE INDEX IF NOT EXISTS idx_matched ON listings(matched);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocked_authors (
    author_key TEXT PRIMARY KEY,
    name       TEXT,
    blocked_at TEXT NOT NULL
);
"""

_FILTER_FIELD_NAMES = {f.name for f in fields(Filters) if f.name != "blocked_authors"}


async def init_db(db_path: str, default_filters: Filters) -> aiosqlite.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(_SCHEMA)
    await conn.commit()
    await _seed_default_filters(conn, default_filters)
    return conn


async def _seed_default_filters(conn: aiosqlite.Connection, default_filters: Filters) -> None:
    cursor = await conn.execute("SELECT COUNT(*) AS n FROM settings")
    row = await cursor.fetchone()
    if row["n"] > 0:
        return
    for name in _FILTER_FIELD_NAMES:
        value = getattr(default_filters, name)
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            (name, json.dumps(value)),
        )
    await conn.commit()


async def is_cold_start(conn: aiosqlite.Connection) -> bool:
    cursor = await conn.execute("SELECT COUNT(*) AS n FROM listings")
    row = await cursor.fetchone()
    return row["n"] == 0


async def get_seen_ids(conn: aiosqlite.Connection, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    cursor = await conn.execute(f"SELECT id FROM listings WHERE id IN ({placeholders})", ids)
    rows = await cursor.fetchall()
    return {row["id"] for row in rows}


async def get_max_seen_id(conn: aiosqlite.Connection) -> int | None:
    cursor = await conn.execute("SELECT MAX(id) AS max_id FROM listings")
    row = await cursor.fetchone()
    return row["max_id"]


async def record_listings(conn: aiosqlite.Connection, items: list[tuple[Listing, bool]]) -> None:
    """items: список (Listing, matched). notified всегда стартует с 0."""
    await conn.executemany(
        """
        INSERT OR IGNORE INTO listings (
            id, url, title, price, rooms, floor, area, district,
            author_name, author_url, image_url, is_promoted, posted_raw,
            matched, notified, found_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        [
            (
                listing.id, listing.url, listing.title, listing.price, listing.rooms,
                listing.floor, listing.area, listing.district, listing.author_name,
                listing.author_url, listing.image_url, int(listing.is_promoted),
                listing.posted_raw, int(matched), listing.found_at.isoformat(), listing.raw_json,
            )
            for listing, matched in items
        ],
    )
    await conn.commit()


async def mark_notified(conn: aiosqlite.Connection, listing_id: int) -> None:
    await conn.execute("UPDATE listings SET notified = 1 WHERE id = ?", (listing_id,))
    await conn.commit()


async def get_last_matched(conn: aiosqlite.Connection, limit: int = 5) -> list[aiosqlite.Row]:
    cursor = await conn.execute(
        "SELECT * FROM listings WHERE matched = 1 ORDER BY found_at DESC LIMIT ?", (limit,)
    )
    return list(await cursor.fetchall())


async def get_matched_since(conn: aiosqlite.Connection, since: datetime) -> list[aiosqlite.Row]:
    cursor = await conn.execute(
        "SELECT * FROM listings WHERE matched = 1 AND found_at >= ? ORDER BY found_at DESC",
        (since.isoformat(),),
    )
    return list(await cursor.fetchall())


async def get_stats_since(conn: aiosqlite.Connection, since: datetime) -> dict[str, float | int]:
    cursor = await conn.execute(
        """
        SELECT COUNT(*) AS total_found,
               SUM(matched) AS total_matched,
               AVG(CASE WHEN matched = 1 THEN price END) AS avg_price
        FROM listings WHERE found_at >= ?
        """,
        (since.isoformat(),),
    )
    row = await cursor.fetchone()
    return {
        "total_found": row["total_found"] or 0,
        "total_matched": row["total_matched"] or 0,
        "avg_price": row["avg_price"] or 0,
    }


async def get_setting_raw(conn: aiosqlite.Connection, key: str) -> object | None:
    cursor = await conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return json.loads(row["value"]) if row else None


async def set_setting_raw(conn: aiosqlite.Connection, key: str, value: object) -> None:
    await conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    await conn.commit()


async def get_filters(conn: aiosqlite.Connection) -> Filters:
    cursor = await conn.execute("SELECT key, value FROM settings")
    rows = await cursor.fetchall()
    values = {row["key"]: json.loads(row["value"]) for row in rows if row["key"] in _FILTER_FIELD_NAMES}
    blocked = await list_blocked_authors(conn)
    return Filters(blocked_authors=blocked, **values)


async def add_blocked_author(conn: aiosqlite.Connection, author_key: str, name: str | None) -> None:
    await conn.execute(
        "INSERT OR REPLACE INTO blocked_authors (author_key, name, blocked_at) VALUES (?, ?, ?)",
        (author_key, name, datetime.now().isoformat()),
    )
    await conn.commit()


async def list_blocked_authors(conn: aiosqlite.Connection) -> list[str]:
    cursor = await conn.execute("SELECT author_key FROM blocked_authors")
    rows = await cursor.fetchall()
    return [row["author_key"] for row in rows]
