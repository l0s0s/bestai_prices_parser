import json
import pytest

from app.services.api_descriptions import load_api_vendors, build_api_descriptions


@pytest.fixture()
def vendors_file(tmp_path, monkeypatch):
    path = tmp_path / "api_vendors.json"
    monkeypatch.setattr("app.settings.settings.api_vendors_file", str(path))
    return path


def test_load_api_vendors_missing_file_returns_empty(vendors_file):
    assert load_api_vendors() == {}


def test_load_api_vendors_round_trips(vendors_file):
    data = {"anthropic": "Anthropic", "generic": "AI"}
    vendors_file.write_text(json.dumps(data), encoding="utf-8")
    assert load_api_vendors() == data


def test_build_api_descriptions_renders_expected_anthropic_card(vendors_file):
    rows = build_api_descriptions({"anthropic": "Anthropic"})
    assert len(rows) == 1
    row = rows[0]
    assert row["vendor_slug"] == "anthropic"
    assert row["display_name"] == "Anthropic"
    assert row["title_ru"] == "Дешёвый Anthropic API"
    assert row["description_ru"] == (
        "Здесь показаны предложения Anthropic API от разных поставщиков и агрегаторов. "
        "Сравните цену входных и выходных токенов, проверьте поддержку нужных функций и "
        "выберите самый выгодный API-маршрут для подключения модели к приложению, боту, "
        "SaaS-продукту или внутреннему AI-инструменту. Таблица помогает найти модель "
        "дешевле официальной цены и быстро перейти к поставщику с подходящими условиями. "
        "Вы можете сравнить доступные способы оплаты, рейтинг поставщика, отзывы, возраст "
        "сервиса, поддерживаемые возможности модели, лимиты запросов и другие важные "
        "условия перед выбором API-провайдера."
    )
    assert row["title_en"] == "Cheap Anthropic API"


def test_build_api_descriptions_generic_vendor_uses_ai_name(vendors_file):
    rows = build_api_descriptions({"generic": "AI"})
    row = rows[0]
    assert row["title_ru"] == "Дешёвый AI API"
    assert row["description_ru"].startswith("Здесь показаны предложения AI API")
    assert row["title_en"] == "Cheap AI API"


def test_build_api_descriptions_sorted_by_slug(vendors_file):
    rows = build_api_descriptions({"openai": "OpenAI", "anthropic": "Anthropic"})
    assert [r["vendor_slug"] for r in rows] == ["anthropic", "openai"]


def test_load_api_vendors_normalizes_em_dash(vendors_file):
    data = {"acme": "Acme — API"}
    vendors_file.write_text(json.dumps(data), encoding="utf-8")
    assert load_api_vendors() == {"acme": "Acme – API"}


def test_build_api_descriptions_normalizes_em_dash_in_display_name(vendors_file):
    data = {"acme": "Acme — API"}
    vendors_file.write_text(json.dumps(data), encoding="utf-8")
    rows = build_api_descriptions()
    assert rows[0]["display_name"] == "Acme – API"
    assert "—" not in rows[0]["title_ru"]
    assert "—" not in rows[0]["title_en"]


def test_build_api_descriptions_reads_from_file_when_no_vendors_passed(vendors_file):
    data = {"anthropic": "Anthropic"}
    vendors_file.write_text(json.dumps(data), encoding="utf-8")
    rows = build_api_descriptions()
    assert len(rows) == 1
    assert rows[0]["vendor_slug"] == "anthropic"


def test_build_api_descriptions_normalizes_em_dash(vendors_file, monkeypatch):
    import app.services.api_descriptions as mod

    monkeypatch.setattr(mod, "RU_BODY_TEMPLATE", "{vendor} — тест")
    rows = build_api_descriptions({"anthropic": "Anthropic"})
    assert rows[0]["description_ru"] == "Anthropic – тест"
