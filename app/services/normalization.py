import json
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict

from app.ai.schemas import RawPriceEntry
from app.settings import settings
from app.logging_setup import logger


@dataclass
class NormalizedPrice:
    canonical_model_id: Optional[str]
    source_model_name: str
    input_price_usd_per_1m: Optional[float]
    output_price_usd_per_1m: Optional[float]
    official_input_price_usd_per_1m: Optional[float]
    official_output_price_usd_per_1m: Optional[float]
    input_discount_percent: Optional[float]
    output_discount_percent: Optional[float]
    is_cheaper_than_official: bool
    needs_review: bool
    review_reason: Optional[str]


def load_model_aliases() -> Dict[str, str]:
    path = Path(settings.model_aliases_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_fx_rates() -> Dict[str, float]:
    path = Path(settings.fx_rates_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("rates", {"USD": 1.0, "CNY": 0.138})
    return {"USD": 1.0, "CNY": 0.138}


def load_official_prices() -> Dict[str, dict]:
    path = Path(settings.official_prices_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def normalize_model_name(source_name: str, aliases: Dict[str, str] = None) -> Optional[str]:
    """Map source model name to canonical ID."""
    if aliases is None:
        aliases = load_model_aliases()

    clean_name = source_name.strip().lower().replace(" ", "-")

    if clean_name in aliases:
        return aliases[clean_name]

    for k, v in aliases.items():
        if k in clean_name or clean_name in k:
            return v

    return None


def parse_multiplier_value(entry: RawPriceEntry) -> Optional[float]:
    """Extract price multiplier value (e.g. 0.3x, 5折=0.5x, 4x)."""
    if entry.price_multiplier is not None:
        return float(entry.price_multiplier)

    raw = entry.raw_price_text or ""

    # Check Chinese discount notation: e.g., 5折 => 0.5, 3折 => 0.3
    zhe_match = re.search(r"([1-9](\.[0-9])?)\s*折", raw)
    if zhe_match:
        return float(zhe_match.group(1)) / 10.0

    # Check multiplier notation: e.g., 0.3x, 0.3倍
    mult_match = re.search(r"([0-9]+\.?[0-9]*)\s*(x|倍|折)", raw, re.IGNORECASE)
    if mult_match:
        return float(mult_match.group(1))

    return None


def normalize_price_entry(
    entry: RawPriceEntry,
    aliases: Dict[str, str] = None,
    fx_rates: Dict[str, float] = None,
    official_prices: Dict[str, dict] = None,
) -> NormalizedPrice:
    """Normalize currency, token units, price multipliers and official baseline comparison."""
    if aliases is None:
        aliases = load_model_aliases()
    if fx_rates is None:
        fx_rates = load_fx_rates()
    if official_prices is None:
        official_prices = load_official_prices()

    canonical_id = normalize_model_name(entry.source_model_name, aliases)
    needs_review = entry.needs_review
    review_reason = entry.review_reason

    if not canonical_id and not needs_review:
        needs_review = True
        review_reason = "unknown_model"

    # Multiplier handling
    multiplier = parse_multiplier_value(entry)
    if multiplier is not None:
        if multiplier <= 0 or multiplier > 100:
            if not needs_review:
                needs_review = True
                review_reason = "unclear_multiplier"

    # Currency conversion rate to USD
    currency = (entry.currency or "USD").upper().strip()
    rate = fx_rates.get(currency, 1.0 if currency == "USD" else None)

    if rate is None and not needs_review:
        needs_review = True
        review_reason = "unclear_price_unit"
        rate = 1.0

    # Token unit conversion (1K -> 1M)
    unit_multiplier = 1.0
    unit_clean = (entry.unit or "1m_tokens").lower().strip()
    if "1k" in unit_clean or "thousand" in unit_clean:
        unit_multiplier = 1000.0
    elif "1m" in unit_clean or "million" in unit_clean or "token" in unit_clean:
        unit_multiplier = 1.0
    elif "request" in unit_clean or "call" in unit_clean:
        unit_multiplier = 1.0
    else:
        if not needs_review:
            needs_review = True
            review_reason = "unclear_price_unit"

    # Baseline info
    off_info = official_prices.get(canonical_id) if canonical_id else None
    off_inp = off_info.get("input_usd_per_1m") if off_info else None
    off_out = off_info.get("output_usd_per_1m") if off_info else None

    # Calculate input price in USD per 1M tokens
    input_usd_1m = None
    if entry.input_price is not None and entry.input_price > 0:
        input_usd_1m = round(entry.input_price * rate * unit_multiplier, 6)
    elif multiplier is not None and off_inp and off_inp > 0 and (multiplier > 0 and multiplier <= 10):
        # Apply multiplier to baseline if explicit raw price missing
        input_usd_1m = round(off_inp * multiplier, 6)

    # Calculate output price in USD per 1M tokens
    output_usd_1m = None
    if entry.output_price is not None and entry.output_price > 0:
        output_usd_1m = round(entry.output_price * rate * unit_multiplier, 6)
    elif multiplier is not None and off_out and off_out > 0 and (multiplier > 0 and multiplier <= 10):
        output_usd_1m = round(off_out * multiplier, 6)

    # Re-check multiplier application to direct raw input/output if multiplier was given
    if multiplier is not None and (0 < multiplier <= 10) and entry.input_price and entry.input_price > 0:
        if off_inp and input_usd_1m and input_usd_1m > off_inp * 2:
            # Multiplier was incorrectly multiplied on an already baseline price or relative value
            input_usd_1m = round(off_inp * multiplier, 6)

    inp_disc = None
    out_disc = None
    is_cheaper = False

    if canonical_id and off_info:
        if input_usd_1m is not None and off_inp and off_inp > 0:
            inp_disc = round((1.0 - (input_usd_1m / off_inp)) * 100.0, 1)

        if output_usd_1m is not None and off_out and off_out > 0:
            out_disc = round((1.0 - (output_usd_1m / off_out)) * 100.0, 1)

        inp_ok = (input_usd_1m is None) or (off_inp and input_usd_1m < off_inp)
        out_ok = (output_usd_1m is None) or (off_out and output_usd_1m < off_out)
        is_cheaper = bool(inp_ok and out_ok and (input_usd_1m is not None or output_usd_1m is not None))

    return NormalizedPrice(
        canonical_model_id=canonical_id,
        source_model_name=entry.source_model_name,
        input_price_usd_per_1m=input_usd_1m,
        output_price_usd_per_1m=output_usd_1m,
        official_input_price_usd_per_1m=off_inp,
        official_output_price_usd_per_1m=off_out,
        input_discount_percent=inp_disc,
        output_discount_percent=out_disc,
        is_cheaper_than_official=is_cheaper,
        needs_review=needs_review,
        review_reason=review_reason,
    )
