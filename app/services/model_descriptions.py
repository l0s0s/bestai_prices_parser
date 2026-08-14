import json
from pathlib import Path
from typing import Dict, Optional

from app.settings import settings


def _normalize_dashes(value):
    """Replace em dashes (—) with en dashes (–) throughout a loaded value.

    Descriptions are hand-authored (often via an LLM), which tends to write
    em dashes; RU/EN catalog copy should use the short dash instead. Applied
    recursively at load time so it's caught once, regardless of how an entry
    was written."""
    if isinstance(value, str):
        return value.replace("—", "–")
    if isinstance(value, dict):
        return {k: _normalize_dashes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_dashes(v) for v in value]
    return value


def load_model_descriptions() -> Dict[str, dict]:
    """Load the manually-curated canonical_model_id -> description map.

    Bilingual (RU/EN) SEO copy for each model, maintained by hand in
    config/model_descriptions.json, outside the pipeline — mirrors
    config/payment_methods.json in app/services/payment_methods.py. Nothing
    here is generated or verified automatically; missing entries are simply
    left out of the export rather than guessed (see select_model_catalog in
    app/services/price_extraction.py). Em dashes are normalized to en dashes
    on load (see _normalize_dashes)."""
    path = Path(settings.model_descriptions_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return _normalize_dashes(json.load(f))
    return {}


def get_model_description(canonical_model_id: str, data: Dict[str, dict] = None) -> Optional[dict]:
    """Read-only lookup by canonical_model_id. Missing entries return None."""
    if data is None:
        data = load_model_descriptions()
    return data.get(canonical_model_id)
