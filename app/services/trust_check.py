import json
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional
import httpx
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Provider
from app.services.exporter import export_frontend_json_atomically
from app.settings import settings
from app.logging_setup import logger


def check_site(website_url: str) -> Tuple[bool, bool]:
    """Check if site is responsive and uses valid HTTPS."""
    site_alive = False
    https_ok = website_url.startswith("https://")

    try:
        with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
            resp = client.get(website_url)
            if resp.status_code < 400:
                site_alive = True
                https_ok = resp.url.scheme == "https"
    except Exception as e:
        logger.info(f"Site check failed for {website_url}: {e}", extra={"pipeline_step": "trust_check"})

    return site_alive, https_ok


def lookup_domain_age(domain: str) -> Tuple[Optional[datetime], Optional[int]]:
    """Fetch domain creation date and age in days via RDAP API."""
    rdap_url = f"https://rdap.org/domain/{domain}"
    try:
        with httpx.Client(timeout=settings.rdap_timeout_seconds, follow_redirects=True) as client:
            resp = client.get(rdap_url)
            if resp.status_code == 200:
                data = resp.json()
                events = data.get("events", [])
                for ev in events:
                    if ev.get("eventAction") in ["registration", "created"]:
                        date_str = ev.get("eventDate")
                        if date_str:
                            # Parse ISO timestamp
                            clean_date = date_str.replace("Z", "+00:00")
                            created_dt = datetime.fromisoformat(clean_date).replace(tzinfo=None)
                            age_days = (datetime.utcnow() - created_dt).days
                            return created_dt, age_days
    except Exception as e:
        logger.info(f"RDAP lookup failed for {domain}: {e}", extra={"pipeline_step": "trust_check"})

    return None, None


def update_domain_age_for_all_providers(db: Session) -> int:
    """Run only the RDAP domain-age lookup for every provider in the DB —
    no site/HTTPS check, no crawling, no AI extraction, no trust_status
    recompute. Lets domain_created_at/domain_age_days be (re)populated on
    demand for the whole provider set without paying for a full update-all
    run. Commits after each provider so a mid-run failure doesn't lose
    already-resolved lookups. Returns the number of providers whose domain
    age was successfully resolved this run (RDAP misses/errors leave the
    existing stored value untouched, same as update_trust_signals)."""
    providers = db.query(Provider).all()
    resolved = 0
    for provider in providers:
        created_at, age_days = lookup_domain_age(provider.domain)
        if created_at:
            provider.domain_created_at = created_at
            provider.domain_age_days = age_days
            resolved += 1
            db.commit()
    return resolved


def update_trust_signals(provider: Provider, db: Session) -> None:
    """Update trust signals and status for a provider."""
    site_alive, https_ok = check_site(provider.website_url)
    created_at, age_days = lookup_domain_age(provider.domain)

    provider.site_alive = site_alive
    provider.https_ok = https_ok
    if created_at:
        provider.domain_created_at = created_at
        provider.domain_age_days = age_days

    pricing_found = bool(provider.pricing_url or provider.docs_url)
    catalog_count = len(provider.sources)

    if site_alive and pricing_found and catalog_count >= 2:
        provider.trust_status = "green"
    elif site_alive and pricing_found:
        provider.trust_status = "yellow"
    else:
        provider.trust_status = "red"

    provider.last_checked_at = datetime.utcnow()
    db.commit()


def sync_domain_age_into_frontend_json() -> int:
    """Refresh domain_created_at/domain_age_days on the already-published
    public/data/providers.json from the values already stored on each
    Provider row, without re-running the full pipeline (no new RDAP calls).

    Mirrors sync_payment_methods_into_frontend_json in
    app/services/payment_methods.py: reads the existing export as-is,
    overwrites each row's two domain-age fields by provider_domain lookup,
    and writes the result back atomically. Every other field is left
    untouched. Returns the number of rows whose domain-age fields actually
    changed."""
    target_path = Path(settings.frontend_json_path)
    if not target_path.exists():
        raise FileNotFoundError(
            f"{target_path} does not exist yet; run the full pipeline (update-all) at least once first."
        )

    with open(target_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    db: Session = SessionLocal()
    try:
        providers_by_domain = {p.domain: p for p in db.query(Provider).all()}

        changed = 0
        for row in rows:
            provider = providers_by_domain.get(row.get("provider_domain", ""))
            new_created_at = (
                provider.domain_created_at.isoformat() + "Z"
                if provider and provider.domain_created_at
                else None
            )
            new_age_days = provider.domain_age_days if provider else None

            if row.get("domain_created_at") != new_created_at or row.get("domain_age_days") != new_age_days:
                changed += 1
            row["domain_created_at"] = new_created_at
            row["domain_age_days"] = new_age_days
    finally:
        db.close()

    export_frontend_json_atomically(rows)
    logger.info(
        f"Synced domain age for {len(rows)} rows ({changed} changed) into {target_path}.",
        extra={"pipeline_step": "sync_domain_age"},
    )
    return changed
