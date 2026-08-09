from dataclasses import dataclass

from app.crawler import page_finder


@dataclass
class _FakeFetchResult:
    html: str
    http_status: int
    final_url: str
    via: str = "httpx"


def test_find_pricing_pages_still_probes_standard_paths_with_a_weak_homepage_match(monkeypatch):
    """Reproduces a real bug found live on sunyears.com: the homepage's only
    scored link was a generic marketing page ("SunYears API Platform", which
    only matches the loose "api" keyword) with no prices on it at all, while
    the real pricing table at /models.html was never linked from the
    homepage in a single hop. Because that one weak homepage match made
    verified_urls non-empty, the standard-path fallback used to be skipped
    entirely, so /models.html was never even tried. It must still be probed
    and included alongside the homepage match."""

    homepage_html = """
    <html><body>
      <a href="/products#api">SunYears API Platform</a>
    </body></html>
    """

    def fake_fetch(url):
        if url == "https://example.com":
            return _FakeFetchResult(html=homepage_html, http_status=200, final_url=url)
        return _FakeFetchResult(html="", http_status=404, final_url=url)

    def fake_verify(url):
        # The weak homepage candidate and the real pricing page both exist;
        # other standard paths (billing, prices, docs, api) do not.
        return url in ("https://example.com/products#api", "https://example.com/models")

    monkeypatch.setattr(page_finder, "fetch", fake_fetch)
    monkeypatch.setattr(page_finder, "verify_http_200", fake_verify)

    urls = page_finder.find_pricing_pages("https://example.com")

    assert "https://example.com/models" in urls, (
        "the real pricing page must still be probed even though a weaker "
        "homepage-scanned candidate already exists"
    )
    assert "https://example.com/products#api" in urls
