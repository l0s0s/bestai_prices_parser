import json
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.settings import settings
from app.services.model_descriptions import _normalize_dashes


def load_provider_descriptions() -> Dict[str, dict]:
    """Load the manually-curated provider domain -> description map used to
    render per-reseller intro cards ("<Provider name> — <what it is> — ...").

    Maintained by hand in config/provider_descriptions.json, outside the
    pipeline — mirrors config/payment_methods.json (app/services/payment_methods.py)
    and config/model_descriptions.json (app/services/model_descriptions.py).
    Nothing here is generated or verified automatically; missing entries are
    simply left out of the export rather than guessed. Em dashes are
    normalized to en dashes on load (see _normalize_dashes)."""
    path = Path(settings.provider_descriptions_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return _normalize_dashes(json.load(f))
    return {}


def get_provider_description(provider_domain: str, data: Dict[str, dict] = None) -> Optional[dict]:
    """Read-only lookup by provider domain. Missing entries return None."""
    if data is None:
        data = load_provider_descriptions()
    return data.get(provider_domain)


def load_published_provider_domains() -> Set[str]:
    """Read the set of provider_domain values currently present in
    public/data/providers.json (the crawl-pipeline export). Used to filter
    which description cards get published, so a stale or not-yet-live entry
    in config/provider_descriptions.json doesn't leak into the output.
    Returns an empty set, rather than raising, if providers.json doesn't
    exist yet."""
    path = Path(settings.frontend_json_path)
    if not path.exists():
        return set()
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return {row["provider_domain"] for row in rows if row.get("provider_domain")}


def build_provider_descriptions(
    descriptions: Optional[Dict[str, dict]] = None,
    published_domains: Optional[Set[str]] = None,
) -> List[dict]:
    """Build the public per-provider card catalog (public/data/provider_descriptions.json).

    One row per entry in config/provider_descriptions.json, sorted by
    provider_domain for stable output. When `published_domains` is given,
    only entries whose domain is in that set are included — pass the result
    of load_published_provider_domains() to restrict output to providers
    currently present in public/data/providers.json. Leave it None (the
    default) to emit every curated entry unfiltered, e.g. for testing."""
    if descriptions is None:
        descriptions = load_provider_descriptions()
    items = sorted(descriptions.items())
    if published_domains is not None:
        items = [(domain, entry) for domain, entry in items if domain in published_domains]
    return [
        {
            "provider_domain": domain,
            "description_ru": entry.get("description_ru", ""),
            "description_en": entry.get("description_en", ""),
        }
        for domain, entry in items
    ]
