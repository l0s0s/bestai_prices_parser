from typing import List, Dict, Optional
import httpx
from bs4 import BeautifulSoup
from app.sources.base import SourceAdapter, DiscoveredProvider
from app.sources.dom_utils import extract_domain, clean_url, clean_provider_name
from app.logging_setup import logger
from app.settings import settings

SLUG_DOMAIN_MAP: Dict[str, str] = {
    "openai": "https://openai.com",
    "anthropic": "https://anthropic.com",
    "azure-openai": "https://azure.microsoft.com/en-us/products/ai-services/openai-service/",
    "openrouter": "https://openrouter.ai",
    "deepseek": "https://deepseek.com",
    "google-gemini": "https://gemini.google.com",
    "aliyun-qwen": "https://aliyun.com",
    "groq": "https://groq.com",
    "together-ai": "https://together.ai",
    "fireworks-ai": "https://fireworks.ai",
    "siliconflow": "https://siliconflow.cn",
    "novita-ai": "https://novita.ai",
    "mistral-ai": "https://mistral.ai",
    "perplexity": "https://perplexity.ai",
    "cohere": "https://cohere.com",
    "stability-ai": "https://platform.stability.ai",
    "amazon-bedrock": "https://aws.amazon.com/bedrock/",
    "voyage-ai": "https://voyageai.com",
    "fal-ai": "https://fal.ai",
    "nvidia-nim": "https://build.nvidia.com",
}

IGNORED_EXTERNAL_DOMAINS = {"apirank.vip", "about.me", "twitter.com", "x.com", "github.com", "t.me"}


class APIRankAdapter(SourceAdapter):
    source_id = "apirank"
    url = "https://apirank.vip/providers/"

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
            logger.warning(f"[apirank] HTTP fetch failed: {e}. Falling back to Playwright.", extra={"pipeline_step": "crawl_source"})

        if not html_content or len(html_content.strip()) < 500:
            html_content = self._fetch_playwright(self.url)

        if not html_content:
            logger.error("[apirank] Failed to retrieve content.", extra={"pipeline_step": "crawl_source", "error_type": "fetch_empty"})
            return providers

        soup = BeautifulSoup(html_content, "lxml")
        seen_domains = set()

        rows = soup.find_all("tr")
        for r in rows:
            cols = r.find_all(["td", "th"])
            if len(cols) < 2:
                continue

            raw_name = cols[1].get_text(strip=True)
            if not raw_name or raw_name.lower() in ["provider", "name", "провайдер"]:
                continue

            link = r.find("a", href=True)
            if not link:
                continue

            href = str(link["href"]).strip()

            target_url = None
            if href.startswith("http") and "apirank.vip" not in href:
                target_url = clean_url(href)
            elif "/providers/" in href:
                slug = href.split("/providers/")[-1].strip("/").lower()
                if slug in SLUG_DOMAIN_MAP:
                    target_url = SLUG_DOMAIN_MAP[slug]
                else:
                    # Fetch detail page to extract exact official website URL
                    detail_url = f"https://apirank.vip/providers/{slug}"
                    target_url = self._extract_url_from_detail_page(detail_url, headers)

            if not target_url:
                target_url = f"https://apirank.vip{href}" if href.startswith("/") else self.url

            domain = extract_domain(target_url)
            provider_name = clean_provider_name(raw_name, domain)

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

        logger.info(f"[apirank] Discovered {len(providers)} providers from table rows and detail pages.", extra={"pipeline_step": "crawl_source"})
        return providers

    def _extract_url_from_detail_page(self, detail_url: str, headers: dict) -> Optional[str]:
        """Fetch APIRank detail page and extract exact official website URL without domain guessing."""
        try:
            with httpx.Client(timeout=4.0, follow_redirects=True, headers=headers) as client:
                resp = client.get(detail_url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    for a in soup.find_all("a", href=True):
                        h = a["href"].strip()
                        if h.startswith("http"):
                            d = extract_domain(h)
                            if d not in IGNORED_EXTERNAL_DOMAINS:
                                return clean_url(h)
        except Exception as e:
            logger.info(f"[apirank] Detail page fetch failed for {detail_url}: {e}", extra={"pipeline_step": "crawl_source"})
        return None

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
            logger.error(f"[apirank] Playwright fetch failed: {e}", extra={"pipeline_step": "crawl_source", "error_type": "playwright_error"})
            return ""
