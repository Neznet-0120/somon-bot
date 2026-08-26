from scraper.normalize import contains_any, normalize_text, parse_price, parse_slug, parse_title


def test_normalize_text_replaces_tajik_diacritics() -> None:
    assert normalize_text("Фирдавсӣ") == normalize_text("Фирдавси") == "фирдавси"
    assert normalize_text("Шоҳмансур") == normalize_text("Шохмансур") == "шохмансур"


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  Сино   район  ") == "сино район"


def test_parse_price_strips_spaces_and_currency() -> None:
    assert parse_price("8 999 c.") == 8999
    assert parse_price("10 000 c.") == 10000
    assert parse_price("") is None
    assert parse_price(None) is None


def test_parse_title_extracts_all_fields() -> None:
    result = parse_title("2-комн. квартира, 9 этаж, 70м², Зарафшон")
    assert result == {"rooms": 2, "floor": 9, "area": 70.0, "district": "Зарафшон"}


def test_parse_title_handles_comma_decimal_area() -> None:
    result = parse_title("3-комн. квартира, 4 этаж, 70,5м², Сино")
    assert result["area"] == 70.5


def test_parse_title_returns_none_fields_on_mismatch() -> None:
    result = parse_title("какой-то произвольный текст")
    assert result == {"rooms": None, "floor": None, "area": None, "district": None}


def test_parse_slug_extracts_fields() -> None:
    result = parse_slug("2-komn-kvartira-10-etazh-90m2-sozidanie-paikar")
    assert result == {"rooms": 2, "floor": 10, "area": 90.0, "district": "sozidanie paikar"}


def test_parse_slug_handles_basement_floor() -> None:
    result = parse_slug("2-komn-kvartira-tsokolnyi-etazh-69-m2-8mkrn-bolosh")
    assert result == {"rooms": 2, "floor": None, "area": 69.0, "district": "8mkrn bolosh"}


def test_parse_slug_returns_none_for_non_apartment() -> None:
    assert parse_slug("toyota-camry-2025") is None


def test_contains_any_matches_with_diacritics() -> None:
    assert contains_any("Исмоили Сомонӣ", ["Исмоили Сомони"]) is True
    assert contains_any("Центр города", ["Сино", "Шохмансур"]) is False
