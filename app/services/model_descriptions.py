import json
from pathlib import Path
from typing import Dict, Optional

from app.settings import settings


def load_model_descriptions() -> Dict[str, dict]:
    """Load the manually-curated canonical_model_id -> description map.

    Bilingual (RU/EN) SEO copy for each model, maintained by hand in
    config/model_descriptions.json, outside the pipeline — mirrors
    config/payment_methods.json in app/services/payment_methods.py. Nothing
    here is generated or verified automatically; missing entries are simply
    left out of the export rather than guessed (see select_model_catalog in
    app/services/price_extraction.py)."""
    path = Path(settings.model_descriptions_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_model_description(canonical_model_id: str, data: Dict[str, dict] = None) -> Optional[dict]:
    """Read-only lookup by canonical_model_id. Missing entries return None."""
    if data is None:
        data = load_model_descriptions()
    return data.get(canonical_model_id)
