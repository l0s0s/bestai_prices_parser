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


def test_normalize_model_name_snapshot_suffix_still_matches():
    # A pure date/snapshot suffix is a harmless qualifier on the same model.
    aliases = {"gpt-4o": "openai/gpt-4o"}
    assert normalize_model_name("gpt-4o-(2024-08-06)", aliases) == "openai/gpt-4o"
    assert normalize_model_name("gpt-4o-20241022", aliases) == "openai/gpt-4o"


def test_normalize_model_name_rejects_distinct_lettered_variant():
    # A short, generic alias key must not match as a bare prefix of a longer,
    # more specific real model name — e.g. "gpt-4" must not swallow
    # "gpt-4-1106-preview" (a distinct, differently-priced historical SKU),
    # or "gpt-4-turbo"/"gpt-4-32k"/"gpt-4-vision-preview" and similar.
    aliases = {"gpt-4": "openai/gpt-4"}
    assert normalize_model_name("gpt-4-1106-preview", aliases) is None
    assert normalize_model_name("gpt-4-turbo", aliases) is None
    assert normalize_model_name("gpt-4-32k", aliases) is None
    assert normalize_model_name("gpt-4-vision-preview", aliases) is None
    assert normalize_model_name("gpt-4", aliases) == "openai/gpt-4"


def test_normalize_model_name_allows_vendor_namespace_prefix():
    # A HuggingFace-style "vendor/model" prefix ahead of an exact alias key
    # is a harmless namespace, not a distinct variant — this is the
    # motivating case for the fuzzy fallback and must keep matching.
    aliases = {"deepseek-r1": "deepseek/deepseek-r1"}
    assert normalize_model_name("deepseek-ai/DeepSeek-R1", aliases) == "deepseek/deepseek-r1"


def test_normalize_model_name_never_guesses_a_more_specific_variant():
    # The source name being a shortened/generic prefix of a longer, more
    # specific alias key must never resolve — that would mean guessing which
    # specific sub-variant the page meant.
    aliases = {
        "qwen-max": "alibaba/qwen-max",
        "gemini-3.1-pro-preview": "google/gemini-3-1-pro-preview",
    }
    assert normalize_model_name("Qwen", aliases) is None
    assert normalize_model_name("gemini-3.1-pro", aliases) is None


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
