from datetime import datetime
from typing import Tuple, Optional
import httpx
from sqlalchemy.orm import Session

from app.models import Provider
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
