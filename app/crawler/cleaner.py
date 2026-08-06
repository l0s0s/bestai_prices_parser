import hashlib
import re
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


PRICE_PATTERN = re.compile(r"(\$|¥|USD|CNY|EUR|RUB|token|per|1M|1K|1M_tokens|1K_tokens|pricing|cost|rate|倍率|折|计费|价格|模型)", re.IGNORECASE)


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

    # Collapse multiple blank lines
    lines = [line.strip() for line in text_content.split("\n") if line.strip()]
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
