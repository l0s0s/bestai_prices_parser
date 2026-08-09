import re
from typing import Any, Optional, List
from pydantic import BaseModel, Field, model_validator

# Real runs against multiple AI gateways/models show two recurring, harmless
# schema deviations that otherwise burn all ai_max_retries and drop the whole
# price entry: the model names the field "model"/"model_name" instead of the
# schema's "source_model_name", and it writes prices as strings with currency
# symbols ("$1.25", "1.35 元") instead of bare numbers. Neither is a judgment
# call — coercing them isn't "recalculating a price" (still forbidden), just
# recovering the literal number the AI already wrote in a different shape.
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _coerce_numeric(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        match = _NUMBER_RE.search(value.replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
        return None
    return value


class RawPriceEntry(BaseModel):
    source_model_name: str
    input_price: Optional[float] = None
    output_price: Optional[float] = None
    currency: str = "USD"
    unit: str = "1M_tokens"  # "1K_tokens" | "1M_tokens" | "request" | ...
    price_multiplier: Optional[float] = None
    raw_price_text: str = ""
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    needs_review: bool = False
    review_reason: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_common_ai_deviations(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not data.get("source_model_name"):
            for alt_key in ("model_name", "model", "name"):
                if data.get(alt_key):
                    data["source_model_name"] = data[alt_key]
                    break
        for key in ("input_price", "output_price", "price_multiplier"):
            if key in data:
                data[key] = _coerce_numeric(data[key])
        return data


class AiExtractionResult(BaseModel):
    source_url: str
    page_language: Optional[str] = None
    prices: List[RawPriceEntry] = []
