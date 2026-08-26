from __future__ import annotations

import csv
import io
import types
import typing
from dataclasses import fields
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.keyboards import filters_menu_keyboard
from core import db
from core.filters import Filters
from core.worker import Worker
from scraper.client import SomonClient
from scraper.parser import parse_listing_page

router = Router()

_FILTER_TYPE_HINTS = typing.get_type_hints(Filters)
_SETTABLE_KEYS = {name for name in _FILTER_TYPE_HINTS if name != "blocked_authors"}


def _coerce_value(key: str, raw: str) -> object:
    hint = _FILTER_TYPE_HINTS[key]
    origin = typing.get_origin(hint)

    if origin is list:
        item_type = typing.get_args(hint)[0]
        items = [v.strip() for v in raw.split(",") if v.strip()]
        return [item_type(v) for v in items] if item_type is not str else items

    base = hint
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        base = args[0] if args else str

    if base is bool:
        return raw.strip().lower() in {"true", "1", "yes", "on", "вкл"}
    if base is int:
        return int(raw)
    if base is float:
        return float(raw)
    return raw


def _format_filters(filters: Filters) -> str:
    lines = ["<b>Текущие фильтры:</b>"]
    for f in fields(filters):
        if f.name == "blocked_authors":
            continue
        value = getattr(filters, f.name)
        lines.append(f"• {f.name} = {value if value not in (None, []) else '—'}")
    if filters.blocked_authors:
        lines.append(f"• blocked_authors = {len(filters.blocked_authors)} шт.")
    return "\n".join(lines)


@router.message(Command("start"))
async def cmd_start(message: Message, worker: Worker) -> None:
    status = "работает" if not worker.state.paused else "на паузе"
    await message.answer(
        f"👋 Привет! Слежу за новыми объявлениями об аренде на somon.tj.\nСтатус: {status}."
    )


@router.message(Command("status"))
async def cmd_status(message: Message, worker: Worker) -> None:
    s = worker.state
    lines = [
        f"Статус: {'⏸ на паузе' if s.paused else '▶️ работает'}",
        f"Интервал опроса: {s.poll_interval} сек",
        f"Последняя проверка: {s.last_check_at.strftime('%d.%m %H:%M:%S') if s.last_check_at else '—'}",
        f"Режим парсинга: {s.parse_mode.value}",
        f"Последняя ошибка: {s.last_error or '—'}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("filters"))
async def cmd_filters(message: Message, conn: aiosqlite.Connection) -> None:
    filters = await db.get_filters(conn)
    await message.answer(
        _format_filters(filters), parse_mode="HTML", reply_markup=filters_menu_keyboard(filters)
    )


@router.message(Command("set"))
async def cmd_set(message: Message, command: CommandObject, conn: aiosqlite.Connection) -> None:
    args = (command.args or "").split(maxsplit=1)
    if len(args) != 2:
        await message.answer("Использование: /set <фильтр> <значение>")
        return
    key, raw_value = args
    if key not in _SETTABLE_KEYS:
        await message.answer(f"Неизвестный фильтр: {key}")
        return
    try:
        value = _coerce_value(key, raw_value)
    except ValueError:
        await message.answer(f"Не удалось разобрать значение для {key}: {raw_value}")
        return
    await db.set_setting_raw(conn, key, value)
    await message.answer(f"✅ {key} = {value}")


@router.message(Command("unset"))
async def cmd_unset(message: Message, command: CommandObject, conn: aiosqlite.Connection) -> None:
    key = (command.args or "").strip()
    if key not in _SETTABLE_KEYS:
        await message.answer(f"Неизвестный фильтр: {key}")
        return
    await db.set_setting_raw(conn, key, None)
    await message.answer(f"✅ {key} сброшен")


@router.message(Command("rooms"))
async def cmd_rooms(message: Message, command: CommandObject, conn: aiosqlite.Connection) -> None:
    args = (command.args or "").split()
    try:
        rooms = [int(a) for a in args]
    except ValueError:
        await message.answer("Использование: /rooms 1 2 3")
        return
    await db.set_setting_raw(conn, "rooms", rooms)
    await message.answer(f"✅ Комнатность: {rooms or 'любая'}")


@router.message(Command("district"))
async def cmd_district(message: Message, command: CommandObject, conn: aiosqlite.Connection) -> None:
    args = (command.args or "").split(maxsplit=1)
    if not args:
        await message.answer("Использование: /district add|del|clear [район]")
        return
    action = args[0].lower()
    filters = await db.get_filters(conn)
    current = list(filters.districts_include)

    if action == "clear":
        await db.set_setting_raw(conn, "districts_include", [])
        await message.answer("✅ Список районов очищен")
        return

    if len(args) < 2:
        await message.answer("Укажи район: /district add|del <район>")
        return
    district = args[1].strip()

    if action == "add":
        if district not in current:
            current.append(district)
        await db.set_setting_raw(conn, "districts_include", current)
        await message.answer(f"✅ Добавлен район: {district}")
    elif action == "del":
        current = [d for d in current if d != district]
        await db.set_setting_raw(conn, "districts_include", current)
        await message.answer(f"✅ Удалён район: {district}")
    else:
        await message.answer("Неизвестное действие. Используй add, del или clear")


@router.message(Command("block"))
async def cmd_block(message: Message, command: CommandObject, conn: aiosqlite.Connection) -> None:
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Использование: /block <author_url или id объявления>")
        return
    if arg.isdigit():
        cursor = await conn.execute("SELECT author_url, author_name FROM listings WHERE id = ?", (int(arg),))
        row = await cursor.fetchone()
        if row is None or not row["author_url"]:
            await message.answer("Объявление не найдено или у него нет автора")
            return
        await db.add_blocked_author(conn, row["author_url"], row["author_name"])
        await message.answer(f"🚫 Заблокирован автор: {row['author_name'] or row['author_url']}")
    else:
        await db.add_blocked_author(conn, arg, None)
        await message.answer(f"🚫 Заблокирован автор: {arg}")


@router.message(Command("pause"))
async def cmd_pause(message: Message, command: CommandObject, worker: Worker) -> None:
    args = (command.args or "").strip()
    worker.state.paused = True
    if args.isdigit():
        minutes = int(args)
        worker.state.paused_until = datetime.now() + timedelta(minutes=minutes)
        await message.answer(f"⏸ Пауза на {minutes} минут")
    else:
        worker.state.paused_until = None
        await message.answer("⏸ Пауза (бессрочно, до /resume)")


@router.message(Command("resume"))
async def cmd_resume(message: Message, worker: Worker) -> None:
    worker.state.paused = False
    worker.state.paused_until = None
    await message.answer("▶️ Продолжаю работу")


@router.message(Command("last"))
async def cmd_last(message: Message, command: CommandObject, conn: aiosqlite.Connection) -> None:
    args = (command.args or "").strip()
    limit = int(args) if args.isdigit() else 5
    rows = await db.get_last_matched(conn, limit=limit)
    if not rows:
        await message.answer("Пока ничего подходящего не найдено")
        return
    lines = [f"• {row['title']} — {row['price'] or '?'} c. — {row['url']}" for row in rows]
    await message.answer("\n".join(lines))


@router.message(Command("check"))
async def cmd_check(message: Message, worker: Worker) -> None:
    await message.answer("🔍 Проверяю прямо сейчас...")
    await worker.poll_once()
    await message.answer("Готово. Смотри /status")


@router.message(Command("test"))
async def cmd_test(message: Message, client: SomonClient, track_urls: list[str]) -> None:
    outcome, html = await client.fetch(track_urls[0])
    if html is None:
        await message.answer(f"❌ Не удалось загрузить страницу: {outcome.value}")
        return
    listings, mode = parse_listing_page(html)
    if not listings:
        await message.answer("❌ Парсер не нашёл ни одной карточки — сайт мог измениться")
        return
    lines = [f"Режим парсинга: {mode.value}. Найдено карточек: {len(listings)}\n"]
    for listing in listings[:3]:
        lines.append(
            f"#{listing.id} {listing.title}\n"
            f"  цена={listing.price} комнаты={listing.rooms} этаж={listing.floor} "
            f"площадь={listing.area} промо={listing.is_promoted}"
        )
    await message.answer("\n\n".join(lines))


@router.message(Command("interval"))
async def cmd_interval(message: Message, command: CommandObject, worker: Worker) -> None:
    args = (command.args or "").strip()
    if not args.isdigit() or int(args) < 20:
        await message.answer("Интервал не может быть меньше 20 секунд. Использование: /interval 45")
        return
    worker.state.poll_interval = int(args)
    await message.answer(f"✅ Интервал опроса: {args} сек")


@router.message(Command("stats"))
async def cmd_stats(message: Message, conn: aiosqlite.Connection) -> None:
    since = datetime.now() - timedelta(days=7)
    stats = await db.get_stats_since(conn, since)
    avg_price = round(stats["avg_price"]) if stats["avg_price"] else "—"
    await message.answer(
        f"📊 Статистика за 7 дней:\n"
        f"Найдено всего: {stats['total_found']}\n"
        f"Прошло фильтр: {stats['total_matched']}\n"
        f"Средняя цена: {avg_price} c."
    )


@router.message(Command("export"))
async def cmd_export(message: Message, conn: aiosqlite.Connection) -> None:
    since = datetime.now() - timedelta(days=365)
    rows = await db.get_matched_since(conn, since)
    if not rows:
        await message.answer("Нет подходящих объявлений для экспорта")
        return
    columns = ("id", "title", "price", "rooms", "floor", "area", "district", "url", "found_at")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[column] for column in columns])
    file = BufferedInputFile(buffer.getvalue().encode("utf-8-sig"), filename="somon_matched.csv")
    await message.answer_document(file)


@router.callback_query(lambda c: c.data and c.data.startswith("block:"))
async def cb_block(callback: CallbackQuery, conn: aiosqlite.Connection) -> None:
    listing_id = int(callback.data.split(":", 1)[1])
    cursor = await conn.execute("SELECT author_url, author_name FROM listings WHERE id = ?", (listing_id,))
    row = await cursor.fetchone()
    if row is None or not row["author_url"]:
        await callback.answer("У этого объявления нет данных об авторе", show_alert=True)
        return
    await db.add_blocked_author(conn, row["author_url"], row["author_name"])
    await callback.answer(f"Заблокирован: {row['author_name'] or row['author_url']}")


@router.callback_query(lambda c: c.data and c.data.startswith("pause:"))
async def cb_pause(callback: CallbackQuery, worker: Worker) -> None:
    minutes = int(callback.data.split(":", 1)[1])
    worker.state.paused = True
    worker.state.paused_until = datetime.now() + timedelta(minutes=minutes)
    await callback.answer(f"Пауза на {minutes} минут")


@router.callback_query(lambda c: c.data and c.data.startswith("toggle:"))
async def cb_toggle(callback: CallbackQuery, conn: aiosqlite.Connection) -> None:
    key = callback.data.split(":", 1)[1]
    filters = await db.get_filters(conn)
    new_value = not getattr(filters, key)
    await db.set_setting_raw(conn, key, new_value)
    await callback.answer(f"{key} = {new_value}")
    if callback.message:
        updated = await db.get_filters(conn)
        await callback.message.edit_text(
            _format_filters(updated), parse_mode="HTML", reply_markup=filters_menu_keyboard(updated)
        )


@router.callback_query(lambda c: c.data == "clear_districts")
async def cb_clear_districts(callback: CallbackQuery, conn: aiosqlite.Connection) -> None:
    await db.set_setting_raw(conn, "districts_include", [])
    await callback.answer("Районы очищены")
    if callback.message:
        updated = await db.get_filters(conn)
        await callback.message.edit_text(
            _format_filters(updated), parse_mode="HTML", reply_markup=filters_menu_keyboard(updated)
        )


@router.callback_query(lambda c: c.data == "refresh_filters")
async def cb_refresh_filters(callback: CallbackQuery, conn: aiosqlite.Connection) -> None:
    filters = await db.get_filters(conn)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            _format_filters(filters), parse_mode="HTML", reply_markup=filters_menu_keyboard(filters)
        )
