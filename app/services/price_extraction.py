import re
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.ai.schemas import AiExtractionResult, RawPriceEntry
from app.crawler.cleaner import CleanedPage
from app.models import Provider, ProviderPrice, PriceHistory
from app.services.normalization import normalize_price_entry, NormalizedPrice
from app.settings import settings
from app.logging_setup import logger

LOGIN_PATTERNS = [
    r"sign\s+in\s+to\s+see",
    r"log\s+in\s+to\s+view",
    r"login\s+required",
    r"contact\s+sales",
    r"请\s*登\s*录",
    r"联\s*系\s*客\s*服",
    r"登\s*录\s*后\s*查\s*看",
]

LOGIN_REGEX = re.compile("|".join(LOGIN_PATTERNS), re.IGNORECASE)


# Currency-symbol-before-digit ($123, ¥123) covers Western notation, but
# Chinese pricing pages very commonly place the currency word AFTER the
# number instead ("1 元/百万tokens", "CNY 起") — a real, live page (Tencent
# Hunyuan's token-price catalog) had exactly this shape: genuine digit
# prices in "元"-suffix form, plus an unrelated "联系客服" (contact support)
# link elsewhere on the page. The old symbol-before-digit-only check missed
# the real prices entirely, so every genuinely-priced entry on that page
# was wrongly flagged login_required and discarded despite having nothing
# to do with a login wall.
HAS_PRICE_DIGITS_RE = re.compile(
    r"(\$|¥)\s*[0-9]+\.?[0-9]*"
    r"|[0-9]+\.?[0-9]*\s*元"
    r"|[0-9]+\.?[0-9]*\s*(USD|CNY|EUR|RUB)\b",
    re.IGNORECASE,
)


def is_login_required(page_text: str) -> bool:
    """Detect login wall or sales contact prompts in page text."""
    if not page_text:
        return False
    # Check if login prompt exists AND page text lacks obvious price figures
    has_login_prompt = bool(LOGIN_REGEX.search(page_text))
    has_digit_prices = bool(HAS_PRICE_DIGITS_RE.search(page_text))
    return has_login_prompt and not has_digit_prices


def validate_ai_result(ai_result: AiExtractionResult, snapshot: CleanedPage) -> List[Tuple[RawPriceEntry, NormalizedPrice]]:
    """Validate AI extraction result against all 8 review criteria."""
    validated: List[Tuple[RawPriceEntry, NormalizedPrice]] = []

    # Check login_required on snapshot page text
    login_blocked = is_login_required(snapshot.text)

    snapshot_clean_text = re.sub(r"\s+", " ", snapshot.text.lower()) if snapshot.text else ""

    model_prices: dict[str, List[float]] = {}

    for entry in ai_result.prices:

        # Each check below sets needs_review unconditionally but only fills in
        # review_reason when it's still blank — first specific reason found
        # wins, but an AI-set needs_review=true with no explanation (allowed by
        # the prompt) no longer suppresses every later check and reaches the
        # CSV with an empty reason column.

        # 1. Login required check
        if login_blocked:
            entry.needs_review = True
            if not entry.review_reason:
                entry.review_reason = "login_required"

        # 2. Price snippet verification in snapshot (also catches a missing
        # raw_price_text outright — nothing to verify means it can't be
        # confirmed against the snapshot either, per TZ step 6.3).
        raw_text_clean = re.sub(r"\s+", " ", entry.raw_price_text.lower()) if entry.raw_price_text else ""
        if not raw_text_clean:
            entry.needs_review = True
            if not entry.review_reason:
                entry.review_reason = "price_not_found"
        elif snapshot_clean_text and raw_text_clean not in snapshot_clean_text:
            words = raw_text_clean.split()[:4]
            snippet_part = " ".join(words)
            if not snippet_part or snippet_part not in snapshot_clean_text:
                entry.needs_review = True
                if not entry.review_reason:
                    entry.review_reason = "price_not_found"

        # 3. Reject zero or negative prices
        if (entry.input_price is not None and entry.input_price <= 0) or \
           (entry.output_price is not None and entry.output_price <= 0):
            entry.needs_review = True
            if not entry.review_reason:
                entry.review_reason = "invalid_json"

        # 4. Low confidence check
        if entry.confidence < settings.ai_min_confidence:
            entry.needs_review = True
            if not entry.review_reason:
                entry.review_reason = "low_confidence"

        # Normalize price
        norm = normalize_price_entry(entry)

        # Track prices for conflicting_prices check
        if norm.canonical_model_id and norm.input_price_usd_per_1m and norm.input_price_usd_per_1m > 0:
            model_prices.setdefault(norm.canonical_model_id, []).append(norm.input_price_usd_per_1m)

        validated.append((entry, norm))

    # 5. Conflicting prices check for same model on same page
    for entry, norm in validated:
        if norm.canonical_model_id and norm.canonical_model_id in model_prices:
            prices_list = model_prices[norm.canonical_model_id]
            if len(prices_list) > 1:
                min_p, max_p = min(prices_list), max(prices_list)
                if max_p / min_p > 2.0:
                    norm.needs_review = True
                    if not norm.review_reason:
                        norm.review_reason = "conflicting_prices"

    return validated


def _merge_key(entry: RawPriceEntry, norm: NormalizedPrice) -> str:
    """Group by canonical model when resolved (matches the DB's one-row-per
    provider+model+page constraint), else fall back to the raw source name."""
    if norm.canonical_model_id:
        return f"id::{norm.canonical_model_id}"
    return f"name::{entry.source_model_name.strip().lower()}"


_FLOAT_TOLERANCE = 1e-6


def _values_conflict(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) > _FLOAT_TOLERANCE


def _merge_price_pair(
    a: Tuple[RawPriceEntry, NormalizedPrice],
    b: Tuple[RawPriceEntry, NormalizedPrice],
) -> Tuple[RawPriceEntry, NormalizedPrice]:
    """Merge two entries describing the same model on the same page — e.g. the
    AI reported one input-only and one output-only row instead of a single row
    with both fields — preferring whichever side has a value for each field."""
    entry_a, norm_a = a
    entry_b, norm_b = b

    text_a = entry_a.raw_price_text or ""
    text_b = entry_b.raw_price_text or ""

    # Two entries only qualify as "complementary halves of one real price"
    # (the case this merge was built for — the AI reporting a model's input
    # and output as two separate JSON objects) when at least one side is
    # missing a field the other has. When BOTH sides already report BOTH
    # input and output, they are two independently complete price claims for
    # whatever normalize_model_name() decided is "the same" canonical model
    # — and that call can be right about the match yet still wrong to treat
    # as one price: confirmed live on two unrelated sites (996444 API,
    # newapi.dragon3api.com) where a bare model name ("gpt-4o",
    # "claude-haiku-4-5") and one of its date-stamped snapshot variants
    # ("gpt-4o-2024-05-13", "claude-haiku-4-5-20251001") — correctly bridged
    # to the same canonical id by the snapshot-suffix rule, since a dated
    # snapshot is *usually* just an alias for the same current billing SKU —
    # turned out to carry a genuinely different, real resale price on that
    # specific page. Blindly keeping one side's numbers while independently
    # picking "whichever raw_price_text is longer" then publishes a row
    # whose number and citation don't even describe the same real listing.
    # Since the code cannot tell which of two complete, differing prices is
    # "the" price for the merged model, neither may be guessed — treat this
    # exactly like an already-known conflict: force review and keep both
    # fragments so a human sees the real discrepancy.
    both_complete = (
        entry_a.input_price is not None and entry_a.output_price is not None
        and entry_b.input_price is not None and entry_b.output_price is not None
    )
    values_differ = both_complete and (
        _values_conflict(entry_a.input_price, entry_b.input_price)
        or _values_conflict(entry_a.output_price, entry_b.output_price)
    )

    conflicting = bool(norm_a.needs_review or norm_b.needs_review) or values_differ
    if conflicting and text_a and text_b and text_a != text_b:
        merged_raw_text = f"{text_a} || {text_b}"
    else:
        merged_raw_text = text_a if len(text_a) >= len(text_b) else text_b

    merge_reason = "conflicting_prices" if values_differ else None

    merged_entry = RawPriceEntry(
        source_model_name=entry_a.source_model_name,
        input_price=entry_a.input_price if entry_a.input_price is not None else entry_b.input_price,
        output_price=entry_a.output_price if entry_a.output_price is not None else entry_b.output_price,
        currency=entry_a.currency or entry_b.currency,
        unit=entry_a.unit or entry_b.unit,
        price_multiplier=entry_a.price_multiplier if entry_a.price_multiplier is not None else entry_b.price_multiplier,
        raw_price_text=merged_raw_text,
        confidence=min(entry_a.confidence, entry_b.confidence),
        needs_review=entry_a.needs_review or entry_b.needs_review or values_differ,
        review_reason=entry_a.review_reason or entry_b.review_reason or merge_reason,
    )
    merged_norm = normalize_price_entry(merged_entry)
    if norm_a.needs_review or norm_b.needs_review or values_differ:
        merged_norm.needs_review = True
        merged_norm.review_reason = merged_norm.review_reason or norm_a.review_reason or norm_b.review_reason or merge_reason
    return merged_entry, merged_norm


def merge_same_model_entries(
    validated_items: List[Tuple[RawPriceEntry, NormalizedPrice]],
) -> List[Tuple[RawPriceEntry, NormalizedPrice]]:
    """Collapse same-page duplicates for the same model before they ever reach
    the DB. Without this, two AI-reported halves (input-only / output-only) for
    one model would either silently clobber each other or raise an
    IntegrityError on the (provider_id, canonical_model_id, source_url)
    uniqueness constraint — the query-based upsert below can't catch this on
    its own because the session doesn't autoflush between loop iterations."""
    merged: dict = {}
    order: List[str] = []
    for entry, norm in validated_items:
        key = _merge_key(entry, norm)
        if key in merged:
            merged[key] = _merge_price_pair(merged[key], (entry, norm))
        else:
            merged[key] = (entry, norm)
            order.append(key)
    return [merged[k] for k in order]


def save_prices(provider: Provider, validated_items: List[Tuple[RawPriceEntry, NormalizedPrice]], source_url: str, db: Session) -> None:
    """Save or update prices in database and record history on value changes."""
    now = datetime.utcnow()
    validated_items = merge_same_model_entries(validated_items)

    for entry, norm in validated_items:
        # Ignore items with no valid price values at all
        if norm.input_price_usd_per_1m is None and norm.output_price_usd_per_1m is None and not norm.needs_review:
            continue

        existing = db.query(ProviderPrice).filter(
            ProviderPrice.provider_id == provider.id,
            ProviderPrice.canonical_model_id == norm.canonical_model_id,
            ProviderPrice.source_url == source_url,
        ).first() if norm.canonical_model_id else None

        if not existing:
            existing = db.query(ProviderPrice).filter(
                ProviderPrice.provider_id == provider.id,
                ProviderPrice.source_model_name == entry.source_model_name,
                ProviderPrice.source_url == source_url,
            ).first()

        if existing:
            # Merge rather than overwrite: the AI sometimes reports input and
            # output prices for the same model as two separate entries (e.g.
            # "Sonnet 5" input-only, then "Sonnet 5" output-only). A blind
            # overwrite here would let the second entry wipe out the first
            # entry's field with None. Only replace a field when the new
            # extraction actually supplied a value for it.
            new_input = norm.input_price_usd_per_1m if norm.input_price_usd_per_1m is not None else existing.input_price_usd_per_1m
            new_output = norm.output_price_usd_per_1m if norm.output_price_usd_per_1m is not None else existing.output_price_usd_per_1m

            if existing.input_price_usd_per_1m != new_input:
                history = PriceHistory(
                    provider_price_id=existing.id,
                    old_value=existing.input_price_usd_per_1m,
                    new_value=new_input,
                    source_url=source_url,
                    changed_at=now,
                )
                db.add(history)

            existing.input_price_usd_per_1m = new_input
            existing.output_price_usd_per_1m = new_output
            existing.confidence = entry.confidence
            # A merged record is only as trustworthy as its most cautious half:
            # if either the existing row or this entry needed review, keep it
            # flagged even though the freshly-merged field looks complete now.
            existing.needs_review = norm.needs_review or existing.needs_review
            existing.review_reason = norm.review_reason or existing.review_reason
            existing.last_checked_at = now
        else:
            new_price = ProviderPrice(
                provider_id=provider.id,
                canonical_model_id=norm.canonical_model_id,
                source_model_name=entry.source_model_name,
                raw_price_text=entry.raw_price_text or "",
                raw_currency=entry.currency,
                raw_unit=entry.unit,
                input_price_usd_per_1m=norm.input_price_usd_per_1m,
                output_price_usd_per_1m=norm.output_price_usd_per_1m,
                confidence=entry.confidence,
                needs_review=norm.needs_review,
                review_reason=norm.review_reason,
                source_url=source_url,
                last_checked_at=now,
            )
            db.add(new_price)

    db.commit()


def _dedupe_publishable_rows(rows: List[dict]) -> List[dict]:
    """Collapse rows that describe the same (provider, model) more than once.

    The DB's uniqueness constraint is (provider_id, canonical_model_id,
    source_url) — a provider that lists the identical pricing table on two
    URLs (e.g. its homepage and a /register page mirroring the same table, as
    seen live on zivv.pro) legitimately produces two ProviderPrice rows for
    one real-world offer. Publishing both would show the frontend the same
    model twice for the same provider. Keep the most recently confirmed row;
    break ties by preferring the shorter source_url (the more likely
    "canonical" page over an incidental mirror)."""
    best: dict = {}
    for row in rows:
        key = (row["provider_domain"], row["canonical_model_id"])
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        if row["last_checked_at"] > current["last_checked_at"]:
            best[key] = row
        elif row["last_checked_at"] == current["last_checked_at"] and len(row["source_url"]) < len(current["source_url"]):
            best[key] = row
    return list(best.values())


def select_publishable_prices(db: Session) -> List[dict]:
    """Select records that satisfy publishing rules in TZ §11."""
    publishable = []

    providers = db.query(Provider).all()
    for provider in providers:
        if not provider.site_alive:
            continue
        if not provider.pricing_url and not provider.docs_url:
            continue

        for price in provider.prices:
            if price.needs_review:
                continue
            if not price.canonical_model_id:
                continue
            if price.confidence < settings.ai_min_confidence:
                continue
            if not price.source_url:
                continue

            # Zero or non-positive prices cannot be published
            if (price.input_price_usd_per_1m is not None and price.input_price_usd_per_1m <= 0) or \
               (price.output_price_usd_per_1m is not None and price.output_price_usd_per_1m <= 0):
                continue

            if price.input_price_usd_per_1m is None and price.output_price_usd_per_1m is None:
                continue

            norm = normalize_price_entry(
                RawPriceEntry(
                    source_model_name=price.source_model_name,
                    input_price=price.input_price_usd_per_1m,
                    output_price=price.output_price_usd_per_1m,
                    currency="USD",
                    unit="1M_tokens",
                    raw_price_text=price.raw_price_text,
                    confidence=price.confidence,
                )
            )

            if not norm.is_cheaper_than_official:
                continue

            publishable.append({
                "provider_name": provider.name,
                "provider_domain": provider.domain,
                "provider_url": provider.website_url,
                "model_name": price.source_model_name,
                "canonical_model_id": price.canonical_model_id,
                "input_price_usd_per_1m": price.input_price_usd_per_1m,
                "output_price_usd_per_1m": price.output_price_usd_per_1m,
                "official_input_price_usd_per_1m": norm.official_input_price_usd_per_1m,
                "official_output_price_usd_per_1m": norm.official_output_price_usd_per_1m,
                "input_discount_percent": norm.input_discount_percent,
                "output_discount_percent": norm.output_discount_percent,
                "trust_status": provider.trust_status,
                "source_url": price.source_url,
                "last_checked_at": price.last_checked_at.isoformat() + "Z" if price.last_checked_at else datetime.utcnow().isoformat() + "Z",
            })

    return _dedupe_publishable_rows(publishable)


def expire_unconfirmed_prices(db: Session, run_start_time: datetime) -> int:
    """Mark prices unconfirmed in current pipeline run as stale needs_review=True."""
    stale_prices = db.query(ProviderPrice).filter(
        ProviderPrice.last_checked_at < run_start_time
    ).all()

    count = 0
    for price in stale_prices:
        if not price.needs_review or price.review_reason != "stale":
            price.needs_review = True
            price.review_reason = "stale"
            count += 1

    db.commit()
    logger.info(f"Marked {count} stale prices needing review.", extra={"pipeline_step": "expire_stale"})
    return count
