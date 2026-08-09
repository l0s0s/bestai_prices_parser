from typing import List
import httpx
from bs4 import BeautifulSoup
from app.sources.base import SourceAdapter, DiscoveredProvider
from app.sources.dom_utils import extract_domain, clean_url, clean_provider_name
from app.logging_setup import logger
from app.settings import settings


class VeridropAdapter(SourceAdapter):
    source_id = "veridrop"
    url = "https://veridrop.org/relays/certified"

    def crawl(self) -> List[DiscoveredProvider]:
        providers: List[DiscoveredProvider] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        html_content = ""
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True, headers=headers) as client:
                resp = client.get(self.url)
                if resp.status_code == 200:
                    html_content = resp.text
        except Exception as e:
            logger.warning(f"[veridrop] HTTP fetch failed: {e}. Falling back to Playwright.", extra={"pipeline_step": "crawl_source"})

        if not html_content or len(html_content.strip()) < 500:
            html_content = self._fetch_playwright(self.url)

        if not html_content:
            logger.error("[veridrop] Failed to retrieve content.", extra={"pipeline_step": "crawl_source", "error_type": "fetch_empty"})
            return providers

        soup = BeautifulSoup(html_content, "lxml")
        seen_domains = set()

        # Extract elements with data-impression-domain attribute
        domain_elements = soup.select("[data-impression-domain]")
        for el in domain_elements:
            raw_domain = str(el.get("data-impression-domain", "")).strip()
            if not raw_domain:
                continue

            target_url = clean_url(f"https://{raw_domain}")
            domain = extract_domain(target_url)

            # el.get_text(strip=True) on the whole relay-row card glues together
            # unrelated text nodes with no separator — avatar initial, domain,
            # "last checked" status line and the "前往 →" link all run together
            # into one unreadable string. The domain itself lives in a dedicated
            # ".relay-domain" span; prefer that and fall back to the full card
            # text only if the page structure changes.
            name_el = el.select_one(".relay-domain")
            raw_text = name_el.get_text(strip=True) if name_el else el.get_text(strip=True)
            provider_name = clean_provider_name(raw_text, domain)

            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                providers.append(
                    DiscoveredProvider(
                        provider_name=provider_name,
                        domain=domain,
                        website_url=target_url,
                        catalog_source=self.source_id,
                        catalog_page_url=self.url
                    )
                )

        # Fallback to links if no data-impression-domain attribute found
        if not providers:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("http") and "veridrop.org" not in href:
                    target_url = clean_url(href)
                    domain = extract_domain(target_url)
                    provider_name = clean_provider_name(a.get_text(strip=True), domain)

                    if domain and domain not in seen_domains:
                        seen_domains.add(domain)
                        providers.append(
                            DiscoveredProvider(
                                provider_name=provider_name,
                                domain=domain,
                                website_url=target_url,
                                catalog_source=self.source_id,
                                catalog_page_url=self.url
                            )
                        )

        logger.info(f"[veridrop] Discovered {len(providers)} providers from relay elements.", extra={"pipeline_step": "crawl_source"})
        return providers

    def _fetch_playwright(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=settings.playwright_timeout_seconds * 1000)
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            logger.error(f"[veridrop] Playwright fetch failed: {e}", extra={"pipeline_step": "crawl_source", "error_type": "playwright_error"})
            return ""
