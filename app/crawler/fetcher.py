from dataclasses import dataclass
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.logging_setup import logger
from app.settings import settings


@dataclass
class FetchResult:
    html: str
    http_status: int
    final_url: str
    via: str  # "httpx" | "playwright"


MIN_CONTENT_LEN = 200


def _rendered_text_len(html: str) -> int:
    """Estimate how much real, human-readable text an HTML payload carries,
    ignoring <script>/<style> bulk.

    A raw byte-length check on the HTML alone is a poor proxy for "did this
    page actually load": a client-rendered SPA shell can easily ship 50-100KB
    of bundled JavaScript in <script> tags while the actual DOM has no text
    at all until that JS runs — confirmed live on multiple real AI-provider
    pricing pages this audit (e.g. Qwen, Stability AI, Cerebras), all of
    which returned 200 with large HTML but an empty rendered page. Measuring
    on raw byte count let those pass as "successfully fetched" and never
    triggered the Playwright fallback TZ requires for JS-rendered pages,
    even on sites where Playwright demonstrably recovers real pricing
    content (e.g. platform.stability.ai/pricing: 0 chars via httpx's raw
    HTML, 6000+ chars of genuine pricing text via Playwright)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return len(soup.get_text(strip=True))


def fetch_httpx(url: str) -> FetchResult:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        return FetchResult(
            html=resp.text,
            http_status=resp.status_code,
            final_url=str(resp.url),
            via="httpx",
        )


def fetch_playwright(url: str) -> FetchResult:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            response = page.goto(url, wait_until="networkidle", timeout=settings.playwright_timeout_seconds * 1000)
            status = response.status if response else 200
            content = page.content()
            final_url = page.url
            browser.close()
            return FetchResult(
                html=content,
                http_status=status,
                final_url=final_url,
                via="playwright",
            )
    except Exception as e:
        logger.warning(f"Playwright fetch failed for {url}: {e}", extra={"pipeline_step": "fetch_playwright"})
        return FetchResult(html="", http_status=500, final_url=url, via="playwright")


def fetch(url: str) -> FetchResult:
    """Fetch URL via HTTPX with fallback to Playwright."""
    try:
        res = fetch_httpx(url)
        if res.http_status == 200 and _rendered_text_len(res.html) >= MIN_CONTENT_LEN:
            return res
        logger.info(f"httpx returned status {res.http_status} or rendered text len < {MIN_CONTENT_LEN} for {url}. Trying Playwright.", extra={"pipeline_step": "fetch"})
    except Exception as e:
        logger.info(f"httpx fetch error for {url}: {e}. Trying Playwright.", extra={"pipeline_step": "fetch"})

    return fetch_playwright(url)
