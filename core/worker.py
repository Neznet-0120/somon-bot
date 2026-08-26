from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite

from core import db
from core.filters import matches_filters
from scraper.client import FetchOutcome, SomonClient
from scraper.models import Listing
from scraper.parser import ParseMode, detect_ban_banner, parse_listing_page

logger = logging.getLogger(__name__)

_JITTER_MAX_SECONDS = 15
_DEBUG_DIR = Path("debug")
_MAX_DEBUG_FILES = 5
_BACKOFF_STEPS_MINUTES = [1, 2, 4, 8, 16, 30]
_RATE_LIMIT_COOLDOWN_MINUTES = 30
_RATE_LIMIT_INTERVAL_MULTIPLIER = 3
_SILENCE_THRESHOLD_CYCLES = 3
_ADMIN_ALERT_COOLDOWN_MINUTES = 60
_BURST_NEW_RATIO = 0.8

NotifyCallback = Callable[[Listing], Awaitable[None]]
AlertCallback = Callable[[str], Awaitable[None]]


@dataclass
class WorkerState:
    paused: bool = False
    paused_until: datetime | None = None
    poll_interval: int = 45
    max_pages: int = 1
    backoff_level: int = 0
    rate_limited_until: datetime | None = None
    last_check_at: datetime | None = None
    last_error: str | None = None
    parse_mode: ParseMode = ParseMode.JSON
    total_found_today: int = 0
    total_matched_today: int = 0
    silence_streak: int = 0
    last_admin_alert_at: dict[str, datetime] = field(default_factory=dict)


class Worker:
    def __init__(
        self,
        conn: aiosqlite.Connection,
        client: SomonClient,
        track_urls: list[str],
        state: WorkerState,
        notify: NotifyCallback,
        alert_admin: AlertCallback,
        debug_dir: Path = _DEBUG_DIR,
    ) -> None:
        self._conn = conn
        self._client = client
        self._track_urls = track_urls
        self.state = state
        self._notify = notify
        self._alert_admin = alert_admin
        self._debug_dir = debug_dir

    async def cold_start(self) -> int:
        """Первый запуск: запоминает все текущие ID без уведомлений. Возвращает их число."""
        total = 0
        for url in self._track_urls:
            outcome, html = await self._client.fetch(url)
            if outcome is not FetchOutcome.OK or html is None:
                continue
            listings, mode = parse_listing_page(html)
            self.state.parse_mode = mode
            await db.record_listings(self._conn, [(listing, False) for listing in listings])
            total += len(listings)
        return total

    async def run_forever(self) -> None:
        while True:
            if self._is_effectively_paused():
                await asyncio.sleep(min(self.state.poll_interval, 30))
                continue
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Необработанная ошибка в цикле опроса, продолжаю работу")
                self.state.last_error = "Внутренняя ошибка цикла опроса (см. логи)"
            await asyncio.sleep(self._next_sleep_seconds())

    def _is_effectively_paused(self) -> bool:
        if not self.state.paused:
            return False
        if self.state.paused_until is not None and datetime.now() >= self.state.paused_until:
            self.state.paused = False
            self.state.paused_until = None
            return False
        return True

    def _next_sleep_seconds(self) -> float:
        jitter = random.uniform(0, _JITTER_MAX_SECONDS)
        if self.state.rate_limited_until and datetime.now() < self.state.rate_limited_until:
            return self.state.poll_interval * _RATE_LIMIT_INTERVAL_MULTIPLIER + jitter
        if self.state.backoff_level > 0:
            step_index = min(self.state.backoff_level - 1, len(_BACKOFF_STEPS_MINUTES) - 1)
            return _BACKOFF_STEPS_MINUTES[step_index] * 60 + jitter
        return self.state.poll_interval + jitter

    async def poll_once(self) -> None:
        self.state.last_check_at = datetime.now()
        any_new_ids_this_cycle = False

        for url in self._track_urls:
            new_ids_for_url = await self._poll_url(url)
            any_new_ids_this_cycle = any_new_ids_this_cycle or new_ids_for_url

        if any_new_ids_this_cycle:
            self.state.silence_streak = 0
        else:
            self.state.silence_streak += 1
            if self.state.silence_streak >= _SILENCE_THRESHOLD_CYCLES:
                await self._alert_once(
                    "silence",
                    "⚠️ Уже несколько циклов подряд нет ни одного нового объявления. "
                    "Возможно, парсер сломался или сайт блокирует запросы. Проверь /test.",
                )

    async def _poll_url(self, url: str) -> bool:
        outcome, html = await self._client.fetch(url)

        if outcome is FetchOutcome.RATE_LIMITED:
            await self._handle_rate_limited()
            return False
        if outcome is not FetchOutcome.OK or html is None:
            self.state.backoff_level = min(self.state.backoff_level + 1, len(_BACKOFF_STEPS_MINUTES))
            self.state.last_error = f"Не удалось получить {url}"
            return False

        if detect_ban_banner(html):
            await self._handle_rate_limited(banner=True)
            return False

        listings = await self._parse_safely(html)
        if listings is None:
            return False

        if self.state.parse_mode is ParseMode.FALLBACK:
            _dump_debug_html(self._debug_dir, html, "fallback")
            await self._alert_once(
                "fallback",
                "⚠️ JSON-структура сайта изменилась, работаю в упрощённом режиме — "
                "без фильтра по цене. Нужно чинить scraper/parser.py",
            )

        new_ids = await self._process_listings(listings)

        if listings and len(new_ids) / len(listings) >= _BURST_NEW_RATIO and self.state.max_pages > 1:
            outcome2, html2 = await self._client.fetch(_with_page(url, 2))
            if outcome2 is FetchOutcome.OK and html2 is not None and not detect_ban_banner(html2):
                more_listings = await self._parse_safely(html2)
                if more_listings is not None:
                    more_new_ids = await self._process_listings(more_listings)
                    new_ids |= more_new_ids

        self.state.backoff_level = 0
        return bool(new_ids)

    async def _parse_safely(self, html: str) -> list[Listing] | None:
        """Парсинг не должен ронять процесс. Любая ошибка — дамп HTML и переход к следующему циклу."""
        try:
            listings, mode = parse_listing_page(html)
        except Exception:
            logger.exception("Ошибка парсинга страницы")
            _dump_debug_html(self._debug_dir, html, "parse_error")
            self.state.last_error = "Ошибка парсинга страницы (см. debug/)"
            return None
        self.state.parse_mode = mode
        return listings

    async def _process_listings(self, listings: list[Listing]) -> set[int]:
        if not listings:
            return set()
        ids = [listing.id for listing in listings]
        seen = await db.get_seen_ids(self._conn, ids)
        new_listings = [listing for listing in listings if listing.id not in seen]
        if not new_listings:
            return set()

        filters = await db.get_filters(self._conn)
        to_record: list[tuple[Listing, bool]] = []
        to_notify: list[Listing] = []
        for listing in new_listings:
            matched = matches_filters(listing, filters)
            to_record.append((listing, matched))
            if matched:
                to_notify.append(listing)

        await db.record_listings(self._conn, to_record)

        for listing in sorted(to_notify, key=lambda item: item.id):
            await self._notify(listing)
            await db.mark_notified(self._conn, listing.id)

        return {listing.id for listing in new_listings}

    async def _handle_rate_limited(self, banner: bool = False) -> None:
        self.state.rate_limited_until = datetime.now() + timedelta(minutes=_RATE_LIMIT_COOLDOWN_MINUTES)
        self.state.last_error = "Антибот-защита (баннер)" if banner else "Антибот-защита (403/429)"
        await self._alert_once(
            "rate_limited",
            f"🚫 {self.state.last_error}. Интервал опроса увеличен в "
            f"{_RATE_LIMIT_INTERVAL_MULTIPLIER} раза на {_RATE_LIMIT_COOLDOWN_MINUTES} минут.",
        )

    async def _alert_once(self, key: str, text: str) -> None:
        last = self.state.last_admin_alert_at.get(key)
        now = datetime.now()
        if last is not None and now - last < timedelta(minutes=_ADMIN_ALERT_COOLDOWN_MINUTES):
            return
        self.state.last_admin_alert_at[key] = now
        await self._alert_admin(text)


def _with_page(url: str, page: int) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}page={page}"


def _dump_debug_html(debug_dir: Path, html: str, reason: str) -> None:
    """Дамп HTML при ошибке/деградации парсера. Хранит последние 5 файлов."""
    debug_dir.mkdir(exist_ok=True, parents=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = debug_dir / f"{timestamp}_{reason}.html"
    try:
        path.write_text(html, encoding="utf-8")
        old_files = sorted(debug_dir.glob("*.html"), key=lambda p: p.stat().st_mtime)
        for old_file in old_files[:-_MAX_DEBUG_FILES]:
            old_file.unlink(missing_ok=True)
    except OSError:
        logger.exception("Не удалось сохранить дамп в %s", debug_dir)
