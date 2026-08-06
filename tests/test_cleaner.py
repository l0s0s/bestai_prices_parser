import pytest
from app.crawler.cleaner import clean_html, detect_language


def test_clean_html_tables_and_scripts():
    raw_html = """
    <html>
      <head><script>alert('test');</script></head>
      <body>
        <nav><a href="#">Home</a></nav>
        <h1>API Prices</h1>
        <table>
          <tr><th>Model</th><th>Input</th><th>Output</th></tr>
          <tr><td>GPT-4o</td><td>$2.50 / 1M</td><td>$10.00 / 1M</td></tr>
        </table>
      </body>
    </html>
    """
    cleaned = clean_html(raw_html, "https://example.com/pricing")
    assert "GPT-4o" in cleaned.text
    assert "alert" not in cleaned.text
    assert "| Model | Input | Output |" in cleaned.text
    assert len(cleaned.content_hash) == 64


def test_detect_language():
    assert detect_language("This is English text with prices.") == "en"
    assert detect_language("这是一个中文 AI API 价格表，包含 GPT-4o 模型。") == "zh"
