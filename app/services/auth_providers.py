import json
from pathlib import Path
from typing import List, Tuple

from app.services.exporter import export_frontend_json_atomically
from app.services.frontend_schema import validate_frontend_json
from app.settings import settings
from app.logging_setup import logger


def load_auth_providers() -> List[dict]:
    """Load the manually-curated rows for providers whose pricing sits behind
    a login/signup wall and so can't be auto-scraped by the crawl pipeline.

    Same row shape as public/data/providers.json (see FRONTEND_JSON_SCHEMA in
    app/services/frontend_schema.py), maintained by hand outside the
    pipeline, entirely in this file."""
    path = Path(settings.auth_providers_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_auth_providers(rows: List[dict]) -> None:
    path = Path(settings.auth_providers_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _row_key(row: dict) -> Tuple[str, str]:
    """Identity used to decide whether a row is already present in the main
    file: provider domain + canonical model id when known, else provider
    domain + raw model name."""
    domain = (row.get("provider_domain") or "").strip().lower()
    model_key = row.get("canonical_model_id") or row.get("model_name") or ""
    return domain, model_key


def sync_auth_providers_into_frontend_json() -> int:
    """Merge rows from public/data/auth_providers.json into the already-published
    public/data/providers.json, adding only rows whose (provider_domain,
    canonical_model_id/model_name) combination isn't already present there.
    Existing rows sourced from the crawl pipeline are never overwritten or
    removed. Returns the number of rows added.

    `update-all` (see app/orchestrator.py) calls this automatically right
    after it rebuilds providers.json from the database, so the auth-only
    providers keep showing up in the published output without a manual step.
    Call this directly only when publishing an edit to
    public/data/auth_providers.json without re-running the full pipeline.
    """
    target_path = Path(settings.frontend_json_path)
    if not target_path.exists():
        raise FileNotFoundError(
            f"{target_path} does not exist yet; run the full pipeline (update-all) at least once first."
        )

    with open(target_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    auth_rows = load_auth_providers()
    validate_frontend_json(auth_rows)

    existing_keys = {_row_key(row) for row in rows}

    added = 0
    for row in auth_rows:
        key = _row_key(row)
        if key in existing_keys:
            continue
        rows.append(row)
        existing_keys.add(key)
        added += 1

    if added:
        export_frontend_json_atomically(rows)
        logger.info(
            f"Synced {added} row(s) from {settings.auth_providers_file} into {target_path}.",
            extra={"pipeline_step": "sync_auth_providers"},
        )
    else:
        logger.info(
            f"No new rows to add from {settings.auth_providers_file} into {target_path}.",
            extra={"pipeline_step": "sync_auth_providers"},
        )

    return added
