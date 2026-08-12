import json
import pytest

from app.services.payment_methods import (
    load_payment_methods_map,
    save_payment_methods_map,
    get_payment_methods,
    ensure_payment_methods_entry,
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
