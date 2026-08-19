import json
import pytest

from app.services.auth_providers import (
    load_auth_providers,
    save_auth_providers,
    sync_auth_providers_into_frontend_json,
)


@pytest.fixture()
def auth_providers_file(tmp_path, monkeypatch):
    path = tmp_path / "auth_providers.json"
    monkeypatch.setattr("app.settings.settings.auth_providers_file", str(path))
    return path


@pytest.fixture()
def frontend_json_file(tmp_path, monkeypatch):
    path = tmp_path / "providers.json"
    monkeypatch.setattr("app.settings.settings.frontend_json_path", str(path))
    return path


def _row(domain, model_name="some-model", canonical_model_id="vendor/some-model", **overrides):
    row = {
        "provider_name": domain,
        "provider_domain": domain,
        "provider_url": f"https://{domain}",
        "model_name": model_name,
        "canonical_model_id": canonical_model_id,
        "input_price_usd_per_1m": 1.0,
        "output_price_usd_per_1m": 2.0,
        "trust_status": "green",
        "source_url": f"https://{domain}/pricing",
        "last_checked_at": "2026-08-13T00:00:00Z",
        "payment_methods": [],
    }
    row.update(overrides)
    return row


def test_load_auth_providers_missing_file_returns_empty(auth_providers_file):
    assert load_auth_providers() == []


def test_save_then_load_round_trips(auth_providers_file):
    rows = [_row("gated.com")]
    save_auth_providers(rows)
    assert load_auth_providers() == rows


def test_sync_missing_frontend_json_raises(auth_providers_file, frontend_json_file):
    save_auth_providers([_row("gated.com")])
    with pytest.raises(FileNotFoundError):
        sync_auth_providers_into_frontend_json()


def test_sync_adds_rows_not_present_in_main_file(auth_providers_file, frontend_json_file):
    frontend_json_file.write_text(json.dumps([_row("open.com")]), encoding="utf-8")
    save_auth_providers([_row("gated.com")])

    added = sync_auth_providers_into_frontend_json()

    rows = json.loads(frontend_json_file.read_text(encoding="utf-8"))
    assert added == 1
    assert {r["provider_domain"] for r in rows} == {"open.com", "gated.com"}


def test_sync_skips_rows_already_present_by_domain_and_canonical_model_id(auth_providers_file, frontend_json_file):
    frontend_json_file.write_text(json.dumps([_row("gated.com")]), encoding="utf-8")
    save_auth_providers([_row("gated.com")])

    added = sync_auth_providers_into_frontend_json()

    rows = json.loads(frontend_json_file.read_text(encoding="utf-8"))
    assert added == 0
    assert len(rows) == 1


def test_sync_falls_back_to_model_name_when_canonical_id_missing(auth_providers_file, frontend_json_file):
    existing = _row("gated.com", model_name="mystery-model", canonical_model_id=None)
    frontend_json_file.write_text(json.dumps([existing]), encoding="utf-8")
    save_auth_providers([_row("gated.com", model_name="mystery-model", canonical_model_id=None)])

    added = sync_auth_providers_into_frontend_json()

    assert added == 0


def test_sync_treats_different_models_on_same_domain_as_distinct(auth_providers_file, frontend_json_file):
    frontend_json_file.write_text(
        json.dumps([_row("gated.com", model_name="model-a", canonical_model_id="vendor/model-a")]),
        encoding="utf-8",
    )
    save_auth_providers([_row("gated.com", model_name="model-b", canonical_model_id="vendor/model-b")])

    added = sync_auth_providers_into_frontend_json()

    rows = json.loads(frontend_json_file.read_text(encoding="utf-8"))
    assert added == 1
    assert len(rows) == 2


def test_sync_does_not_overwrite_existing_row_fields(auth_providers_file, frontend_json_file):
    frontend_json_file.write_text(
        json.dumps([_row("gated.com", input_price_usd_per_1m=99.0)]), encoding="utf-8"
    )
    save_auth_providers([_row("gated.com", input_price_usd_per_1m=1.0)])

    sync_auth_providers_into_frontend_json()

    rows = json.loads(frontend_json_file.read_text(encoding="utf-8"))
    assert rows[0]["input_price_usd_per_1m"] == 99.0


def test_sync_returns_zero_when_auth_providers_file_empty(auth_providers_file, frontend_json_file):
    frontend_json_file.write_text(json.dumps([_row("open.com")]), encoding="utf-8")

    added = sync_auth_providers_into_frontend_json()

    assert added == 0
