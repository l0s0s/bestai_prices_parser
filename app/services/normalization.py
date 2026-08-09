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


# A token made up of only digits, dots, colons and parens — never letters —
# so it reads as a harmless date/snapshot stamp ("2024", "(2024", "06)"),
# not a distinct named variant. See the fuzzy-match comment in
# normalize_model_name().
_SNAPSHOT_TOKEN_RE = re.compile(r"^[()\d.:]*$")


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

    # Treat whitespace, "/" and "_" as the same token separator as "-" so
    # vendor-prefixed forms like "deepseek-ai/DeepSeek-R1" line up with the
    # "-"-only alias keys, both for the exact lookup and the fuzzy fallback.
    clean_name = re.sub(r"[\s/_]+", "-", source_name.strip().lower())

    if clean_name in aliases:
        return aliases[clean_name]

    # Token-boundary-aware fuzzy fallback. A raw substring check (`k in
    # clean_name`) lets a short alias key match inside an unrelated name that
    # merely happens to contain the same letters — e.g. the alias "o1" (for
    # OpenAI o1) matches inside "sao10k-l3-8b-lunaris" (a completely different,
    # unrelated open-weight model on Novita), silently mislabeling it as
    # OpenAI o1 pricing with needs_review left False. Splitting both sides
    # into "-"-delimited tokens and requiring the alias key's tokens to line
    # up as a contiguous run of whole tokens inside the name keeps the
    # intended matches while rejecting ones that only line up mid-token.
    #
    # Token-boundary alignment alone is still not enough to decide whether a
    # match is safe — it depends on which side carries the leftover tokens:
    #
    # - Leftover tokens BEFORE the match (e.g. "deepseek-ai" before
    #   "deepseek-r1") are a harmless vendor/org namespace prefix, as in the
    #   HuggingFace-style "deepseek-ai/DeepSeek-R1" naming this fallback was
    #   built for — always safe to bridge.
    # - Leftover tokens AFTER the match (e.g. "1106", "preview" after "gpt-4")
    #   denote a real, differently-priced variant. Accepting these guessed a
    #   short/generic alias key ("gpt-4") onto a longer, more specific real
    #   SKU ("gpt-4-1106-preview", GPT-4 Turbo preview) — confirmed live on a
    #   sunyears.com listing this audit, where it silently attached the wrong
    #   official baseline to a real published price. Only bridge trailing
    #   tokens that are pure digit/date/snapshot stamps (e.g. "2024", "08",
    #   "(2024", "06)") — never a lettered qualifier.
    # - The reverse shape — the source name is a shortened/generic form of a
    #   MORE specific alias key (e.g. "Qwen" is a prefix of "qwen-max";
    #   "gemini-3.1-pro" is a prefix of "gemini-3.1-pro-preview") — is never
    #   bridged at all: accepting it means guessing which specific variant a
    #   vaguer source name meant, which TZ explicitly forbids ("не угадывать
    #   отсутствующие значения").
    name_tokens = clean_name.split("-")
    for k, v in aliases.items():
        key_tokens = k.split("-")
        if key_tokens == name_tokens:
            continue  # already handled by the exact dict lookup above
        n, m = len(name_tokens), len(key_tokens)
        if m > n:
            continue
        for start in range(n - m + 1):
            if name_tokens[start:start + m] != key_tokens:
                continue
            trailing = name_tokens[start + m:]
            if all(_SNAPSHOT_TOKEN_RE.match(t) for t in trailing):
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

    # needs_review can already be True here with no review_reason — the AI is
    # allowed to set needs_review=true on its own (per prompt: "if ambiguous,
    # set needs_review=true") without explaining why. Each check below used to
    # gate on "not needs_review" to avoid clobbering an earlier, more specific
    # reason, but that also meant an AI-set-but-unexplained flag silently ate
    # every later check, leaving review_reason blank in the CSV. Gate on
    # "not review_reason" instead: still first-reason-wins, but a blank reason
    # always gets filled in.
    if not canonical_id and not review_reason:
        review_reason = "unknown_model"
    needs_review = needs_review or not canonical_id

    # Multiplier handling
    multiplier = parse_multiplier_value(entry)
    if multiplier is not None:
        if multiplier <= 0 or multiplier > 100:
            needs_review = True
            if not review_reason:
                review_reason = "unclear_multiplier"

    # Currency conversion rate to USD
    currency = (entry.currency or "USD").upper().strip()
    rate = fx_rates.get(currency, 1.0 if currency == "USD" else None)

    if rate is None:
        needs_review = True
        if not review_reason:
            review_reason = "unclear_price_unit"
        # Regardless of whether this is the first or a later-found issue, an
        # unresolvable currency must never reach the multiplication below as
        # None — that crashes the whole provider (float * NoneType) instead of
        # just flagging the one price for review.
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
        needs_review = True
        if not review_reason:
            review_reason = "unclear_price_unit"

    # `unit` is a single field applied to both input and output — it cannot
    # represent a page where the two are billed on different token scales
    # (e.g. "$3.75 / million input tokens" next to "$0.01 / thousand output
    # tokens", seen live on Replicate). Applying one unit_multiplier to both
    # in that case silently under- or over-scales one of the two prices by
    # 1000x. Detect the mixed-unit signature in raw_price_text itself and
    # force manual review rather than trust either field's placement.
    raw_lower = (entry.raw_price_text or "").lower()
    has_million_marker = bool(re.search(r"\bmillion\b|\b1m\b", raw_lower))
    has_thousand_marker = bool(re.search(r"\bthousand\b|\b1k\b", raw_lower))
    if entry.input_price is not None and entry.output_price is not None and has_million_marker and has_thousand_marker:
        needs_review = True
        if not review_reason:
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

    # Last-resort catch-all: the AI can flag needs_review=true for reasons none
    # of the mechanical checks above catch (e.g. it judged the text ambiguous
    # for a reason outside this code's checklist). Never let a flagged record
    # reach the review CSV with a blank reason column — that leaves a human
    # reviewer with no clue what to look at.
    if needs_review and not review_reason:
        review_reason = "ai_flagged_ambiguous"

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
