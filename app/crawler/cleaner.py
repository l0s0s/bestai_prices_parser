import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup, Tag

from app.settings import settings
from app.logging_setup import logger


@dataclass
class CleanedPage:
    source_url: str
    text: str
    language: str
    http_status: int
    fetched_at: datetime
    content_hash: str


# Requires an actual digit next to a currency symbol / token-unit ratio / CN pricing
# notation — NOT bare words like "pricing"/"cost"/"rate"/"per"/"token". The old
# keyword-only pattern matched nav link labels such as "Pricing" on every provider's
# own pricing page (the exact page this parser targets), so nav/header/footer blocks
# were almost never actually removed there, flooding the AI with repeated CTA noise.
PRICE_PATTERN = re.compile(
    r"(\$\s?\d|¥\s?\d|\d[\d,]*\.?\d*\s?(USD|CNY|EUR|RUB)\b"
    r"|\d[\d,]*\.?\d*\s?/\s?(1M|1K|MTok)\b|每(百万|千)|\d+\s?折|倍率)",
    re.IGNORECASE,
)

# Short, digit-free lines that repeat more than this many times are almost always
# duplicate DOM markup (the same CTA/nav label rendered once per responsive
# breakpoint), not distinct content. Genuine price lines always contain a digit
# and are therefore never touched by this collapse.
BOILERPLATE_MAX_REPEATS = 3

CURRENCY_SYMBOLS = {"$", "¥", "€", "£"}
_BARE_NUMBER = re.compile(r"[\d,]+\.?\d*")


def merge_fragmented_price_lines(lines: list) -> list:
    """Re-join a bare currency symbol + its numeric value + its '/ unit' suffix
    when a site renders each in its own inline <span> for styling. BeautifulSoup's
    get_text(separator="\\n") otherwise splits "$10 / MTok" into three separate,
    unreadable lines ("$", "10", "/ MTok"), which starves the AI extractor of a
    recognizable price pattern even though the value is technically present."""
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line in CURRENCY_SYMBOLS and i + 1 < len(lines) and _BARE_NUMBER.fullmatch(lines[i + 1]):
            combined = line + lines[i + 1]
            i += 2
            if i < len(lines) and lines[i].startswith("/"):
                combined += " " + lines[i]
                i += 1
            merged.append(combined)
            continue
        merged.append(line)
        i += 1
    return merged


def collapse_repeated_boilerplate(lines: list) -> list:
    """Drop excess repeats of digit-free lines that show up many times due to
    responsive/duplicate DOM markup (e.g. the same 'Contact sales' button
    rendered once per breakpoint). Lines containing a digit are always kept in
    full, since real price rows must never be dropped by this heuristic."""
    counts = Counter(line.lower() for line in lines)
    seen = Counter()
    result = []
    for line in lines:
        key = line.lower()
        if not any(ch.isdigit() for ch in line) and counts[key] > BOILERPLATE_MAX_REPEATS:
            seen[key] += 1
            if seen[key] > BOILERPLATE_MAX_REPEATS:
                continue
        result.append(line)
    return result


def detect_language(text: str) -> str:
    """Basic language detection based on CJK character presence."""
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk_count >= 5:
        return "zh"
    return "en"


def table_to_markdown(table: Tag) -> str:
    """Convert HTML <table> element to Markdown table string."""
    rows = table.find_all("tr")
    if not rows:
        return ""

    md_lines = []
    for i, row in enumerate(rows):
        cols = row.find_all(["th", "td"])
        col_texts = [c.get_text(" ", strip=True).replace("\n", " ") for c in cols]
        if not col_texts or not any(col_texts):
            continue
        md_lines.append("| " + " | ".join(col_texts) + " |")

        # Header separator after first row
        if i == 0 and len(cols) > 0:
            md_lines.append("| " + " | ".join(["---"] * len(cols)) + " |")

    return "\n".join(md_lines)


def clean_html(html_content: str, source_url: str, http_status: int = 200) -> CleanedPage:
    """Clean HTML into Markdown/plain text, compute sha256 content hash."""
    if not html_content:
        now = datetime.utcnow()
        return CleanedPage(
            source_url=source_url,
            text="",
            language="en",
            http_status=http_status,
            fetched_at=now,
            content_hash=hashlib.sha256(b"").hexdigest(),
        )

    soup = BeautifulSoup(html_content, "lxml")

    # Remove script, style, iframe, noscript
    for tag in soup(["script", "style", "iframe", "noscript"]):
        tag.decompose()

    # Remove nav, header, footer unless they contain pricing tables or symbols
    for tag_name in ["nav", "header", "footer"]:
        for el in soup.find_all(tag_name):
            text_val = el.get_text()
            if not el.find("table") and not PRICE_PATTERN.search(text_val):
                el.decompose()

    # Convert tables to markdown
    for table in soup.find_all("table"):
        md_table = table_to_markdown(table)
        table.replace_with("\n\n" + md_table + "\n\n")

    # Extract text from remaining elements
    text_content = soup.get_text(separator="\n", strip=True)

    # Collapse multiple blank lines, re-stitch price fragments split across inline
    # spans, then collapse repeated boilerplate (nav/CTA duplicated across
    # responsive breakpoints) while preserving every price line.
    lines = [line.strip() for line in text_content.split("\n") if line.strip()]
    lines = merge_fragmented_price_lines(lines)
    lines = collapse_repeated_boilerplate(lines)
    cleaned_text = "\n".join(lines)

    content_hash = hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest()
    language = detect_language(cleaned_text)
    now = datetime.utcnow()

    return CleanedPage(
        source_url=source_url,
        text=cleaned_text,
        language=language,
        http_status=http_status,
        fetched_at=now,
        content_hash=content_hash,
    )


def save_snapshot(provider_id: int, cleaned: CleanedPage) -> str:
    """Save cleaned text snapshot to snapshots/ directory."""
    settings.ensure_directories()
    filename = f"{provider_id}_{cleaned.content_hash[:12]}.txt"
    filepath = Path(settings.snapshots_dir) / filename

    header = (
        f"URL: {cleaned.source_url}\n"
        f"Fetched: {cleaned.fetched_at.isoformat()}Z\n"
        f"Status: {cleaned.http_status}\n"
        f"Language: {cleaned.language}\n"
        f"Content-Hash: {cleaned.content_hash}\n"
        "----------------------------------------\n"
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(header + cleaned.text)

    return str(filepath)
