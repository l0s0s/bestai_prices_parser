import re
from urllib.parse import urlparse
import tldextract


GENERIC_CTA_PATTERNS = [
    r"访问官网",
    r"官网",
    r"перейти\s+на\s+сайт",
    r"visit\s+site",
    r"visit\s+official\s+site",
    r"official\s+website",
    r"website",
    r"link",
    r"click\s+here",
    r"go\s+to\s+site",
    r"http[s]?://",
]

CTA_REGEX = re.compile("|".join(GENERIC_CTA_PATTERNS), re.IGNORECASE)


def extract_domain(url: str) -> str:
    """Extract registered domain in lower case without www."""
    extracted = tldextract.extract(url)
    domain_val = getattr(extracted, "top_domain_under_public_suffix", None) or getattr(extracted, "registered_domain", "")
    if domain_val:
        return domain_val.lower()
    parsed = urlparse(url)
    hostname = parsed.hostname or url
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname.lower()


def clean_url(url: str) -> str:
    """Ensure valid HTTP/HTTPS scheme and clean URL string."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def clean_provider_name(name: str, domain: str) -> str:
    """Clean provider name and filter out CTA button strings like '访问官网'."""
    if not name:
        name = ""

    cleaned = name.strip()

    # If name is a CTA phrase or too short/generic, derive fallback from domain
    if not cleaned or len(cleaned) < 2 or CTA_REGEX.search(cleaned):
        main_part = domain.split(".")[0]
        if main_part in ["com", "org", "net", "vip", "ai", "io"]:
            parts = domain.split(".")
            main_part = parts[0] if len(parts) > 1 else domain
        return main_part.capitalize() + " API"

    return cleaned[:100]
