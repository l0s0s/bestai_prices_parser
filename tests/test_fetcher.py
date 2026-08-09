from dataclasses import dataclass

from app.crawler import fetcher


@dataclass
class _FakeFetchResult:
    html: str
    http_status: int
    final_url: str
    via: str = "httpx"


def test_fetch_falls_back_to_playwright_when_html_is_a_script_only_spa_shell(monkeypatch):
    """Reproduces a real bug found live on multiple AI-provider pricing pages
    (Qwen, Stability AI, Cerebras): httpx returns HTTP 200 with a large HTML
    payload that is almost entirely <script> bundle bytes for a
    client-rendered SPA, with essentially zero real text in the DOM until
    JS executes. A raw-byte-length check on that HTML easily clears
    MIN_CONTENT_LEN and wrongly short-circuits before Playwright — which
    can render the real content — ever gets a chance to run."""
    spa_shell_html = "<html><head></head><body>" + ("<script>var x = 1;</script>" * 50) + "</body></html>"
    assert len(spa_shell_html) >= fetcher.MIN_CONTENT_LEN  # raw bytes alone would have passed the old check

    def fake_fetch_httpx(url):
        return _FakeFetchResult(html=spa_shell_html, http_status=200, final_url=url, via="httpx")

    called = {"playwright": False}

    def fake_fetch_playwright(url):
        called["playwright"] = True
        return _FakeFetchResult(html="<html><body>Real rendered pricing content</body></html>", http_status=200, final_url=url, via="playwright")

    monkeypatch.setattr(fetcher, "fetch_httpx", fake_fetch_httpx)
    monkeypatch.setattr(fetcher, "fetch_playwright", fake_fetch_playwright)

    result = fetcher.fetch("https://example.com/pricing")

    assert called["playwright"] is True
    assert result.via == "playwright"


def test_fetch_keeps_httpx_result_when_it_has_real_rendered_text(monkeypatch):
    real_html = "<html><body><h1>Pricing</h1>" + ("<p>Model X costs $1 per 1M tokens.</p>" * 10) + "</body></html>"

    def fake_fetch_httpx(url):
        return _FakeFetchResult(html=real_html, http_status=200, final_url=url, via="httpx")

    def fake_fetch_playwright(url):
        raise AssertionError("Playwright should not be called when httpx already returned real content")

    monkeypatch.setattr(fetcher, "fetch_httpx", fake_fetch_httpx)
    monkeypatch.setattr(fetcher, "fetch_playwright", fake_fetch_playwright)

    result = fetcher.fetch("https://example.com/pricing")

    assert result.via == "httpx"
