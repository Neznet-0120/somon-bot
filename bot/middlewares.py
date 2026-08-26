from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update


class AdminOnlyMiddleware(BaseMiddleware):
    """Пропускает апдейты только от ADMIN_CHAT_ID. Остальным отвечает и игнорирует."""

    def __init__(self, admin_chat_id: int) -> None:
        self._admin_chat_id = admin_chat_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat_id = _extract_chat_id(event)
        if chat_id is None or chat_id == self._admin_chat_id:
            return await handler(event, data)

        message = getattr(event, "message", None) or getattr(event, "callback_query", None)
        target = getattr(message, "message", message) if message else None
        if target is not None and hasattr(target, "answer"):
            await target.answer("Это личный бот.")
        return None


def _extract_chat_id(event: TelegramObject) -> int | None:
    if isinstance(event, Update):
        if event.message:
            return event.message.chat.id
        if event.callback_query and event.callback_query.message:
            return event.callback_query.message.chat.id
    return None
