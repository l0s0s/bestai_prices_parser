import json
import pytest

from app.services.provider_descriptions import (
    build_provider_descriptions,
    load_published_provider_domains,
)


@pytest.fixture()
def frontend_json_file(tmp_path, monkeypatch):
    path = tmp_path / "providers.json"
    monkeypatch.setattr("app.settings.settings.frontend_json_path", str(path))
    return path


def _price_row(domain):
    return {
        "provider_name": domain,
        "provider_domain": domain,
        "provider_url": f"https://{domain}",
        "model_name": "some-model",
        "canonical_model_id": "vendor/some-model",
        "input_price_usd_per_1m": 1.0,
        "output_price_usd_per_1m": 2.0,
        "trust_status": "green",
        "source_url": f"https://{domain}/pricing",
        "last_checked_at": "2026-08-13T00:00:00Z",
        "payment_methods": [],
    }


def test_load_published_provider_domains_missing_file_returns_empty(frontend_json_file):
    assert load_published_provider_domains() == set()


def test_load_published_provider_domains_reads_from_providers_json(frontend_json_file):
    frontend_json_file.write_text(
        json.dumps([_price_row("a.com"), _price_row("b.com"), _price_row("a.com")]),
        encoding="utf-8",
    )
    assert load_published_provider_domains() == {"a.com", "b.com"}


def test_build_provider_descriptions_unfiltered_by_default():
    descriptions = {
        "a.com": {"description_ru": "ru-a", "description_en": "en-a"},
        "b.com": {"description_ru": "ru-b", "description_en": "en-b"},
    }
    rows = build_provider_descriptions(descriptions=descriptions)
    assert [r["provider_domain"] for r in rows] == ["a.com", "b.com"]


def test_build_provider_descriptions_filters_to_published_domains():
    descriptions = {
        "a.com": {"description_ru": "ru-a", "description_en": "en-a"},
        "stale.com": {"description_ru": "ru-stale", "description_en": "en-stale"},
    }
    rows = build_provider_descriptions(descriptions=descriptions, published_domains={"a.com"})
    assert [r["provider_domain"] for r in rows] == ["a.com"]


def test_build_provider_descriptions_empty_published_domains_yields_no_rows():
    descriptions = {"a.com": {"description_ru": "ru-a", "description_en": "en-a"}}
    rows = build_provider_descriptions(descriptions=descriptions, published_domains=set())
    assert rows == []
