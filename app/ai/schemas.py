from typing import Optional, List
from pydantic import BaseModel, Field


class RawPriceEntry(BaseModel):
    source_model_name: str
    input_price: Optional[float] = None
    output_price: Optional[float] = None
    currency: str = "USD"
    unit: str = "1M_tokens"  # "1K_tokens" | "1M_tokens" | "request" | ...
    price_multiplier: Optional[float] = None
    raw_price_text: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    needs_review: bool = False
    review_reason: Optional[str] = None


class AiExtractionResult(BaseModel):
    source_url: str
    page_language: Optional[str] = None
    prices: List[RawPriceEntry] = []
