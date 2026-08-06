# План реализации: AI-парсер цен для BestAIPrice

Основано на `bestai_price_parser_tz.md`. Этот документ детализирует ТЗ до уровня файлов, схем данных, интерфейсов и конкретных шагов разработки — по нему можно писать код напрямую, без дополнительных решений "на ходу".

---

## 0. Ключевые технические решения (дополняют ТЗ)

| Вопрос | Решение |
|---|---|
| AI SDK | Официальный `anthropic` Python SDK. `AI_BASE_URL`/`AI_MODEL` в `.env` оставляем настраиваемыми (как в ТЗ) — это даёт свободу сменить модель без правки кода, но по умолчанию используем Anthropic Structured Output (`output_config.format`, JSON Schema). |
| Модель по умолчанию | `claude-sonnet-4-6` (или актуальный `claude-sonnet-5`, если ключ его поддерживает) — баланс цены/качества для structured extraction на ~20-50 провайдеров/сутки. `claude-haiku-4-5` — fallback для снижения стоимости, если бюджет важнее качества извлечения нестандартных таблиц (китайские сайты, `0.3x` коэффициенты). Решение по конкретной модели — параметр `.env`, не хардкод. |
| Prompt caching | `extraction_prompt.txt` + JSON Schema — стабильный префикс на каждый вызов. Кэшируем через `cache_control: {"type": "ephemeral"}` на системном промпте — при десятках провайдеров в сутки это заметная экономия. |
| ORM | SQLAlchemy 2.0 (declarative, typed) + Alembic не нужен на MVP — миграции через `init-db` (create_all), т.к. схема фиксирована на 5 дней. |
| HTTP | `httpx.Client` с ретраями через `tenacity` (3 попытки, экспоненциальный backoff), таймаут 15с на обычный fetch. |
| Браузер | Playwright Chromium, headless, только как fallback (пустой контент/страница защищена JS-рендером). |
| CLI | `Typer` — соответствует ТЗ. |
| Тесты | `pytest` + `respx`/`httpx` мок-транспорт для сетевых тестов, фикстуры HTML-страниц в `tests/fixtures/`. |

---

## 1. Структура репозитория (финальная)

```
bestai_prices_parser/
  app/
    __init__.py
    cli.py
    settings.py
    db.py
    models.py
    sources/
      __init__.py
      base.py
      apirank.py
      aiapipk.py
      veridrop.py
    crawler/
      __init__.py
      fetcher.py
      page_finder.py
      cleaner.py
    ai/
      __init__.py
      client.py            # тонкая обёртка над anthropic SDK / произвольным AI_BASE_URL
      extractor.py
      schemas.py
    services/
      __init__.py
      provider_discovery.py
      price_extraction.py
      normalization.py
      trust_check.py
      exporter.py
      frontend_schema.py    # JSON Schema для providers.json
  config/
    sources.json
    extraction_prompt.txt
    model_aliases.json
    official_prices.json
  data/                      # sqlite (gitignored)
  snapshots/                 # gitignored
  exports/                   # review_prices.csv (gitignored)
  logs/                      # gitignored
  public/data/               # providers.json — локальный dev-выход (gitignored на проде)
  tests/
    fixtures/
      apirank_page.html
      aiapipk_page.html
      veridrop_page.html
      pricing_page_openai_like.html
    test_sources.py
    test_page_finder.py
    test_cleaner.py
    test_normalization.py
    test_trust_check.py
    test_exporter.py
    test_ai_validation.py
  .env.example
  requirements.txt
  pyproject.toml             # ruff/black конфиг, опционально
  README.md
```

---

## 2. Конфигурация

### `.env.example`
```dotenv
AI_API_KEY=
AI_BASE_URL=https://api.anthropic.com
AI_MODEL=claude-sonnet-4-6
AI_TIMEOUT_SECONDS=60
AI_MAX_RETRIES=2
AI_MIN_CONFIDENCE=0.80

DATABASE_URL=sqlite:///data/bestai.db
SOURCES_FILE=config/sources.json
MODEL_ALIASES_FILE=config/model_aliases.json
OFFICIAL_PRICES_FILE=config/official_prices.json
EXTRACTION_PROMPT_FILE=config/extraction_prompt.txt

FRONTEND_JSON_PATH=public/data/providers.json
REVIEW_CSV_PATH=exports/review_prices.csv
SNAPSHOTS_DIR=snapshots
LOG_DIR=logs

HTTP_TIMEOUT_SECONDS=15
HTTP_MAX_RETRIES=3
PLAYWRIGHT_TIMEOUT_SECONDS=30

RDAP_TIMEOUT_SECONDS=10
```

`app/settings.py` — `pydantic-settings.BaseSettings`, читает `.env`, валидирует пути (создаёт директории `data/`, `snapshots/`, `exports/`, `logs/` при первом запуске, если их нет).

### `config/sources.json` — как в ТЗ, три обязательных источника + место для 3 дополнительных (изначально `enabled: false`, включаются на день 4-5 при наличии времени).

### `config/extraction_prompt.txt` — системный промпт (см. §6.2).

---

## 3. Модель данных

### `app/models.py` (SQLAlchemy 2.0, declarative)

```python
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    website_url: Mapped[str] = mapped_column(String(1024))
    pricing_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    docs_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    site_alive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    https_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    domain_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    domain_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trust_status: Mapped[str] = mapped_column(String(16), default="yellow")  # green|yellow|red
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sources: Mapped[list["ProviderSource"]] = relationship(back_populates="provider")
    prices: Mapped[list["ProviderPrice"]] = relationship(back_populates="provider")

class ProviderSource(Base):
    __tablename__ = "provider_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    catalog_source: Mapped[str] = mapped_column(String(64))       # apirank|aiapipk|veridrop|...
    catalog_page_url: Mapped[str] = mapped_column(String(1024))
    catalog_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    catalog_reviews_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    provider: Mapped["Provider"] = relationship(back_populates="sources")

class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    source_url: Mapped[str] = mapped_column(String(1024))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)   # sha256 hex
    snapshot_path: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ProviderPrice(Base):
    __tablename__ = "provider_prices"
    __table_args__ = (UniqueConstraint("provider_id", "canonical_model_id", "source_url", name="uq_price_identity"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    canonical_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_model_name: Mapped[str] = mapped_column(String(255))
    raw_price_text: Mapped[str] = mapped_column(Text)
    raw_currency: Mapped[str] = mapped_column(String(8))
    raw_unit: Mapped[str] = mapped_column(String(32))
    input_price_usd_per_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_price_usd_per_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1024))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    provider: Mapped["Provider"] = relationship(back_populates="prices")

class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_price_id: Mapped[int] = mapped_column(ForeignKey("provider_prices.id"))
    old_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_url: Mapped[str] = mapped_column(String(1024))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

`review_reason` — enum-строка из фиксированного набора (см. §7). `app/db.py` создаёт `engine`/`SessionLocal` из `DATABASE_URL`, `init_db()` вызывает `Base.metadata.create_all`.

---

## 4. Source adapters

### `app/sources/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class DiscoveredProvider:
    provider_name: str
    domain: str
    website_url: str
    catalog_source: str
    catalog_page_url: str
    catalog_rating: float | None = None
    catalog_reviews_count: int | None = None

class SourceAdapter(ABC):
    source_id: str

    @abstractmethod
    def crawl(self) -> list[DiscoveredProvider]:
        """Скачивает каталог, проходит пагинацию, возвращает валидные записи."""
```

### Конкретные адаптеры
- `apirank.py`: `httpx.get` → `BeautifulSoup` парсинг карточек `/providers/`; если контент рендерится JS (проверяется по пустоте `<body>` после первого запроса) — fallback на Playwright. Пагинация — по `?page=` или "Load more" (проверить вживую на день 1, зафиксировать селекторы).
- `aiapipk.py`: аналогично, отдельные CSS-селекторы под структуру сайта.
- `veridrop.py`: `/relays/certified` — отметка `listed_on_veridrop=True` для найденных доменов.
- Общий helper `sources/dom_utils.py` (не обязателен отдельным файлом, можно в `base.py`): извлечение `provider_name`, `domain` (через `tldextract`), `website_url` из `<a>`/карточки; пустые карточки (нет имени или URL) отбрасываются.
- **AI fallback** (используется только если DOM-парсинг возвращает 0 карточек за 2 попытки): один вызов `extractor.extract_provider_card(text) -> {provider_name, domain, website_url}` на карточку/таблицу с урезанной JSON Schema. Управляется флагом `--allow-ai-fallback` в `crawl-sources`, по умолчанию выключен, включаем только если сайт поменял вёрстку.

### `services/provider_discovery.py`
- `crawl_enabled_sources() -> list[DiscoveredProvider]` — вызывает адаптеры для `enabled: true` записей `sources.json`, ловит исключения по-адаптерно (не роняет весь `crawl-sources`).
- `normalize_and_deduplicate(rows) -> list[Provider]`:
  1. `domain = tldextract.extract(url).registered_domain.lower()`, убрать `www.`.
  2. `httpx.head(url, follow_redirects=True, max_redirects=2)` → взять итоговый `domain` (кэшировать по исходному домену, чтобы не дублировать сетевые вызовы).
  3. Группировка по итоговому домену → один `Provider`, несколько `ProviderSource`.
  4. Upsert в БД (по `domain` unique).

---

## 5. Поиск pricing-страницы и загрузка

### `crawler/fetcher.py`
```python
def fetch(url: str) -> FetchResult:  # FetchResult: html, http_status, final_url, via: "httpx"|"playwright"
```
Логика: `httpx.get` → если `len(text.strip()) < MIN_CONTENT_LEN` (например 200 символов) или статус не 200 → Playwright (`page.goto`, `wait_until="networkidle"`, таймаут из `.env`). Единый `tenacity.retry` декоратор с 3 попытками для `httpx`-пути.

### `crawler/page_finder.py`
```python
CANDIDATE_KEYWORDS = ["pricing", "prices", "models", "billing", "docs", "api", "价格", "计费", "模型"]
CANDIDATE_PATHS = ["/pricing", "/prices", "/models", "/docs", "/api", "/billing"]

def find_pricing_pages(website_url: str) -> list[str]:
    # 1. fetch homepage, собрать все <a href> с текстом/URL
    # 2. score по совпадению ключевых слов в anchor text ИЛИ path
    # 3. если 0 совпадений — попробовать CANDIDATE_PATHS напрямую (HEAD/GET, ждать 200)
    # 4. если совпадений > 3 и они неоднозначны (общий score близкий) — передать
    #    список {anchor_text, url} в ai/extractor.rank_pricing_links() для AI-ранжирования
    #    (AI выбирает ТОЛЬКО из переданных URL, не придумывает новые)
    # 5. вернуть top-3, отфильтрованные по домену провайдера и HTTP 200
```

### `crawler/cleaner.py`
- Удаляет `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>` (кроме случаев, когда в них таблица цен — эвристика: если тег содержит `<table>` или `$`/`¥`/`%`, не удалять).
- Извлекает заголовки, таблицы (`<table>` → Markdown-таблица через `markdownify` или ручной конвертер), списки, параграфы со строками, содержащими цифры+валюта/токен-юниты (`\$|¥|USD|CNY|per|1M|1K|tokens`).
- Возвращает `CleanedPage(text: str, language: str, http_status: int, fetched_at: datetime)`. Язык — `langdetect` или простая эвристика (доля CJK-символов).
- `sha256(text.encode()).hexdigest()` → `content_hash`.
- Сохраняет `snapshots/{provider_id}_{content_hash[:12]}.txt` с шапкой: `URL: ...\nFetched: ...\nStatus: ...\nLanguage: ...\n---\n{text}`.

---

## 6. AI-экстрактор

### 6.1 `ai/schemas.py` — Pydantic-модели ответа AI (используются и как JSON Schema для `output_config.format`, и для валидации)

```python
from pydantic import BaseModel, Field

class RawPriceEntry(BaseModel):
    source_model_name: str
    input_price: float | None = None
    output_price: float | None = None
    currency: str
    unit: str                       # "1K_tokens" | "1M_tokens" | "request" | ...
    price_multiplier: float | None = None
    raw_price_text: str
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False
    review_reason: str | None = None

class AiExtractionResult(BaseModel):
    source_url: str
    page_language: str | None = None
    prices: list[RawPriceEntry] = []
```

### 6.2 `config/extraction_prompt.txt`
Содержимое — как в ТЗ (§5, шаг 5), без изменений:
```
Извлеки только цены AI API из переданного текста.
Не используй знания из памяти и не угадывай отсутствующие значения.
Для каждой цены сохрани точный фрагмент страницы в raw_price_text.
Разделяй input и output price.
Не пересчитывай валюту и единицы.
Если значение неоднозначно, установи needs_review=true.
Верни только JSON по переданной JSON Schema.
```

### 6.3 `ai/client.py` — обёртка

```python
import anthropic

class AiClient:
    def __init__(self, settings):
        self._client = anthropic.Anthropic(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url or None,
            timeout=settings.ai_timeout_seconds,
            max_retries=0,  # ретраи делаем сами на уровне extractor (нужно логировать причину)
        )
        self._model = settings.ai_model

    def extract(self, system_prompt: str, source_url: str, page_text: str, schema: dict) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{
                "role": "user",
                "content": f"source_url: {source_url}\n\n{page_text}",
            }],
        )
        return next(b.text for b in response.content if b.type == "text")
```

### 6.4 `ai/extractor.py`

```python
def extract_prices_with_ai(snapshot: CleanedPage, source_url: str) -> AiExtractionResult:
    schema = AiExtractionResult.model_json_schema()
    for attempt in range(settings.ai_max_retries + 1):
        try:
            raw = ai_client.extract(SYSTEM_PROMPT, source_url, snapshot.text, schema)
            result = AiExtractionResult.model_validate_json(raw)
            log_ai_call(provider_id=..., source_url=source_url, attempt=attempt)  # без ключа/заголовков
            return result
        except (ValidationError, json.JSONDecodeError) as e:
            last_error = e
    raise AiExtractionError("invalid_json", last_error)
```
- Таймаут и число попыток — из `.env` (`AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`).
- Логи: `timestamp, pipeline_step="extract_prices", provider_id, source_url, error_type, error_message` — без API-ключа и заголовков (см. §11).
- `rank_pricing_links(candidates: list[dict]) -> str` — отдельный узкий вызов для §5, тоже через `output_config.format` с простой schema `{"chosen_url": "string"}`, с обязательной проверкой code'ом, что `chosen_url` есть в `candidates`.

---

## 7. Валидация и нормализация (обычный код)

### `services/price_extraction.py` — `validate_ai_result`
Проверки в порядке (первая сработавшая причина → `needs_review=True`, `review_reason=...`):
1. Схема невалидна → `invalid_json` (уже отловлено на уровне `extractor`, здесь — доп. проверка полноты полей).
2. `result.source_url != snapshot.source_url` → `price_not_found` (аномалия, лог + review).
3. Для каждой цены: `raw_price_text not in snapshot.text` (нормализованное сравнение — убрать пробелы/переносы) → `unclear_price_unit`... нет, точнее — отдельная причина `price_not_found` (не подтверждено в snapshot).
4. `input_price is not None and input_price <= 0` или не число → отбросить запись (не публиковать, не в review — просто мусор), залогировать.
5. `currency`/`unit` не входят в допустимые множества (`{"USD","CNY","EUR",...}` / `{"1K_tokens","1M_tokens","request","image",...}`) → `unclear_price_unit`.
6. `confidence < settings.ai_min_confidence` → `low_confidence`.
7. Модель не находится в `model_aliases.json` (после lower/normalize) → `unknown_model` (обрабатывается на шаге нормализации модели, но флаг проставляется здесь же).
8. Если для одной модели у одного провайдера на одной странице две цены сильно расходятся (>2x) без явного объяснения (разные tier) → `conflicting_prices`.
9. Признаки логина/paywall в тексте snapshot (`"sign in to see pricing"`, `"contact sales"` без цифр) → `login_required` (проверяется до вызова AI, на этапе `cleaner`, чтобы не тратить AI-вызов).

Фиксированный список причин ревью — `Literal["price_not_found","unknown_model","unclear_price_unit","unclear_multiplier","conflicting_prices","login_required","low_confidence","invalid_json"]`.

### `services/normalization.py`
```python
def normalize_model(source_model_name: str, aliases: dict[str, str]) -> str | None:
    key = source_model_name.strip().lower().replace(" ", "-")
    return aliases.get(key)  # None => unknown_model

def normalize_price(entry: RawPriceEntry, fx_rates: dict[str, float]) -> NormalizedPrice:
    # 1K -> 1M: множитель 1000
    # currency -> USD по сохранённому курсу (fx_rates хранит {"CNY": 0.14, ...}, дата курса в отдельном поле)
    # price_multiplier (0.3x, 5折=0.5x) применяется к official baseline на шаге сравнения (§8), не здесь
```
Курсы валют: простой статический словарь в `config/fx_rates.json` (обновляется вручную/раз в неделю на MVP — не в скоупе 5 дней делать live-конвертацию через внешний API, но зафиксировать `updated_at` и `source` для прозрачности).

### `services/exporter.py` → `export_review_csv()`
Колонки: `provider_name, domain, source_model_name, canonical_model_id, raw_price_text, raw_currency, raw_unit, confidence, review_reason, source_url, last_checked_at`.

---

## 8. Сравнение с official_prices.json

`services/normalization.py` (или отдельный `official_compare.py`):
```python
def compare_with_official(canonical_model_id, input_usd, output_usd, official: dict) -> ComparisonResult:
    baseline = official.get(canonical_model_id)
    if baseline is None:
        return ComparisonResult(is_cheaper_than_official=False, ...)  # нет базы -> не публикуем
    input_discount = round((1 - input_usd / baseline["input_usd_per_1m"]) * 100, 1)
    output_discount = round((1 - output_usd / baseline["output_usd_per_1m"]) * 100, 1)
    is_cheaper = input_usd < baseline["input_usd_per_1m"] and output_usd < baseline["output_usd_per_1m"]
    return ComparisonResult(is_cheaper, input_discount, output_discount)
```
`config/official_prices.json` — заполняется вручную на день 3, минимум 5 моделей (`openai/gpt-4o`, `anthropic/claude-3-5-sonnet`, `google/gemini-2-5-flash`, `deepseek/deepseek-v3` — по ТЗ) со ссылками на официальные страницы и `updated_at`.

---

## 9. Проверка провайдера (trust)

`services/trust_check.py`:
```python
def update_trust_signals(provider: Provider):
    site_alive, https_ok, status = check_site(provider.website_url)      # httpx HEAD/GET, https_ok = scheme=="https" and no cert error
    domain_age_days = lookup_domain_age(provider.domain)                  # RDAP (python-whois или rdap через httpx к rdap.org), fallback -> "unknown" (None), не роняем pipeline
    listed = {s.catalog_source for s in provider.sources}
    pricing_found = provider.pricing_url is not None

    if site_alive and pricing_found and len(listed) >= 2:
        status = "green"
    elif site_alive and pricing_found:
        status = "yellow"
    else:
        status = "red"
    ...
```
RDAP: сначала запрос к `https://rdap.org/domain/{domain}`, при ошибке/таймауте — `unknown`, пайплайн продолжается (не блокирующая ошибка).

---

## 10. Публикация

### `services/exporter.py` → `export_frontend_json_atomically`
```python
def export_frontend_json_atomically(rows: list[PublicRow]):
    tmp_path = f"{settings.frontend_json_path}.tmp"
    payload = [row.model_dump(mode="json") for row in rows]
    validate_against_schema(payload, FRONTEND_JSON_SCHEMA)   # jsonschema.validate
    with open(tmp_path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.chmod(tmp_path, 0o644)
    os.replace(tmp_path, settings.frontend_json_path)         # атомарно на одной ФС
```
`services/frontend_schema.py` — JSON Schema, зеркалящая пример из ТЗ §12 (обязательные поля: `provider_name, provider_domain, provider_url, model_name, canonical_model_id, input_price_usd_per_1m, output_price_usd_per_1m, trust_status, source_url, last_checked_at`).

### `services/price_extraction.py` → `select_publishable_prices()`
Реализует правило публикации из ТЗ §11 буквально (все условия через `and`), с явным списком проверок в коде (не одной строкой), чтобы легко логировать, какое условие не выполнено — это упрощает отладку review-потока.

---

## 11. Оркестрация и CLI

### `app/cli.py` (Typer)
```python
app = typer.Typer()

@app.command("init-db")
def init_db(): ...

@app.command("crawl-sources")
def crawl_sources(): ...

@app.command("update-all")
def update_all():
    summary = run_update_all()
    print_summary(summary)   # sources_processed, providers_found, providers_unique,
                              # pricing_pages_found, prices_extracted, prices_published,
                              # records_needing_review, errors_count, duration_seconds
    if summary.hard_failure:
        raise typer.Exit(code=1)
```

`app/orchestrator.py` (новый файл, не был явно назван в ТЗ, но нужен для §5.9):
```python
def run_update_all() -> RunSummary:
    started = time.monotonic()
    summary = RunSummary()
    try:
        source_rows = crawl_enabled_sources()
        providers = normalize_and_deduplicate(source_rows)
    except (ConfigError, DbError) as e:
        log_fatal(e); raise  # -> exit code 1, providers.json не трогаем

    for provider in providers:
        try:
            pricing_urls = find_pricing_pages(provider.website_url)
            for url in pricing_urls:
                snapshot = fetch_and_clean(url)
                if snapshot.content_hash == get_previous_hash(provider.id, url):
                    continue
                ai_result = extract_prices_with_ai(snapshot, url)
                validated = validate_ai_result(ai_result, snapshot)
                normalized = normalize_models_and_prices(validated)
                save_prices(provider, normalized)
            update_trust_signals(provider)
        except ProviderError as error:
            log_provider_error(provider, error)
            summary.errors_count += 1

    public_rows = select_publishable_prices()
    try:
        export_frontend_json_atomically(public_rows)
    except (SchemaValidationError, OSError) as e:
        log_fatal(e); summary.hard_failure = True  # предыдущий JSON не трогаем
    export_review_csv()
    summary.duration_seconds = time.monotonic() - started
    return summary
```
Это прямая реализация примера из ТЗ §5.9, но с явными try/except границами, соответствующими §5.8 (жёсткий отказ только для: БД, конфиг, финальная schema-валидация, невозможность записи frontend JSON).

### Логирование (`app/logging_setup.py`)
JSON-lines в `logs/app.log` + `logs/cron.log` (через cron-редирект). Поля: `timestamp, pipeline_step, provider_id, source_url, error_type, error_message`. Явный фильтр, не допускающий попадания `AI_API_KEY`/`Authorization`/полного содержимого `.env` в лог (unit-тест на это, см. §14).

---

## 12. Развёртывание

Точно по ТЗ §5.3, §5.7. Дополнительно:
- `deploy/README_DEPLOY.md` (или раздел в основном `README.md`) с точными командами копипастой для VPS `145.63.129.235`.
- Cron-строка как в ТЗ, plus health-check: раз в неделю проверять `exports/review_prices.csv` mtime — если старше 26 часов, значит `update-all` не отрабатывает (ручной мониторинг на MVP, без алертинга — не в скоупе 5 дней).

---

## 13. План по дням (детализация)

### День 1 — Сбор провайдеров
1. Инициализация репозитория: структура каталогов, `requirements.txt`, `.env.example`, `pyproject.toml` (ruff).
2. `app/settings.py`, `app/db.py`, `app/models.py`, `init-db`.
3. `config/sources.json` с тремя источниками.
4. Живой осмотр APIRank/AIAPIPK/Veridrop → зафиксировать реальные CSS-селекторы/структуру пагинации (это может изменить оценку времени — риск, см. §15).
5. `sources/base.py` + три адаптера + `provider_discovery.py`.
6. `crawl-sources` CLI, ручной прогон, проверка: в БД нет дублей по домену.
7. Юнит-тесты на нормализацию домена и дедупликацию (`tests/test_sources.py`).

**DoD:** `python -m app.cli crawl-sources` заполняет `provider_sources`/`providers`, ≥20 уникальных провайдеров, 0 дублей по домену.

### День 2 — Поиск страниц и AI-agent
1. `crawler/fetcher.py` (httpx + Playwright fallback), `page_finder.py`, `cleaner.py`.
2. `config/extraction_prompt.txt`, `ai/schemas.py`, `ai/client.py`, `ai/extractor.py`.
3. JSON Schema validation + 2 повторные попытки на невалидный JSON.
4. Snapshots сохраняются в `snapshots/`, hash в БД.
5. Тесты: `test_page_finder.py` (эвристики ключевых слов, кандидаты путей), `test_cleaner.py` (на фикстурах HTML), мок AI-ответа для `test_ai_validation.py` (без реального API-вызова в CI).

**DoD:** для ≥10 провайдеров найден `pricing_url`, AI возвращает сырой JSON с `source_url`/`raw_price_text` по ≥1 модели.

### День 3 — Проверка и нормализация
1. `config/model_aliases.json` (минимум 15-20 популярных моделей).
2. `services/price_extraction.py::validate_ai_result` — все 8 причин ревью.
3. `services/normalization.py` — модели, валюты, token units, `config/fx_rates.json`.
4. `config/official_prices.json` — 4-5 моделей вручную.
5. `official_compare.py`.
6. `exporter.export_review_csv()`.
7. Тесты: `test_normalization.py`, кейсы `0.3x`, `1K→1M`, CNY→USD.

**DoD:** валидные цены имеют `input_price_usd_per_1m`/`output_price_usd_per_1m`; сомнительные — в `review_prices.csv` с причиной.

### День 4 — Проверка провайдеров и export
1. `services/trust_check.py` (site/HTTPS/RDAP, статус green/yellow/red).
2. `services/price_extraction.py::select_publishable_prices()` (правило публикации §11 ТЗ).
3. `services/frontend_schema.py` + `exporter.export_frontend_json_atomically()`.
4. Полный `app/orchestrator.py::run_update_all()`, `update-all` CLI с итоговой сводкой.
5. Тесты: `test_trust_check.py` (мок RDAP), `test_exporter.py` (атомарность, поведение при невалидном payload — старый файл не тронут).

**DoD:** `providers.json` проходит schema-валидацию, содержит только записи дешевле official baseline с `confidence>=0.80` и `needs_review=false`.

### День 5 — Вёрстка, сервер, приёмка
1. Подключение готовой вёрстки к `public/data/providers.json` (нужен доступ к репозиторию вёрстки — см. открытый вопрос §15).
2. Проверка фильтров/сортировки на реальных данных, desktop/mobile smoke-test.
3. Деплой на VPS `145.63.129.235` по `deploy/README_DEPLOY.md`.
4. `crontab` с `flock`.
5. Полный прогон `update-all` на проде, сверка с 15 приёмочными пунктами ТЗ §9.
6. `README.md`: команды запуска, структура `.env`, троттлинг, что делать при ошибках.

**DoD:** сайт показывает реальные данные; cron установлен и однократно проверен вручную (`run-parts`-подобный тест или временный `* * * * *` на 2 минуты для проверки, затем возврат на `15 3 * * *`).

---

## 14. Тестирование (сквозной чеклист)

- [ ] Дедупликация по домену (redirect chain до 2 хопов).
- [ ] `page_finder`: ключевые слова + fallback пути + AI-ранжирование только из переданного списка.
- [ ] `cleaner`: таблицы/абзацы с ценами не выбрасываются при очистке.
- [ ] `content_hash` не меняется при повторном фетче неизменной страницы → AI не вызывается повторно (мок счётчика вызовов AI).
- [ ] Невалидный AI JSON → 2 ретрая → запись причины → переход к следующему провайдеру (не падает весь `update-all`).
- [ ] `raw_price_text` действительно найден в snapshot (позитив/негатив кейсы).
- [ ] 1K→1M, CNY→USD, `0.3x` от official baseline — арифметика.
- [ ] Неизвестная модель → `needs_review=True`, не публикуется.
- [ ] `confidence < 0.80` → не публикуется.
- [ ] `select_publishable_prices()` — только цены `is_cheaper_than_official=True`.
- [ ] Атомарная запись `providers.json`: симулировать сбой валидации → старый файл не изменён.
- [ ] Ошибка одного провайдера (сеть недоступна) не останавливает цикл по остальным.
- [ ] В логах нет `AI_API_KEY`/`Authorization`/полного `.env` (grep-тест по `logs/*.log` после тестового прогона).
- [ ] `update-all` печатает все 9 полей сводки.

---

## 15. Открытые вопросы к заказчику / риски

1. **Доступ к репозиторию вёрстки** — не описан в ТЗ явно (готовая вёрстка — отдельный проект на VPS в `/var/www/bestaiprice`?). Нужен доступ на день 5, иначе День 5 сдвигается.
2. **AI API ключ и провайдер** — ТЗ намеренно оставляет выбор через `.env` (`AI_BASE_URL`/`AI_MODEL`). Нужно решить до дня 2: чей ключ используется (заказчика или разработчика на этапе разработки) и какая модель — влияет на бюджет и качество извлечения многоязычных таблиц.
3. **Реальная структура APIRank/AIAPIPK/Veridrop** может измениться/не поддаваться простому DOM-парсингу (антибот, капча, SPA с виртуальным скроллом) — это главный риск Дня 1, который может съесть буфер времени. Рекомендация: потратить первые 1-2 часа Дня 1 на разведку вручную (curl/Playwright inspect), прежде чем писать адаптеры.
4. **Курсы валют** — в ТЗ не указан источник; в этом плане — статический `fx_rates.json`, обновляемый вручную. Если нужен live-курс, это отдельная небольшая задача (не в 5-дневном скоупе, но дешёво добавить один HTTP-вызов к бесплатному FX API).
5. **RDAP/WHOIS rate-limits** — на 20+ доменов в сутки не критично, но при расширении списка источников может потребоваться кэширование `domain_age_days` (не пересчитывать чаще раза в неделю).

---

## 16. Как проверить план end-to-end (после реализации)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env   # заполнить AI_API_KEY

python -m app.cli init-db
python -m app.cli crawl-sources
python -m app.cli update-all
cat public/data/providers.json | python -m json.tool | head -50
cat exports/review_prices.csv
pytest -q
```
Сверить вывод `update-all` и содержимое `providers.json`/`review_prices.csv` с 15 пунктами приёмки в ТЗ §9.
