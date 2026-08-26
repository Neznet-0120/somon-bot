from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from bot.keyboards import listing_notification_keyboard
from scraper.models import Listing

logger = logging.getLogger(__name__)

_SEND_INTERVAL_SECONDS = 1.0


def format_caption(listing: Listing) -> str:
    title = html.escape(listing.title)
    lines = [f"🏠 <b>{title}</b>", ""]

    if listing.price is not None:
        lines.append(f"💰 <b>{listing.price:,} сомони/мес</b>".replace(",", " "))
    else:
        lines.append("💰 <b>Цена не указана</b>")

    if listing.district:
        lines.append(f"📍 {html.escape(listing.district)}")

    facts = []
    if listing.floor is not None:
        facts.append(f"{listing.floor} этаж")
    if listing.area is not None:
        facts.append(f"{listing.area:g} м²")
    if listing.rooms is not None:
        facts.append(f"{listing.rooms} комн.")
    if facts:
        lines.append(f"🏢 {' · '.join(facts)}")

    if listing.author_name:
        lines.append(f"👤 {html.escape(listing.author_name)}")

    found_at_str = listing.found_at.strftime("%d.%m %H:%M")
    time_line = f"🕐 Найдено: {found_at_str}"
    if listing.posted_raw:
        time_line += f" (опубликовано: {html.escape(listing.posted_raw)})"
    lines.append(time_line)

    lines.append("")
    lines.append(f"🔗 {listing.url}")
    return "\n".join(lines)


class Notifier:
    """Очередь отправки уведомлений с интервалом ~1 сек и retry при RetryAfter."""

    def __init__(self, bot: Bot, admin_chat_id: int) -> None:
        self._bot = bot
        self._admin_chat_id = admin_chat_id
        self._queue: asyncio.Queue[Listing] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def enqueue(self, listing: Listing) -> None:
        await self._queue.put(listing)

    async def _run(self) -> None:
        while True:
            listing = await self._queue.get()
            try:
                await self._send(listing)
            except Exception:
                logger.exception("Не удалось отправить уведомление о %s", listing.id)
            await asyncio.sleep(_SEND_INTERVAL_SECONDS)

    async def _send(self, listing: Listing) -> None:
        caption = format_caption(listing)
        keyboard = listing_notification_keyboard(listing)
        try:
            await self._send_once(listing, caption, keyboard)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            await self._send_once(listing, caption, keyboard)

    async def _send_once(self, listing: Listing, caption: str, keyboard: InlineKeyboardMarkup) -> None:
        if listing.image_url:
            try:
                await self._bot.send_photo(
                    self._admin_chat_id, photo=listing.image_url, caption=caption,
                    parse_mode="HTML", reply_markup=keyboard,
                )
                return
            except TelegramBadRequest:
                logger.warning("Не удалось отправить фото для %s, отправляю текстом", listing.id)
        await self._bot.send_message(
            self._admin_chat_id, text=caption, parse_mode="HTML",
            reply_markup=keyboard, disable_web_page_preview=False,
        )

    async def send_admin_alert(self, text: str) -> None:
        try:
            await self._bot.send_message(self._admin_chat_id, text=text)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            await self._bot.send_message(self._admin_chat_id, text=text)
