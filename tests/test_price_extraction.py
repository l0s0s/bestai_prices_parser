import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Provider, ProviderPrice
from app.ai.schemas import RawPriceEntry
from app.services.normalization import normalize_price_entry
from app.services.price_extraction import merge_same_model_entries, save_prices, _merge_price_pair


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield session
    session.close()


def _make_pair(source_model_name, input_price=None, output_price=None, raw_price_text=""):
    entry = RawPriceEntry(
        source_model_name=source_model_name,
        input_price=input_price,
        output_price=output_price,
        currency="USD",
        unit="1M_tokens",
        raw_price_text=raw_price_text,
        confidence=0.95,
    )
    norm = normalize_price_entry(
        entry,
        aliases={"gpt-4o": "openai/gpt-4o"},
        official_prices={"openai/gpt-4o": {"input_usd_per_1m": 2.5, "output_usd_per_1m": 10.0}},
    )
    return entry, norm


def test_merge_same_model_entries_combines_input_and_output_halves():
    """Reproduces the real Gemini/Jigji behavior observed on anthropic.com/pricing:
    the AI reported "Sonnet 5" input and output as two separate JSON objects
    instead of one entry with both fields populated."""
    input_half = _make_pair("GPT-4o", input_price=1.0, raw_price_text="Input $1 / 1M")
    output_half = _make_pair("GPT-4o", output_price=4.0, raw_price_text="Output $4 / 1M")

    merged = merge_same_model_entries([input_half, output_half])

    assert len(merged) == 1
    entry, norm = merged[0]
    assert entry.input_price == 1.0
    assert entry.output_price == 4.0
    assert norm.input_price_usd_per_1m == 1.0
    assert norm.output_price_usd_per_1m == 4.0


def test_merge_price_pair_keeps_both_raw_texts_when_conflicting():
    """Reproduces a real bug found live on a crowded sunyears.com catalog
    page: two entries resolved to the SAME canonical model with genuinely
    different (already conflicting_prices-flagged) numbers. The old
    "longest text wins" tie-break could keep one side's number but the
    OTHER side's raw_price_text, silently citing a snippet unrelated to the
    kept price. Once either side is already flagged for review, both
    fragments must survive so a human reviewer sees the real conflict."""
    entry_a, norm_a = _make_pair("GPT-4o", input_price=1.12, output_price=9.0, raw_price_text="$1.12 in / $9.00 out")
    entry_b, norm_b = _make_pair(
        "GPT-4o", input_price=0.045, output_price=0.36,
        raw_price_text="$0.0450 in / $0.360 out (a much longer, unrelated snippet)",
    )
    norm_a.needs_review = True
    norm_a.review_reason = "conflicting_prices"

    merged_entry, merged_norm = _merge_price_pair((entry_a, norm_a), (entry_b, norm_b))

    assert "$1.12" in merged_entry.raw_price_text
    assert "$0.0450" in merged_entry.raw_price_text
    assert merged_norm.needs_review is True


def test_merge_price_pair_flags_conflict_when_two_complete_entries_disagree():
    """Reproduces a real bug found live on two unrelated sites (996444 API,
    newapi.dragon3api.com): a bare model name ("gpt-4o") and one of its
    date-stamped snapshot variants ("gpt-4o-2024-05-13") both correctly
    resolved to the same canonical model, but the source page priced them
    differently (a real, distinct historical/tiered rate for the dated
    snapshot). Neither entry was individually flagged needs_review (the old
    conflicting_prices check only fires above a 2x ratio, and this pair was
    under it), so the old merge silently combined one entry's numbers with
    the other's raw_price_text with no warning at all. Two COMPLETE entries
    (both input and output already present on each side) disagreeing on
    value must never be silently merged — this must always be caught,
    regardless of how close the two prices are."""
    entry_a, norm_a = _make_pair("GPT-4o", input_price=1.25, output_price=5.0, raw_price_text="Input: $1.25 / M | Output: $5 / M")
    entry_b, norm_b = _make_pair(
        "GPT-4o-2024-05-13", input_price=2.5, output_price=7.5,
        raw_price_text="Input: $2.5 / M tokens | Output: $7.5 / M tokens",
    )
    assert norm_a.needs_review is False and norm_b.needs_review is False  # neither individually flagged

    merged_entry, merged_norm = _merge_price_pair((entry_a, norm_a), (entry_b, norm_b))

    assert merged_norm.needs_review is True
    assert merged_norm.review_reason == "conflicting_prices"
    assert "$1.25" in merged_entry.raw_price_text
    assert "$2.5" in merged_entry.raw_price_text


def test_merge_same_model_entries_leaves_distinct_models_untouched():
    a = _make_pair("GPT-4o", input_price=1.0, output_price=4.0)
    b = _make_pair("Claude Sonnet", input_price=3.0, output_price=15.0)
    merged = merge_same_model_entries([a, b])
    assert len(merged) == 2


def test_save_prices_does_not_lose_or_duplicate_split_entries(db_session):
    """Regression test: before the fix, saving an input-only entry followed by
    an output-only entry for the same model in one batch either created two
    separate DB rows (violating the provider+model+source_url uniqueness the
    schema assumes) or, once "existing" happened to match, blindly overwrote
    the first entry's field with the second entry's None."""
    provider = Provider(name="Test", domain="test.com", website_url="https://test.com")
    db_session.add(provider)
    db_session.commit()

    input_half = _make_pair("GPT-4o", input_price=1.0, raw_price_text="Input $1 / 1M")
    output_half = _make_pair("GPT-4o", output_price=4.0, raw_price_text="Output $4 / 1M")

    save_prices(provider, [input_half, output_half], "https://test.com/pricing", db=db_session)

    rows = db_session.query(ProviderPrice).filter(ProviderPrice.provider_id == provider.id).all()
    assert len(rows) == 1
    assert rows[0].input_price_usd_per_1m == 1.0
    assert rows[0].output_price_usd_per_1m == 4.0


def test_save_prices_second_run_merges_into_existing_row_without_wiping_fields(db_session):
    """A later run that only re-confirms the output price must not blank out
    the input price already stored from an earlier run."""
    provider = Provider(name="Test", domain="test.com", website_url="https://test.com")
    db_session.add(provider)
    db_session.commit()

    full = _make_pair("GPT-4o", input_price=1.0, output_price=4.0, raw_price_text="$1 / $4 per 1M")
    save_prices(provider, [full], "https://test.com/pricing", db=db_session)

    output_only = _make_pair("GPT-4o", output_price=5.0, raw_price_text="Output $5 / 1M")
    save_prices(provider, [output_only], "https://test.com/pricing", db=db_session)

    rows = db_session.query(ProviderPrice).filter(ProviderPrice.provider_id == provider.id).all()
    assert len(rows) == 1
    assert rows[0].input_price_usd_per_1m == 1.0
    assert rows[0].output_price_usd_per_1m == 5.0
