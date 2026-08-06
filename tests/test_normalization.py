import pytest
from app.ai.schemas import RawPriceEntry
from app.services.normalization import normalize_model_name, normalize_price_entry


def test_normalize_model_name():
    aliases = {
        "gpt-4o": "openai/gpt-4o",
        "claude-3.5-sonnet": "anthropic/claude-3-5-sonnet"
    }
    assert normalize_model_name("GPT-4o", aliases) == "openai/gpt-4o"
    assert normalize_model_name("claude 3.5 sonnet", aliases) == "anthropic/claude-3-5-sonnet"
    assert normalize_model_name("Unknown-Model-X", aliases) is None


def test_normalize_price_entry_conversion():
    aliases = {"gpt-4o": "openai/gpt-4o"}
    fx_rates = {"USD": 1.0, "CNY": 0.14}
    official_prices = {
        "openai/gpt-4o": {
            "input_usd_per_1m": 2.50,
            "output_usd_per_1m": 10.00
        }
    }

    # 1K token unit conversion
    entry_1k = RawPriceEntry(
        source_model_name="GPT-4o",
        input_price=0.00125,  # $0.00125 per 1K => $1.25 per 1M
        output_price=0.005,    # $0.005 per 1K => $5.00 per 1M
        currency="USD",
        unit="1K_tokens",
        raw_price_text="$0.00125 / 1K tokens",
    )

    norm_1k = normalize_price_entry(entry_1k, aliases, fx_rates, official_prices)
    assert norm_1k.input_price_usd_per_1m == 1.25
    assert norm_1k.output_price_usd_per_1m == 5.0
    assert norm_1k.input_discount_percent == 50.0
    assert norm_1k.output_discount_percent == 50.0
    assert norm_1k.is_cheaper_than_official is True

    # CNY currency conversion
    entry_cny = RawPriceEntry(
        source_model_name="GPT-4o",
        input_price=7.0,  # 7 CNY per 1M => 7 * 0.14 = $0.98 per 1M
        output_price=28.0, # 28 CNY per 1M => 28 * 0.14 = $3.92 per 1M
        currency="CNY",
        unit="1M_tokens",
        raw_price_text="7元 / 1M tokens",
    )

    norm_cny = normalize_price_entry(entry_cny, aliases, fx_rates, official_prices)
    assert norm_cny.input_price_usd_per_1m == 0.98
    assert norm_cny.output_price_usd_per_1m == 3.92
    assert norm_cny.is_cheaper_than_official is True
