import json
import pytest
from datetime import datetime
from app.ai.client import AiClient
from app.ai.schemas import AiExtractionResult, RawPriceEntry
from app.crawler.cleaner import CleanedPage
from app.services.price_extraction import validate_ai_result, is_login_required
from app.services.normalization import normalize_price_entry


def test_ai_client_no_fake_prices_without_key():
    client = AiClient(api_key="")
    raw_res = client.extract("sys prompt", "https://example.com/pricing", "GPT-4o text", {})
    data = json.loads(raw_res)
    assert data["prices"] == []


def test_validate_ai_result_snippet_missing():
    snapshot = CleanedPage(
        source_url="https://example.com/pricing",
        text="GPT-4o price is $1.25 per 1M input tokens.",
        language="en",
        http_status=200,
        fetched_at=datetime.utcnow(),
        content_hash="1234567890abcdef",
    )

    result = AiExtractionResult(
        source_url="https://example.com/pricing",
        prices=[
            RawPriceEntry(
                source_model_name="GPT-4o",
                input_price=1.25,
                output_price=5.0,
                currency="USD",
                unit="1M_tokens",
                raw_price_text="Non-existent snippet in page text",
                confidence=0.95,
            )
        ]
    )

    validated = validate_ai_result(result, snapshot)
    assert len(validated) == 1
    raw_entry, norm_entry = validated[0]
    assert norm_entry.needs_review is True
    assert norm_entry.review_reason == "price_not_found"


def test_login_required_detection():
    assert is_login_required("Please sign in to see pricing details.") is True
    assert is_login_required("Sign in to view. Contact sales for high volume.") is True
    assert is_login_required("GPT-4o price $2.50 / 1M tokens") is False


def test_zero_price_rejection():
    snapshot = CleanedPage(
        source_url="https://example.com/pricing",
        text="GPT-4o $0.00 / 1M tokens",
        language="en",
        http_status=200,
        fetched_at=datetime.utcnow(),
        content_hash="1234567890abcdef",
    )

    result = AiExtractionResult(
        source_url="https://example.com/pricing",
        prices=[
            RawPriceEntry(
                source_model_name="GPT-4o",
                input_price=0.0,
                output_price=0.0,
                currency="USD",
                unit="1M_tokens",
                raw_price_text="GPT-4o $0.00 / 1M tokens",
                confidence=0.9,
            )
        ]
    )

    validated = validate_ai_result(result, snapshot)
    raw_entry, norm_entry = validated[0]
    assert norm_entry.needs_review is True
    assert norm_entry.review_reason == "invalid_json"


def test_price_multiplier_zhe_notation():
    entry = RawPriceEntry(
        source_model_name="GPT-4o",
        input_price=None,
        output_price=None,
        currency="USD",
        unit="1M_tokens",
        price_multiplier=0.3,
        raw_price_text="官方 0.3x 倍率 / 3折优惠",
        confidence=0.9,
    )
    official_prices = {
        "openai/gpt-4o": {
            "input_usd_per_1m": 2.50,
            "output_usd_per_1m": 10.00
        }
    }
    norm = normalize_price_entry(entry, aliases={"gpt-4o": "openai/gpt-4o"}, official_prices=official_prices)
    assert norm.input_price_usd_per_1m == 0.75
    assert norm.output_price_usd_per_1m == 3.0
    assert norm.is_cheaper_than_official is True
