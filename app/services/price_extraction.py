import re
from datetime import datetime
from typing import List, Tuple
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


def is_login_required(page_text: str) -> bool:
    """Detect login wall or sales contact prompts in page text."""
    if not page_text:
        return False
    # Check if login prompt exists AND page text lacks obvious price figures
    has_login_prompt = bool(LOGIN_REGEX.search(page_text))
    has_digit_prices = bool(re.search(r"(\$|¥)\s*[0-9]+\.?[0-9]*", page_text))
    return has_login_prompt and not has_digit_prices


def validate_ai_result(ai_result: AiExtractionResult, snapshot: CleanedPage) -> List[Tuple[RawPriceEntry, NormalizedPrice]]:
    """Validate AI extraction result against all 8 review criteria."""
    validated: List[Tuple[RawPriceEntry, NormalizedPrice]] = []

    # Check login_required on snapshot page text
    login_blocked = is_login_required(snapshot.text)

    snapshot_clean_text = re.sub(r"\s+", " ", snapshot.text.lower()) if snapshot.text else ""

    model_prices: dict[str, List[float]] = {}

    for entry in ai_result.prices:

        # 1. Login required check
        if login_blocked and not entry.needs_review:
            entry.needs_review = True
            entry.review_reason = "login_required"

        # 2. Price snippet verification in snapshot
        raw_text_clean = re.sub(r"\s+", " ", entry.raw_price_text.lower()) if entry.raw_price_text else ""
        if raw_text_clean and snapshot_clean_text and raw_text_clean not in snapshot_clean_text:
            words = raw_text_clean.split()[:4]
            snippet_part = " ".join(words)
            if not snippet_part or snippet_part not in snapshot_clean_text:
                if not entry.needs_review:
                    entry.needs_review = True
                    entry.review_reason = "price_not_found"

        # 3. Reject zero or negative prices
        if (entry.input_price is not None and entry.input_price <= 0) or \
           (entry.output_price is not None and entry.output_price <= 0):
            if not entry.needs_review:
                entry.needs_review = True
                entry.review_reason = "invalid_json"

        # 4. Low confidence check
        if entry.confidence < settings.ai_min_confidence and not entry.needs_review:
            entry.needs_review = True
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
                if max_p / min_p > 2.0 and not norm.needs_review:
                    norm.needs_review = True
                    norm.review_reason = "conflicting_prices"

    return validated


def save_prices(provider: Provider, validated_items: List[Tuple[RawPriceEntry, NormalizedPrice]], source_url: str, db: Session) -> None:
    """Save or update prices in database and record history on value changes."""
    now = datetime.utcnow()

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
            if existing.input_price_usd_per_1m != norm.input_price_usd_per_1m:
                history = PriceHistory(
                    provider_price_id=existing.id,
                    old_value=existing.input_price_usd_per_1m,
                    new_value=norm.input_price_usd_per_1m,
                    source_url=source_url,
                    changed_at=now,
                )
                db.add(history)

            existing.input_price_usd_per_1m = norm.input_price_usd_per_1m
            existing.output_price_usd_per_1m = norm.output_price_usd_per_1m
            existing.confidence = entry.confidence
            existing.needs_review = norm.needs_review
            existing.review_reason = norm.review_reason
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

    return publishable


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
