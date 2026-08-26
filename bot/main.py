from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot import handlers
from bot.config import get_settings
from bot.middlewares import AdminOnlyMiddleware
from bot.notifier import Notifier
from core import db
from core.filters import Filters
from core.worker import Worker, WorkerState
from scraper.client import SomonClient


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _default_filters_from_settings(settings) -> Filters:
    return Filters(
        price_min=settings.price_min,
        price_max=settings.price_max,
        rooms=settings.rooms,
        area_min=settings.area_min,
        area_max=settings.area_max,
        floor_min=settings.floor_min,
        floor_max=settings.floor_max,
        districts_include=settings.districts_include,
        districts_exclude=settings.districts_exclude,
        keywords_exclude=settings.keywords_exclude,
        only_with_photo=settings.only_with_photo,
        skip_promoted=settings.skip_promoted,
    )


async def main() -> None:
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    conn = await db.init_db(settings.db_path, _default_filters_from_settings(settings))
    client = SomonClient(timeout=settings.request_timeout, proxy_url=settings.proxy_url)
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    notifier = Notifier(bot, settings.admin_chat_id)

    was_cold_start = await db.is_cold_start(conn)
    state = WorkerState(poll_interval=settings.poll_interval, max_pages=settings.max_pages)
    worker = Worker(
        conn=conn,
        client=client,
        track_urls=settings.track_urls,
        state=state,
        notify=notifier.enqueue,
        alert_admin=notifier.send_admin_alert,
    )

    dp.include_router(handlers.router)
    dp.message.middleware(AdminOnlyMiddleware(settings.admin_chat_id))
    dp.callback_query.middleware(AdminOnlyMiddleware(settings.admin_chat_id))

    await notifier.start()

    if was_cold_start:
        total = await worker.cold_start()
        await bot.send_message(
            settings.admin_chat_id,
            f"🚀 Бот запущен, отслеживаю {total} объявлений. Новые уведомления начнутся со следующего цикла.",
        )
        logger.info("Холодный старт: записано %d объявлений", total)
    else:
        await bot.send_message(settings.admin_chat_id, "🚀 Бот перезапущен, продолжаю отслеживание.")

    worker_task = asyncio.create_task(worker.run_forever())

    try:
        await dp.start_polling(
            bot,
            conn=conn,
            worker=worker,
            client=client,
            notifier=notifier,
            track_urls=settings.track_urls,
        )
    finally:
        worker_task.cancel()
        await notifier.stop()
        await client.close()
        await conn.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
