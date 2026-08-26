from pathlib import Path

from scraper.parser import ParseMode, detect_ban_banner, parse_listing_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_json_path_parses_real_page() -> None:
    html = (FIXTURES / "listing_page.html").read_text(encoding="utf-8")
    listings, mode = parse_listing_page(html)

    assert mode is ParseMode.JSON
    assert len(listings) == 60

    ids = [item.id for item in listings]
    assert len(ids) == len(set(ids))


def test_json_path_extracts_fields_correctly() -> None:
    html = (FIXTURES / "listing_page.html").read_text(encoding="utf-8")
    listings, _ = parse_listing_page(html)

    by_id = {item.id: item for item in listings}
    listing = by_id[16980220]

    assert listing.title == "2-комн. квартира, 6 этаж, 84м², Шохмансур"
    assert listing.price == 8999
    assert listing.price_old == 11000
    assert listing.currency == "TJS"
    assert listing.rooms == 2
    assert listing.floor == 6
    assert listing.area == 84.0
    assert listing.district == "Шохмансур"
    assert listing.is_promoted is True
    assert listing.url == "https://somon.tj/adv/16980220_2-komn-kvartira-6-etazh-84m2-shokhmansur/"
    assert listing.author_url == "/items/author/17821615/"
    assert listing.photos_count == 12


def test_json_path_marks_promoted_correctly() -> None:
    html = (FIXTURES / "listing_page.html").read_text(encoding="utf-8")
    listings, _ = parse_listing_page(html)

    promoted_count = sum(1 for item in listings if item.is_promoted)
    regular_count = sum(1 for item in listings if not item.is_promoted)

    assert promoted_count == 37  # 14 VIP + 23 ТОП
    assert regular_count == 23


def test_json_path_price_without_discount_has_no_old_price() -> None:
    html = (FIXTURES / "listing_page.html").read_text(encoding="utf-8")
    listings, _ = parse_listing_page(html)

    by_id = {item.id: item for item in listings}
    listing = by_id[16798740]

    assert listing.price == 8200
    assert listing.price_old is None


def test_fallback_path_used_when_json_missing() -> None:
    html = (FIXTURES / "listing_page_broken.html").read_text(encoding="utf-8")
    listings, mode = parse_listing_page(html)

    assert mode is ParseMode.FALLBACK
    assert len(listings) > 0


def test_fallback_path_extracts_id_rooms_floor_area_district() -> None:
    html = (FIXTURES / "listing_page_broken.html").read_text(encoding="utf-8")
    listings, _ = parse_listing_page(html)

    by_id = {item.id: item for item in listings}
    listing = by_id[12711965]

    assert listing.rooms == 2
    assert listing.floor == 10
    assert listing.area == 90.0
    assert listing.district == "sozidanie paikar"
    assert listing.price is None
    assert listing.author_name is None
    assert listing.is_promoted is False


def test_fallback_path_skips_non_apartment_links() -> None:
    html = (FIXTURES / "listing_page_broken.html").read_text(encoding="utf-8")
    listings, _ = parse_listing_page(html)

    ids = {item.id for item in listings}
    assert 16341105 not in ids  # toyota-camry-2025, не квартира


def test_ban_banner_not_falsely_detected_on_real_page() -> None:
    html = (FIXTURES / "listing_page.html").read_text(encoding="utf-8")
    # Фраза "аккаунт был заблокирован" реально есть в бандле переводов
    # (i18n-ключ youBlocked), но это не значит, что бота забанили.
    assert detect_ban_banner(html) is False


def test_ban_banner_detected_when_actually_present() -> None:
    html = (FIXTURES / "listing_page.html").read_text(encoding="utf-8")
    banner_html = html + '<div class="banner">Ваш аккаунт был заблокирован на somon.tj</div>'
    assert detect_ban_banner(banner_html) is True
