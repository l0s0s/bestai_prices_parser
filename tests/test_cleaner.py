import pytest
from app.crawler.cleaner import clean_html, detect_language, collapse_repeated_boilerplate, merge_fragmented_price_lines


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


def test_nav_with_bare_pricing_word_is_removed():
    """A nav 'Pricing' menu link (no digit) must not survive just because the
    word 'pricing' appears — that word appears in the nav of every pricing
    page this parser targets, so keeping it defeats the filter entirely."""
    raw_html = """
    <html><body>
      <nav>
        <a href="/pricing">Pricing</a>
        <a href="/docs">Docs</a>
        <button>Contact sales</button>
      </nav>
      <table>
        <tr><th>Model</th><th>Input</th></tr>
        <tr><td>GPT-4o</td><td>$2.50 / 1M</td></tr>
      </table>
    </body></html>
    """
    cleaned = clean_html(raw_html, "https://example.com/pricing")
    assert "Contact sales" not in cleaned.text
    assert "GPT-4o" in cleaned.text
    assert "$2.50 / 1M" in cleaned.text


def test_nav_with_real_price_evidence_is_kept():
    raw_html = """
    <html><body>
      <nav>Input pricing: $2.50 / 1M tokens for GPT-4o</nav>
      <p>filler</p>
    </body></html>
    """
    cleaned = clean_html(raw_html, "https://example.com/pricing")
    assert "$2.50 / 1M" in cleaned.text


def test_collapse_repeated_boilerplate_drops_excess_digit_free_repeats():
    lines = ["Contact sales"] * 9 + ["Try Claude"] * 6 + ["$2 / MTok"] * 5
    collapsed = collapse_repeated_boilerplate(lines)
    assert collapsed.count("Contact sales") == 3
    assert collapsed.count("Try Claude") == 3
    # Lines containing a digit (real price data) are never collapsed, no matter
    # how many times they legitimately repeat (e.g. same price across tiers).
    assert collapsed.count("$2 / MTok") == 5


def test_collapse_repeated_boilerplate_keeps_infrequent_lines_untouched():
    lines = ["Home", "Docs", "Pricing", "Home"]
    assert collapse_repeated_boilerplate(lines) == lines


def test_merge_fragmented_price_lines_stitches_span_split_price():
    # Mirrors real markup where currency symbol, value and unit are separate
    # inline <span> children, e.g. anthropic.com/pricing.
    lines = ["Input", "$", "10", "/ MTok", "Output", "$", "50", "/ MTok"]
    merged = merge_fragmented_price_lines(lines)
    assert merged == ["Input", "$10 / MTok", "Output", "$50 / MTok"]


def test_clean_html_stitches_span_split_price_end_to_end():
    raw_html = """
    <html><body>
      <div class="tokens_main_val"><span>$</span><span data-value="10">10</span><span> / MTok</span></div>
    </body></html>
    """
    cleaned = clean_html(raw_html, "https://example.com/pricing")
    assert "$10 / MTok" in cleaned.text
