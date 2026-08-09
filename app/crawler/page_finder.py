from urllib.parse import urljoin, urlparse
from typing import List, Tuple, Dict
from bs4 import BeautifulSoup
import httpx

from app.crawler.fetcher import fetch
from app.sources.dom_utils import extract_domain, clean_url
from app.ai.extractor import rank_pricing_links
from app.logging_setup import logger
from app.settings import settings

CANDIDATE_KEYWORDS = ["pricing", "prices", "models", "billing", "docs", "api", "价格", "计费", "模型"]
CANDIDATE_PATHS = ["/pricing", "/prices", "/models", "/docs", "/api", "/billing"]


def verify_http_200(url: str) -> bool:
    """Verify if target URL responds with HTTP status 200."""
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
            resp = client.head(url)
            if resp.status_code == 200:
                return True
            # Retry with GET if HEAD is forbidden/not allowed
            resp = client.get(url)
            return resp.status_code == 200
    except Exception:
        return False


def find_pricing_pages(website_url: str) -> List[str]:
    """Find top candidate pricing/docs URLs on provider website verifying HTTP 200."""
    base_domain = extract_domain(website_url)
    fetched = fetch(website_url)

    candidate_map: Dict[str, Dict] = {}

    if fetched.http_status == 200 and fetched.html:
        soup = BeautifulSoup(fetched.html, "lxml")

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            anchor_text = a.get_text(strip=True).lower()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            full_url = clean_url(urljoin(website_url, href))
            url_domain = extract_domain(full_url)
            if url_domain != base_domain:
                continue

            score = 0
            url_path = urlparse(full_url).path.lower()

            for kw in CANDIDATE_KEYWORDS:
                if kw in anchor_text:
                    score += 3
                if kw in url_path:
                    score += 2

            if score > 0:
                if full_url not in candidate_map or candidate_map[full_url]["score"] < score:
                    candidate_map[full_url] = {
                        "url": full_url,
                        "anchor_text": anchor_text[:100],
                        "score": score,
                    }

    # Sort candidates by score descending
    sorted_candidates = sorted(candidate_map.values(), key=lambda x: x["score"], reverse=True)

    # Verify HTTP 200 for top scored candidate URLs
    verified_urls = []
    for item in sorted_candidates:
        url = item["url"]
        if verify_http_200(url):
            verified_urls.append(url)
        if len(verified_urls) >= 3:
            break

    # Always also probe the standard candidate paths, not only when the
    # homepage yielded zero scored links. A single weak homepage match (e.g.
    # a nav item like "API Platform" that only scores on the generic "api"
    # keyword) used to suppress this fallback entirely — confirmed live on
    # sunyears.com, where the homepage's one scored link was a marketing
    # overview page with no prices at all, while the real pricing table at
    # /models.html was never reachable in a single hop from the homepage and
    # so never got tried. Backfilling here (skipping URLs already verified
    # above, still capped at 3 total) means a weak or wrong homepage match no
    # longer starves out the well-known standard paths.
    for path in CANDIDATE_PATHS:
        if len(verified_urls) >= 3:
            break
        target_url = clean_url(urljoin(website_url, path))
        if target_url in verified_urls:
            continue
        if verify_http_200(target_url):
            verified_urls.append(target_url)

    # AI ranking if candidates > 3 or top candidates have identical score
    if len(sorted_candidates) > 3:
        top_candidates = sorted_candidates[:5]
        chosen_ai_url = rank_pricing_links(top_candidates, website_url)
        if chosen_ai_url in verified_urls:
            # Move chosen AI URL to first position
            verified_urls.remove(chosen_ai_url)
            verified_urls.insert(0, chosen_ai_url)

    # Fallback to website_url if still empty
    if not verified_urls:
        verified_urls = [website_url]

    return verified_urls
