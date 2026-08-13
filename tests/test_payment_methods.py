import json
import pytest

from app.services.payment_methods import (
    load_payment_methods_map,
    save_payment_methods_map,
    get_payment_methods,
    ensure_payment_methods_entry,
    sync_payment_methods_into_frontend_json,
)


@pytest.fixture()
def pm_file(tmp_path, monkeypatch):
    path = tmp_path / "payment_methods.json"
    monkeypatch.setattr("app.settings.settings.payment_methods_file", str(path))
    return path


def test_load_payment_methods_map_missing_file_returns_empty(pm_file):
    assert load_payment_methods_map() == {}


def test_save_then_load_round_trips(pm_file):
    save_payment_methods_map({"test.com": ["paypal", "crypto"]})
    assert load_payment_methods_map() == {"test.com": ["paypal", "crypto"]}


def test_get_payment_methods_returns_entry(pm_file):
    data = {"test.com": ["paypal"]}
    assert get_payment_methods("test.com", data) == ["paypal"]


def test_get_payment_methods_missing_domain_returns_empty_without_mutating(pm_file):
    data = {"other.com": ["paypal"]}
    assert get_payment_methods("test.com", data) == []
    assert "test.com" not in data


def test_get_payment_methods_reads_from_file_when_no_data_passed(pm_file):
    save_payment_methods_map({"test.com": ["revolut"]})
    assert get_payment_methods("test.com") == ["revolut"]


def test_ensure_payment_methods_entry_adds_empty_list_for_new_domain(pm_file):
    data = {}
    added = ensure_payment_methods_entry("test.com", data)
    assert added is True
    assert data == {"test.com": []}


def test_ensure_payment_methods_entry_leaves_existing_entry_untouched(pm_file):
    data = {"test.com": ["paypal"]}
    added = ensure_payment_methods_entry("test.com", data)
    assert added is False
    assert data == {"test.com": ["paypal"]}


def test_ensure_payment_methods_entry_does_not_overwrite_curated_empty_list(pm_file):
    # An empty list already on file is a curated "confirmed none", not a gap.
    data = {"test.com": []}
    added = ensure_payment_methods_entry("test.com", data)
    assert added is False
    assert data == {"test.com": []}


def _row(domain, payment_methods=None):
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
        "payment_methods": payment_methods or [],
    }


@pytest.fixture()
def frontend_json_file(tmp_path, monkeypatch):
    path = tmp_path / "providers.json"
    monkeypatch.setattr("app.settings.settings.frontend_json_path", str(path))
    return path


def test_sync_payment_methods_missing_frontend_json_raises(pm_file, frontend_json_file):
    with pytest.raises(FileNotFoundError):
        sync_payment_methods_into_frontend_json()


def test_sync_payment_methods_updates_rows_by_domain(pm_file, frontend_json_file):
    save_payment_methods_map({"test.com": ["paypal", "crypto"], "other.com": []})
    frontend_json_file.write_text(
        json.dumps([_row("test.com"), _row("other.com", ["stale"])]), encoding="utf-8"
    )

    changed = sync_payment_methods_into_frontend_json()

    rows = json.loads(frontend_json_file.read_text(encoding="utf-8"))
    assert rows[0]["payment_methods"] == ["paypal", "crypto"]
    assert rows[1]["payment_methods"] == []
    assert changed == 2  # test.com went [] -> [paypal, crypto], other.com went [stale] -> []


def test_sync_payment_methods_domain_without_entry_gets_empty_list(pm_file, frontend_json_file):
    save_payment_methods_map({})
    frontend_json_file.write_text(json.dumps([_row("unknown.com", ["old"])]), encoding="utf-8")

    changed = sync_payment_methods_into_frontend_json()

    rows = json.loads(frontend_json_file.read_text(encoding="utf-8"))
    assert rows[0]["payment_methods"] == []
    assert changed == 1


def test_sync_payment_methods_leaves_unrelated_fields_untouched(pm_file, frontend_json_file):
    save_payment_methods_map({"test.com": ["paypal"]})
    frontend_json_file.write_text(json.dumps([_row("test.com")]), encoding="utf-8")

    sync_payment_methods_into_frontend_json()

    rows = json.loads(frontend_json_file.read_text(encoding="utf-8"))
    assert rows[0]["provider_name"] == "test.com"
    assert rows[0]["trust_status"] == "green"


def test_sync_payment_methods_returns_zero_when_nothing_changes(pm_file, frontend_json_file):
    save_payment_methods_map({"test.com": ["paypal"]})
    frontend_json_file.write_text(json.dumps([_row("test.com", ["paypal"])]), encoding="utf-8")

    changed = sync_payment_methods_into_frontend_json()

    assert changed == 0
