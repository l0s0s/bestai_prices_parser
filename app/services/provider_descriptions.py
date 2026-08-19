import json
from pathlib import Path
from typing import Dict, List, Optional

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


def build_provider_descriptions(descriptions: Optional[Dict[str, dict]] = None) -> List[dict]:
    """Build the public per-provider card catalog (public/data/provider_descriptions.json).

    One row per entry in config/provider_descriptions.json, sorted by
    provider_domain for stable output. Not filtered against currently
    publishable providers in public/data/providers.json — same approach as
    build_api_descriptions in app/services/api_descriptions.py; the frontend
    joins by provider_domain and simply has no card to show for domains not
    currently published."""
    if descriptions is None:
        descriptions = load_provider_descriptions()
    return [
        {
            "provider_domain": domain,
            "description_ru": entry.get("description_ru", ""),
            "description_en": entry.get("description_en", ""),
        }
        for domain, entry in sorted(descriptions.items())
    ]
