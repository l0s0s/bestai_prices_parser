import json
from pathlib import Path
from typing import Dict, List, Optional

from app.settings import settings
from app.services.model_descriptions import _normalize_dashes

RU_TITLE_TEMPLATE = "Дешёвый {vendor} API"
RU_BODY_TEMPLATE = (
    "Здесь показаны предложения {vendor} API от разных поставщиков и агрегаторов. "
    "Сравните цену входных и выходных токенов, проверьте поддержку нужных функций и "
    "выберите самый выгодный API-маршрут для подключения модели к приложению, боту, "
    "SaaS-продукту или внутреннему AI-инструменту. Таблица помогает найти модель "
    "дешевле официальной цены и быстро перейти к поставщику с подходящими условиями. "
    "Вы можете сравнить доступные способы оплаты, рейтинг поставщика, отзывы, возраст "
    "сервиса, поддерживаемые возможности модели, лимиты запросов и другие важные "
    "условия перед выбором API-провайдера."
)
EN_TITLE_TEMPLATE = "Cheap {vendor} API"
EN_BODY_TEMPLATE = (
    "Here you'll find {vendor} API offers from different providers and aggregators. "
    "Compare input and output token prices, check support for the features you need, "
    "and choose the best API route for connecting the model to your app, bot, SaaS "
    "product, or internal AI tool. The table helps you find a model cheaper than the "
    "official price and quickly reach a provider with suitable terms. You can compare "
    "available payment methods, provider rating, reviews, service age, supported model "
    "capabilities, request limits, and other important conditions before choosing an "
    "API provider."
)


def load_api_vendors() -> Dict[str, str]:
    """Load the hand-curated vendor_slug -> display_name map used to render
    the "cheap <vendor> API" intro cards.

    Maintained by hand in config/api_vendors.json, independent of which
    vendors currently have models in config/model_descriptions.json — new
    vendors can be added here ahead of the catalog. Includes a "generic"
    entry (display name "AI") for the catch-all "Дешёвый AI API" card. Em
    dashes are normalized to en dashes on load (see _normalize_dashes)."""
    path = Path(settings.api_vendors_file)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return _normalize_dashes(json.load(f))
    return {}


def _render_card(vendor_display_name: str) -> dict:
    """Render the bilingual title/description pair for one vendor, from the
    shared template. All vendor cards (including the generic "AI" one) are
    the same copy with only the vendor name substituted."""
    return _normalize_dashes({
        "title_ru": RU_TITLE_TEMPLATE.format(vendor=vendor_display_name),
        "description_ru": RU_BODY_TEMPLATE.format(vendor=vendor_display_name),
        "title_en": EN_TITLE_TEMPLATE.format(vendor=vendor_display_name),
        "description_en": EN_BODY_TEMPLATE.format(vendor=vendor_display_name),
    })


def build_api_descriptions(vendors: Optional[Dict[str, str]] = None) -> List[dict]:
    """Build the public API-vendor card catalog (public/data/api_descriptions.json).

    One row per entry in config/api_vendors.json, sorted by vendor_slug for
    stable output."""
    if vendors is None:
        vendors = load_api_vendors()
    return [
        {"vendor_slug": slug, "display_name": name, **_render_card(name)}
        for slug, name in sorted(vendors.items())
    ]
