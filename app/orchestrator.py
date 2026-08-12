import time
from datetime import datetime
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import SourceSnapshot, ProviderPrice, Provider
from app.sources.base import DiscoveredProvider
from app.services.provider_discovery import crawl_enabled_sources, normalize_and_deduplicate
from app.crawler.page_finder import find_pricing_pages
from app.crawler.fetcher import fetch
from app.crawler.cleaner import clean_html, save_snapshot
from app.ai.extractor import extract_prices_with_ai
from app.services.price_extraction import validate_ai_result, save_prices, select_publishable_prices, expire_unconfirmed_prices
from app.services.payment_methods import load_payment_methods_map, save_payment_methods_map, ensure_payment_methods_entry
from app.services.trust_check import update_trust_signals
from app.services.exporter import export_frontend_json_atomically, export_review_csv
from app.logging_setup import logger


@dataclass
class RunSummary:
    sources_processed: int = 0
    providers_found: int = 0
    providers_unique: int = 0
    pricing_pages_found: int = 0
    prices_extracted: int = 0
    prices_published: int = 0
    records_needing_review: int = 0
    errors_count: int = 0
    duration_seconds: float = 0.0
    hard_failure: bool = False


def run_update_all() -> RunSummary:
    """Execute complete end-to-end bestai_prices_parser pipeline."""
    start_time = time.monotonic()
    run_start_dt = datetime.utcnow()
    summary = RunSummary()

    init_db()
    db: Session = SessionLocal()

    try:
        # Step 1: Crawl catalogs
        logger.info("Starting pipeline step: crawl_enabled_sources", extra={"pipeline_step": "crawl_sources"})
        discovered: list[DiscoveredProvider] = crawl_enabled_sources()
        summary.sources_processed = len(set(d.catalog_source for d in discovered))
        summary.providers_found = len(discovered)

        # Step 2: Deduplicate & Save Providers
        providers: list[Provider] = normalize_and_deduplicate(discovered, db=db)
        summary.providers_unique = len(providers)

        # Payment methods are no longer parsed from pages at all — they live
        # only in config/payment_methods.json, keyed by provider domain, and
        # are looked up (never mechanically extracted) at export time. All
        # this step does is make sure every provider we attempt to price this
        # run has an entry in that file, creating an empty one if missing so
        # the file grows to cover the full provider set for manual curation.
        payment_methods_map = load_payment_methods_map()

        # Step 3: Process each provider
        for provider in providers:
            try:
                pricing_urls = find_pricing_pages(provider.website_url)
                if pricing_urls:
                    summary.pricing_pages_found += len(pricing_urls)
                    provider.pricing_url = pricing_urls[0]
                    if ensure_payment_methods_entry(provider.domain, payment_methods_map):
                        save_payment_methods_map(payment_methods_map)

                for url in pricing_urls:
                    fetched = fetch(url)
                    cleaned = clean_html(fetched.html, url, fetched.http_status)
                    snapshot_path = save_snapshot(provider.id, cleaned)

                    # Check previous content hash to avoid duplicate AI calls
                    prev_snapshot = db.query(SourceSnapshot).filter(
                        SourceSnapshot.provider_id == provider.id,
                        SourceSnapshot.source_url == url,
                    ).order_by(SourceSnapshot.fetched_at.desc()).first()

                    if prev_snapshot and prev_snapshot.content_hash == cleaned.content_hash:
                        logger.info(f"Page content unchanged for {url}. Skipping AI extraction.", extra={"pipeline_step": "snapshot_check", "provider_id": provider.id})
                        continue

                    # Record new snapshot in DB
                    snap_record = SourceSnapshot(
                        provider_id=provider.id,
                        source_url=url,
                        http_status=cleaned.http_status,
                        content_hash=cleaned.content_hash,
                        snapshot_path=snapshot_path,
                    )
                    db.add(snap_record)
                    db.commit()

                    # AI Price Extraction
                    ai_result = extract_prices_with_ai(cleaned, url, provider_id=provider.id)
                    validated_items = validate_ai_result(ai_result, cleaned)
                    summary.prices_extracted += len(validated_items)

                    save_prices(provider, validated_items, url, db=db)

                # Update trust signals (HTTP, HTTPS, RDAP)
                update_trust_signals(provider, db=db)

            except Exception as e:
                logger.error(f"Error processing provider {provider.domain}: {e}", extra={"pipeline_step": "process_provider", "provider_id": provider.id, "error_type": type(e).__name__})
                summary.errors_count += 1

        # Expire stale unconfirmed prices from previous runs
        expire_unconfirmed_prices(db=db, run_start_time=run_start_dt)

        # Step 4: Export frontend JSON and review CSV
        publishable_rows = select_publishable_prices(db=db)
        summary.prices_published = len(publishable_rows)

        try:
            export_frontend_json_atomically(publishable_rows)
        except Exception as e:
            logger.error(f"Atomic frontend export failed: {e}", extra={"pipeline_step": "export_frontend", "error_type": type(e).__name__})
            summary.hard_failure = True

        export_review_csv(db=db)
        summary.records_needing_review = db.query(ProviderPrice).filter(ProviderPrice.needs_review == True).count()

    except Exception as e:
        logger.error(f"Fatal error in run_update_all: {e}", extra={"pipeline_step": "update_all", "error_type": type(e).__name__})
        summary.hard_failure = True
        summary.errors_count += 1
    finally:
        db.close()
        summary.duration_seconds = round(time.monotonic() - start_time, 2)

    return summary
