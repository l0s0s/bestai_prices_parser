import json
import pytest
from app.services.exporter import export_frontend_json_atomically
from app.services.frontend_schema import FRONTEND_JSON_SCHEMA


def test_export_frontend_json_atomically(tmp_path, monkeypatch):
    target = tmp_path / "providers.json"
    monkeypatch.setattr("app.settings.settings.frontend_json_path", str(target))

    sample_data = [
        {
            "provider_name": "Test API",
            "provider_domain": "test.com",
            "provider_url": "https://test.com",
            "model_name": "GPT-4o",
            "canonical_model_id": "openai/gpt-4o",
            "input_price_usd_per_1m": 1.25,
            "output_price_usd_per_1m": 5.0,
            "official_input_price_usd_per_1m": 2.50,
            "official_output_price_usd_per_1m": 10.00,
            "input_discount_percent": 50.0,
            "output_discount_percent": 50.0,
            "trust_status": "green",
            "source_url": "https://test.com/pricing",
            "last_checked_at": "2026-08-01T00:00:00Z"
        }
    ]

    export_frontend_json_atomically(sample_data)

    assert target.exists()
    content = json.loads(target.read_text(encoding="utf-8"))
    assert len(content) == 1
    assert content[0]["provider_name"] == "Test API"
