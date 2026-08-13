import json
from pathlib import Path
from typing import Dict, List

from app.services.exporter import export_frontend_json_atomically
from app.settings import settings
from app.logging_setup import logger


def load_payment_methods_map() -> Dict[str, List[str]]:
    """Load the manually-curated provider domain -> payment methods map.

    Payment methods are no longer parsed from pages at all (previously an AI
    field mechanically re-verified against page text). They now live only in
    this file, keyed by provider domain, maintained by hand outside the
    pipeline."""
    path = Path(settings.payment_methods_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_payment_methods_map(data: Dict[str, List[str]]) -> None:
    path = Path(settings.payment_methods_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def get_payment_methods(provider_domain: str, data: Dict[str, List[str]] = None) -> List[str]:
    """Read-only lookup by provider domain. Missing entries return []."""
    if data is None:
        data = load_payment_methods_map()
    return list(data.get(provider_domain) or [])


def ensure_payment_methods_entry(provider_domain: str, data: Dict[str, List[str]]) -> bool:
    """Make sure `data` has an entry for this domain, adding an empty list if
    it doesn't. Mutates `data` in place; returns True if an entry was added,
    so the caller knows whether the map needs to be persisted. Does not touch
    an existing entry, empty or not — an empty list already on file is a
    curated "confirmed none", not a gap to refill."""
    if provider_domain in data:
        return False
    data[provider_domain] = []
    logger.info(
        f"No payment_methods entry for {provider_domain}; added empty entry to {settings.payment_methods_file}.",
        extra={"pipeline_step": "payment_methods_lookup"},
    )
    return True


def sync_payment_methods_into_frontend_json() -> int:
    """Refresh payment_methods on the already-published public/data/providers.json
    from config/payment_methods.json, without re-running the pipeline.

    Reads the existing export as-is, overwrites each row's payment_methods by
    provider_domain lookup, and writes the result back atomically (same path
    export_frontend_json_atomically normally uses). Every other field is left
    untouched. Returns the number of rows whose payment_methods value
    actually changed."""
    target_path = Path(settings.frontend_json_path)
    if not target_path.exists():
        raise FileNotFoundError(
            f"{target_path} does not exist yet; run the full pipeline (update-all) at least once first."
        )

    with open(target_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    payment_map = load_payment_methods_map()

    changed = 0
    for row in rows:
        new_methods = get_payment_methods(row.get("provider_domain", ""), payment_map)
        if row.get("payment_methods") != new_methods:
            changed += 1
        row["payment_methods"] = new_methods

    export_frontend_json_atomically(rows)
    logger.info(
        f"Synced payment_methods for {len(rows)} rows ({changed} changed) into {target_path}.",
        extra={"pipeline_step": "sync_payment_methods"},
    )
    return changed
