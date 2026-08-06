import jsonschema

FRONTEND_JSON_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": [
            "provider_name",
            "provider_domain",
            "provider_url",
            "model_name",
            "canonical_model_id",
            "input_price_usd_per_1m",
            "output_price_usd_per_1m",
            "trust_status",
            "source_url",
            "last_checked_at",
        ],
        "properties": {
            "provider_name": {"type": "string"},
            "provider_domain": {"type": "string"},
            "provider_url": {"type": "string"},
            "model_name": {"type": "string"},
            "canonical_model_id": {"type": ["string", "null"]},
            "input_price_usd_per_1m": {"type": ["number", "null"]},
            "output_price_usd_per_1m": {"type": ["number", "null"]},
            "official_input_price_usd_per_1m": {"type": ["number", "null"]},
            "official_output_price_usd_per_1m": {"type": ["number", "null"]},
            "input_discount_percent": {"type": ["number", "null"]},
            "output_discount_percent": {"type": ["number", "null"]},
            "trust_status": {"type": "string", "enum": ["green", "yellow", "red"]},
            "source_url": {"type": "string"},
            "last_checked_at": {"type": "string"},
        },
    },
}


def validate_frontend_json(data: list) -> None:
    """Validate output data list against JSON schema."""
    jsonschema.validate(instance=data, schema=FRONTEND_JSON_SCHEMA)
