import pytest

from core import db
from core.filters import Filters
from core.worker import Worker, WorkerState
from scraper.client import FetchOutcome
from scraper.models import Listing

URL = "https://somon.tj/nedvizhimost/arenda-kvartir/dushanbe/"


class FakeClient:
    def __init__(self) -> None:
        self.responses: dict[str, tuple[FetchOutcome, str | None]] = {}
        self.calls: list[str] = []

    def set_response(self, url: str, outcome: FetchOutcome, html: str | None) -> None:
        self.responses[url] = (outcome, html)

    async def fetch(self, url: str) -> tuple[FetchOutcome, str | None]:
        self.calls.append(url)
        return self.responses.get(url, (FetchOutcome.ERROR, None))


def make_listing_html(ids: list[int], promoted_ids: set[int] | None = None) -> str:
    """Собирает минимальный HTML с RSC-чанком, который парсер распознает."""
    import json

    promoted_ids = promoted_ids or set()
    adverts = []
    for listing_id in ids:
        adverts.append(
            {
                "id": listing_id,
                "title": "2-комн. квартира, 5 этаж, 60м², Сино",
                "price": "5 000 c.",
                "start_price": "",
                "currency": "TJS",
                "price_without_currency": "5000",
                "first_thumb": "https://cdntj.somon.tj/img.webp",
                "img_count": 3,
                "published": "Сегодня",
                "url": f"/adv/{listing_id}_2-komn-kvartira-5-etazh-60m2-sino/",
                "ad_type": {"type": "premium" if listing_id in promoted_ids else "regular", "text": ""},
                "user": {"id": 999, "name": "Тест"},
            }
        )
    payload = {"adverts": adverts}
    payload_json = json.dumps(payload, ensure_ascii=False)
    chunk = json.dumps(f"5c:{payload_json}")
    return f"<html><body><script>self.__next_f.push([1,{chunk}])</script></body></html>"


@pytest.fixture
async def conn(tmp_path):
    default_filters = Filters(price_min=1000, price_max=9000, rooms=[1, 2, 3], skip_promoted=True)
    connection = await db.init_db(str(tmp_path / "test.db"), default_filters)
    yield connection
    await connection.close()


@pytest.fixture
def notified():
    items: list[Listing] = []

    async def _notify(listing: Listing) -> None:
        items.append(listing)

    _notify.items = items  # type: ignore[attr-defined]
    return _notify


@pytest.fixture
def alerts():
    messages: list[str] = []

    async def _alert(text: str) -> None:
        messages.append(text)

    _alert.messages = messages  # type: ignore[attr-defined]
    return _alert


def make_worker(conn, client, notify, alert, tmp_path, **state_kwargs) -> Worker:
    state = WorkerState(poll_interval=45, max_pages=1, **state_kwargs)
    return Worker(conn, client, [URL], state, notify, alert, debug_dir=tmp_path / "debug")


async def test_cold_start_records_without_notifying(conn, notified, alerts, tmp_path) -> None:
    client = FakeClient()
    client.set_response(URL, FetchOutcome.OK, make_listing_html([1, 2, 3]))
    worker = make_worker(conn, client, notified, alerts, tmp_path)

    total = await worker.cold_start()

    assert total == 3
    assert notified.items == []
    assert await db.is_cold_start(conn) is False


async def test_poll_once_notifies_new_matching_listing(conn, notified, alerts, tmp_path) -> None:
    client = FakeClient()
    client.set_response(URL, FetchOutcome.OK, make_listing_html([1, 2]))
    worker = make_worker(conn, client, notified, alerts, tmp_path)
    await worker.cold_start()

    client.set_response(URL, FetchOutcome.OK, make_listing_html([1, 2, 3]))
    await worker.poll_once()

    assert [item.id for item in notified.items] == [3]


async def test_poll_once_does_not_renotify_seen_listing(conn, notified, alerts, tmp_path) -> None:
    client = FakeClient()
    client.set_response(URL, FetchOutcome.OK, make_listing_html([1]))
    worker = make_worker(conn, client, notified, alerts, tmp_path)
    await worker.cold_start()

    await worker.poll_once()
    await worker.poll_once()

    assert notified.items == []


async def test_promoted_listing_not_notified_when_skip_promoted(conn, notified, alerts, tmp_path) -> None:
    client = FakeClient()
    client.set_response(URL, FetchOutcome.OK, make_listing_html([]))
    worker = make_worker(conn, client, notified, alerts, tmp_path)
    await worker.cold_start()

    client.set_response(URL, FetchOutcome.OK, make_listing_html([10], promoted_ids={10}))
    await worker.poll_once()

    assert notified.items == []
    seen = await db.get_seen_ids(conn, [10])
    assert seen == {10}  # записан в seen, но не уведомлён


async def test_rate_limited_triggers_backoff_and_single_alert(conn, notified, alerts, tmp_path) -> None:
    client = FakeClient()
    client.set_response(URL, FetchOutcome.RATE_LIMITED, None)
    worker = make_worker(conn, client, notified, alerts, tmp_path)

    await worker.poll_once()
    await worker.poll_once()

    assert worker.state.rate_limited_until is not None
    assert len(alerts.messages) == 1  # cooldown не даёт слать повторно


async def test_silence_threshold_alerts_admin(conn, notified, alerts, tmp_path) -> None:
    client = FakeClient()
    client.set_response(URL, FetchOutcome.OK, make_listing_html([1]))
    worker = make_worker(conn, client, notified, alerts, tmp_path)
    await worker.cold_start()

    client.set_response(URL, FetchOutcome.OK, make_listing_html([1]))  # тот же id, ничего нового
    for _ in range(3):
        await worker.poll_once()

    assert any("сломался" in m or "нового объявления" in m for m in alerts.messages)


async def test_fallback_mode_alerts_admin(conn, notified, alerts, tmp_path) -> None:
    client = FakeClient()
    broken_html = "<html><body><a href=\"/adv/1_2-komn-kvartira-5-etazh-60m2-sino/\"></a></body></html>"
    client.set_response(URL, FetchOutcome.OK, broken_html)
    worker = make_worker(conn, client, notified, alerts, tmp_path=tmp_path)

    await worker.poll_once()

    assert any("упрощённом режиме" in m for m in alerts.messages)
