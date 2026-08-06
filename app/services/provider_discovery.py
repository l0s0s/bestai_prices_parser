import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor
import httpx
from sqlalchemy.orm import Session

from app.sources.base import DiscoveredProvider, SourceAdapter
from app.sources.apirank import APIRankAdapter
from app.sources.aiapipk import AIAPIPKAdapter
from app.sources.veridrop import VeridropAdapter
from app.sources.dom_utils import extract_domain, clean_url
from app.models import Provider, ProviderSource
from app.db import SessionLocal
from app.logging_setup import logger
from app.settings import settings

ADAPTER_MAP: Dict[str, type[SourceAdapter]] = {
    "apirank": APIRankAdapter,
    "aiapipk": AIAPIPKAdapter,
    "veridrop": VeridropAdapter,
}


def crawl_enabled_sources() -> List[DiscoveredProvider]:
    """Load config/sources.json and execute enabled adapters."""
    sources_path = Path(settings.sources_file)
    if not sources_path.exists():
        logger.error(f"Sources file not found at {sources_path}", extra={"pipeline_step": "crawl_sources"})
        return []

    with open(sources_path, "r", encoding="utf-8") as f:
        sources_config = json.load(f)

    discovered: List[DiscoveredProvider] = []

    for item in sources_config:
        if not item.get("enabled", False):
            continue

        source_id = item.get("id")
        adapter_cls = ADAPTER_MAP.get(source_id)
        if not adapter_cls:
            logger.warning(f"No adapter registered for source id: {source_id}", extra={"pipeline_step": "crawl_sources"})
            continue

        try:
            adapter = adapter_cls()
            logger.info(f"Crawling source catalog: {source_id}", extra={"pipeline_step": "crawl_sources"})
            rows = adapter.crawl()
            logger.info(f"Source {source_id} returned {len(rows)} providers", extra={"pipeline_step": "crawl_sources"})
            discovered.extend(rows)
        except Exception as e:
            logger.error(f"Error crawling source {source_id}: {e}", extra={"pipeline_step": "crawl_sources", "error_type": type(e).__name__})

    return discovered


def resolve_final_domain(website_url: str, domain_cache: Dict[str, str]) -> tuple[str, str]:
    """Follow up to 2 HTTP redirects to determine canonical domain and URL (TZ Step 2)."""
    if website_url in domain_cache:
        cached_domain = domain_cache[website_url]
        return cached_domain, website_url

    canonical_url = clean_url(website_url)
    canonical_domain = extract_domain(canonical_url)

    # Perform HTTP redirect resolution if URL is remote
    if canonical_url.startswith("http") and "apirank.vip" not in canonical_url and "veridrop.org" not in canonical_url:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            with httpx.Client(timeout=2.0, follow_redirects=True, max_redirects=2, headers=headers) as client:
                resp = client.head(canonical_url)
                if resp.status_code < 400:
                    canonical_url = clean_url(str(resp.url))
                    canonical_domain = extract_domain(canonical_url)
        except Exception:
            pass

    domain_cache[website_url] = canonical_domain
    return canonical_domain, canonical_url


def normalize_and_deduplicate(discovered_rows: List[DiscoveredProvider], db: Session = None) -> List[Provider]:
    """Group by final domain, upsert Providers and ProviderSources in DB using concurrent redirect resolution."""
    should_close_db = False
    if db is None:
        db = SessionLocal()
        should_close_db = True

    try:
        domain_cache: Dict[str, str] = {}

        def process_item(item: DiscoveredProvider):
            domain, final_url = resolve_final_domain(item.website_url, domain_cache)
            item.domain = domain
            item.website_url = final_url
            return item

        with ThreadPoolExecutor(max_workers=20) as executor:
            resolved_items = list(executor.map(process_item, discovered_rows))

        grouped: Dict[str, List[DiscoveredProvider]] = {}
        for item in resolved_items:
            grouped.setdefault(item.domain, []).append(item)

        saved_providers: List[Provider] = []
        now = datetime.utcnow()

        for domain, items in grouped.items():
            if not domain:
                continue

            # Pick cleanest provider name
            best_name = sorted(items, key=lambda x: len(x.provider_name))[0].provider_name
            best_url = items[0].website_url

            # Query existing provider in DB
            provider = db.query(Provider).filter(Provider.domain == domain).first()
            if not provider:
                provider = Provider(
                    name=best_name,
                    domain=domain,
                    website_url=best_url,
                    trust_status="yellow",
                    last_checked_at=now,
                )
                db.add(provider)
                db.flush()
            else:
                provider.name = best_name
                provider.website_url = best_url
                provider.last_checked_at = now

            # Save catalog sources
            for item in items:
                existing_source = db.query(ProviderSource).filter(
                    ProviderSource.provider_id == provider.id,
                    ProviderSource.catalog_source == item.catalog_source,
                ).first()

                if not existing_source:
                    ps = ProviderSource(
                        provider_id=provider.id,
                        catalog_source=item.catalog_source,
                        catalog_page_url=item.catalog_page_url,
                        catalog_rating=item.catalog_rating,
                        catalog_reviews_count=item.catalog_reviews_count,
                        discovered_at=now,
                    )
                    db.add(ps)

            saved_providers.append(provider)

        db.commit()
        return saved_providers
    finally:
        if should_close_db:
            db.close()
