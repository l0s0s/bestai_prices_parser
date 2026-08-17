import csv
import json
import os
from pathlib import Path
from typing import List
from sqlalchemy.orm import Session

from app.models import ProviderPrice
from app.services.frontend_schema import (
    validate_frontend_json,
    validate_model_catalog_json,
    validate_api_descriptions_json,
)
from app.settings import settings
from app.logging_setup import logger


def export_frontend_json_atomically(rows: List[dict]) -> None:
    """Atomically write public/data/providers.json after schema validation."""
    target_path = Path(settings.frontend_json_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target_path.with_suffix(".json.tmp")

    # Validate schema
    validate_frontend_json(rows)

    # Write tmp file
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    # Set 0644 permissions
    os.chmod(tmp_path, 0o644)

    # Atomic rename
    os.replace(tmp_path, target_path)
    logger.info(f"Successfully exported {len(rows)} records to {target_path}", extra={"pipeline_step": "export_frontend"})


def export_models_json_atomically(rows: List[dict]) -> None:
    """Atomically write public/data/models.json after schema validation."""
    target_path = Path(settings.models_json_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target_path.with_suffix(".json.tmp")

    validate_model_catalog_json(rows)

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    os.chmod(tmp_path, 0o644)

    os.replace(tmp_path, target_path)
    logger.info(f"Successfully exported {len(rows)} records to {target_path}", extra={"pipeline_step": "export_models"})


def export_api_descriptions_json_atomically(rows: List[dict]) -> None:
    """Atomically write public/data/api_descriptions.json after schema validation."""
    target_path = Path(settings.api_descriptions_json_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target_path.with_suffix(".json.tmp")

    validate_api_descriptions_json(rows)

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    os.chmod(tmp_path, 0o644)

    os.replace(tmp_path, target_path)
    logger.info(f"Successfully exported {len(rows)} records to {target_path}", extra={"pipeline_step": "export_api_descriptions"})


def export_review_csv(db: Session) -> str:
    """Export records needing manual review to CSV."""
    review_path = Path(settings.review_csv_path)
    review_path.parent.mkdir(parents=True, exist_ok=True)

    review_prices = db.query(ProviderPrice).filter(ProviderPrice.needs_review == True).all()

    fieldnames = [
        "provider_name",
        "domain",
        "source_model_name",
        "canonical_model_id",
        "raw_price_text",
        "raw_currency",
        "raw_unit",
        "confidence",
        "review_reason",
        "source_url",
        "last_checked_at",
    ]

    with open(review_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for price in review_prices:
            provider = price.provider
            writer.writerow({
                "provider_name": provider.name if provider else "",
                "domain": provider.domain if provider else "",
                "source_model_name": price.source_model_name,
                "canonical_model_id": price.canonical_model_id or "",
                "raw_price_text": price.raw_price_text,
                "raw_currency": price.raw_currency,
                "raw_unit": price.raw_unit,
                "confidence": price.confidence,
                "review_reason": price.review_reason or "",
                "source_url": price.source_url,
                "last_checked_at": price.last_checked_at.isoformat() + "Z" if price.last_checked_at else "",
            })

    logger.info(f"Exported {len(review_prices)} review records to {review_path}", extra={"pipeline_step": "export_review"})
    return str(review_path)
