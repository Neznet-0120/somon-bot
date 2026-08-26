from __future__ import annotations

import asyncio
import logging
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,tg;q=0.8",
    "Referer": "https://somon.tj/",
}

_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2


class FetchOutcome(str, Enum):
    OK = "ok"
    RATE_LIMITED = "rate_limited"  # 403 / 429 / антибот
    ERROR = "error"  # сетевая ошибка / таймаут / прочие статусы


class SomonClient:
    """HTTP-клиент для somon.tj с постоянной сессией, cookie jar и ретраями."""

    def __init__(self, timeout: int, proxy_url: str | None = None) -> None:
        self._client = httpx.AsyncClient(
            headers=_DEFAULT_HEADERS,
            timeout=timeout,
            proxy=proxy_url or None,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> tuple[FetchOutcome, str | None]:
        """Возвращает (исход, html). html есть только при FetchOutcome.OK."""
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._client.get(url)
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning("Таймаут запроса к %s (попытка %d/%d)", url, attempt, _MAX_ATTEMPTS)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Сетевая ошибка %s (попытка %d/%d): %s", url, attempt, _MAX_ATTEMPTS, exc)
            else:
                if response.status_code in (403, 429):
                    logger.warning("Антибот-ответ %d от %s", response.status_code, url)
                    return FetchOutcome.RATE_LIMITED, None
                if response.status_code != 200:
                    logger.warning("Неожиданный статус %d от %s", response.status_code, url)
                    last_error = None
                else:
                    return FetchOutcome.OK, response.text
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_DELAY_SECONDS * attempt)
        if last_error is not None:
            logger.error("Не удалось получить %s после %d попыток: %s", url, _MAX_ATTEMPTS, last_error)
        return FetchOutcome.ERROR, None
