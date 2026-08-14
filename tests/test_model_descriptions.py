import json
import pytest

from app.services.model_descriptions import load_model_descriptions, get_model_description


@pytest.fixture()
def md_file(tmp_path, monkeypatch):
    path = tmp_path / "model_descriptions.json"
    monkeypatch.setattr("app.settings.settings.model_descriptions_file", str(path))
    return path


def test_load_model_descriptions_missing_file_returns_empty(md_file):
    assert load_model_descriptions() == {}


def test_load_model_descriptions_round_trips(md_file):
    data = {"openai/gpt-4o": {"display_name": "GPT-4o", "description_ru": "р", "description_en": "e"}}
    md_file.write_text(json.dumps(data), encoding="utf-8")
    assert load_model_descriptions() == data


def test_get_model_description_returns_entry(md_file):
    data = {"openai/gpt-4o": {"display_name": "GPT-4o", "description_ru": "р", "description_en": "e"}}
    assert get_model_description("openai/gpt-4o", data) == data["openai/gpt-4o"]


def test_get_model_description_missing_id_returns_none(md_file):
    assert get_model_description("openai/gpt-4o", {}) is None


def test_get_model_description_reads_from_file_when_no_data_passed(md_file):
    data = {"openai/gpt-4o": {"display_name": "GPT-4o", "description_ru": "р", "description_en": "e"}}
    md_file.write_text(json.dumps(data), encoding="utf-8")
    assert get_model_description("openai/gpt-4o") == data["openai/gpt-4o"]


def test_load_model_descriptions_normalizes_em_dash_to_en_dash(md_file):
    data = {
        "openai/gpt-4o": {
            "display_name": "GPT-4o",
            "description_ru": "GPT-4o — флагманская модель",
            "description_en": "GPT-4o — the flagship model",
        }
    }
    md_file.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_model_descriptions()
    assert loaded["openai/gpt-4o"]["description_ru"] == "GPT-4o – флагманская модель"
    assert loaded["openai/gpt-4o"]["description_en"] == "GPT-4o – the flagship model"
    assert "—" not in json.dumps(loaded)
