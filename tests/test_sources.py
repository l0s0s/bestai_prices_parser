import pytest
from bs4 import BeautifulSoup
from app.sources.dom_utils import extract_domain, clean_url, clean_provider_name
from app.sources.apirank import APIRankAdapter
from app.sources.veridrop import VeridropAdapter
from app.services.provider_discovery import resolve_final_domain


def test_extract_domain():
    assert extract_domain("https://www.openai.com/pricing") == "openai.com"
    assert extract_domain("http://sub.domain.provider.org/path?query=1") == "provider.org"
    assert extract_domain("https://example.cn") == "example.cn"


def test_clean_url():
    assert clean_url("  http://example.com/pricing/  ") == "http://example.com/pricing"
    assert clean_url("domain.com/docs") == "https://domain.com/docs"


def test_clean_provider_name_filters_cta():
    assert clean_provider_name("访问官网", "fastapi.cn") == "Fastapi API"
    assert clean_provider_name("перейти на сайт", "deepseek.com") == "Deepseek API"
    assert clean_provider_name("  OneAPI Pro  ", "oneapi.top") == "OneAPI Pro"


def test_apirank_adapter_table_row_parsing(monkeypatch):
    sample_html = """
    <table>
      <tr><th>#</th><th>Provider</th><th>Models</th><th>Input</th><th>Output</th><th>Link</th></tr>
      <tr><td>#1</td><td>OpenAI</td><td>GPT-4o</td><td>$2.50/M</td><td>$10/M</td><td><a href="/providers/openai">View</a></td></tr>
      <tr><td>#2</td><td>Anthropic Claude</td><td>Claude 3.5</td><td>$3/M</td><td>$15/M</td><td><a href="/providers/anthropic">View</a></td></tr>
    </table>
    """
    adapter = APIRankAdapter()
    monkeypatch.setattr(adapter, "_fetch_playwright", lambda url: sample_html)
    monkeypatch.setattr("httpx.Client.get", lambda self, url, **kwargs: type("Resp", (), {"status_code": 200, "text": sample_html}))

    providers = adapter.crawl()
    assert len(providers) == 2
    domains = [p.domain for p in providers]
    assert "openai.com" in domains
    assert "anthropic.com" in domains


def test_apirank_detail_page_extraction_no_domain_guessing(monkeypatch):
    sample_catalog_html = """
    <table>
      <tr><th>#</th><th>Provider</th><th>Link</th></tr>
      <tr><td>#1</td><td>Custom AI Provider</td><td><a href="/providers/custom-unmapped-slug">View</a></td></tr>
    </table>
    """
    sample_detail_html = """
    <html>
      <body>
        <a href="https://custom-official-domain.ai">Official Website</a>
        <a href="https://about.me/author">Author</a>
      </body>
    </html>
    """

    adapter = APIRankAdapter()
    monkeypatch.setattr(adapter, "_fetch_playwright", lambda url: sample_catalog_html)

    def mock_get(self_client, url, **kwargs):
        url_str = str(url)
        if "custom-unmapped-slug" in url_str:
            return type("Resp", (), {"status_code": 200, "text": sample_detail_html})
        elif url_str == adapter.url:
            return type("Resp", (), {"status_code": 200, "text": sample_catalog_html})
        return type("Resp", (), {"status_code": 404, "text": ""})

    monkeypatch.setattr("httpx.Client.get", mock_get)

    providers = adapter.crawl()
    assert len(providers) == 1
    assert providers[0].domain == "custom-official-domain.ai"
    assert providers[0].website_url == "https://custom-official-domain.ai"


def test_veridrop_adapter_data_impression_domain_parsing(monkeypatch):
    sample_html = """
    <div>
      <a data-impression-domain="api.koozhan.com" href="/relays/1">Koozhan PRO</a>
      <a data-impression-domain="routemux.com" href="/relays/2">Routemux PRO</a>
    </div>
    """
    adapter = VeridropAdapter()
    monkeypatch.setattr(adapter, "_fetch_playwright", lambda url: sample_html)
    monkeypatch.setattr("httpx.Client.get", lambda self, url, **kwargs: type("Resp", (), {"status_code": 200, "text": sample_html}))

    providers = adapter.crawl()
    assert len(providers) == 2
    domains = [p.domain for p in providers]
    assert "api.koozhan.com" in domains or "koozhan.com" in domains
    assert "routemux.com" in domains


def test_resolve_final_domain_cache():
    cache = {}
    domain, url = resolve_final_domain("https://example.com/page", cache)
    assert domain == "example.com"
    assert "https://example.com/page" in cache
