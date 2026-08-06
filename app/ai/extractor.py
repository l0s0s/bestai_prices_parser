import json
from pathlib import Path
from pydantic import ValidationError
from app.ai.client import AiClient
from app.ai.schemas import AiExtractionResult
from app.crawler.cleaner import CleanedPage
from app.logging_setup import logger
from app.settings import settings


def get_system_prompt() -> str:
    prompt_path = Path(settings.extraction_prompt_file)
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return (
        "Извлеки только цены AI API из переданного текста.\n"
        "Не используй знания из памяти и не угадывай отсутствующие значения.\n"
        "Для каждой цены сохрани точный фрагмент страницы в raw_price_text.\n"
        "Разделяй input и output price.\n"
        "Не пересчитывай валюту и единицы.\n"
        "Если значение неоднозначно, установи needs_review=true.\n"
        "Верни только JSON по переданной JSON Schema.\n"
    )


def extract_prices_with_ai(snapshot: CleanedPage, source_url: str, provider_id: int = 0) -> AiExtractionResult:
    """Extract prices from cleaned page using AI agent with retries."""
    ai_client = AiClient()
    system_prompt = get_system_prompt()
    schema = AiExtractionResult.model_json_schema()

    last_error = None
    for attempt in range(settings.ai_max_retries + 1):
        try:
            raw_text = ai_client.extract(system_prompt, source_url, snapshot.text, schema)
            result = AiExtractionResult.model_validate_json(raw_text)

            logger.info(
                f"Successfully extracted {len(result.prices)} prices (attempt {attempt + 1})",
                extra={
                    "pipeline_step": "extract_prices",
                    "provider_id": provider_id,
                    "source_url": source_url,
                }
            )
            return result

        except (ValidationError, json.JSONDecodeError) as e:
            last_error = e
            logger.warning(
                f"AI extraction validation failed on attempt {attempt + 1}: {e}",
                extra={
                    "pipeline_step": "extract_prices",
                    "provider_id": provider_id,
                    "source_url": source_url,
                    "error_type": type(e).__name__,
                }
            )

    # If retries exhausted, return empty result with error logged
    logger.error(
        f"Failed AI extraction for {source_url} after {settings.ai_max_retries + 1} attempts: {last_error}",
        extra={
            "pipeline_step": "extract_prices",
            "provider_id": provider_id,
            "source_url": source_url,
            "error_type": "invalid_json",
        }
    )

    return AiExtractionResult(source_url=source_url, prices=[])


def rank_pricing_links(candidates: list[dict], website_url: str) -> str:
    """Use AI agent to rank ambiguous pricing page candidates, choosing ONLY from candidates list."""
    if not candidates:
        return website_url
    if len(candidates) == 1:
        return candidates[0].get("url", website_url)

    ai_client = AiClient()
    schema = {
        "type": "object",
        "required": ["chosen_url"],
        "properties": {
            "chosen_url": {"type": "string"}
        }
    }

    system_prompt = (
        "Выбери ТОЛЬКО ОДИН самый вероятный URL страницы цен/тарифной сетки API "
        "из предоставленного списка кандидатов. Не придумывай новые URL."
    )

    valid_urls = [c.get("url") for c in candidates if c.get("url")]

    try:
        raw_res = ai_client.extract(system_prompt, website_url, json.dumps(candidates, ensure_ascii=False), schema)
        parsed = json.loads(raw_res)
        chosen = parsed.get("chosen_url")
        if chosen in valid_urls:
            return chosen
    except Exception as e:
        logger.info(f"AI link ranking fallback to top scored URL: {e}", extra={"pipeline_step": "page_finder"})

    return valid_urls[0] if valid_urls else website_url
