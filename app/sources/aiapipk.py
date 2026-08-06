from typing import List
import httpx
from bs4 import BeautifulSoup
from app.sources.base import SourceAdapter, DiscoveredProvider
from app.sources.dom_utils import extract_domain, clean_url, clean_provider_name
from app.logging_setup import logger
from app.settings import settings


class AIAPIPKAdapter(SourceAdapter):
    source_id = "aiapipk"
    url = "https://www.aiapipk.com/"

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
            logger.warning(f"[aiapipk] HTTP fetch failed: {e}. Falling back to Playwright.", extra={"pipeline_step": "crawl_source"})

        if not html_content or len(html_content.strip()) < 500:
            html_content = self._fetch_playwright(self.url)

        if not html_content:
            logger.error("[aiapipk] Failed to retrieve content.", extra={"pipeline_step": "crawl_source", "error_type": "fetch_empty"})
            return providers

        soup = BeautifulSoup(html_content, "lxml")
        seen_domains = set()

        # Parse table rows <tr> or card blocks
        rows = soup.find_all("tr")
        if len(rows) > 1:
            for row in rows:
                cols = row.find_all(["td", "th"])
                if not cols:
                    continue

                link = row.find("a", href=True)
                if not link:
                    continue

                href = str(link["href"]).strip()
                if not href.startswith("http") or "aiapipk.com" in href:
                    continue

                # Extract provider name from column 0 or title text, avoiding CTA button text
                col_text = cols[0].get_text(strip=True) if len(cols) > 0 else ""
                target_url = clean_url(href)
                domain = extract_domain(target_url)
                provider_name = clean_provider_name(col_text, domain)

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

        # Fallback to links if table parsing found no items
        if not providers:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("http") and "aiapipk.com" not in href:
                    target_url = clean_url(href)
                    domain = extract_domain(target_url)
                    parent = a.parent
                    parent_text = parent.get_text(" ", strip=True) if parent else ""
                    provider_name = clean_provider_name(parent_text, domain)

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
            logger.error(f"[aiapipk] Playwright fetch failed: {e}", extra={"pipeline_step": "crawl_source", "error_type": "playwright_error"})
            return ""
