# ТЗ для разработчика

# AI-парсер цен AI API-провайдеров для BestAIPrice

Срок выполнения: 5 рабочих дней. Вёрстка готова; разработчик подключает к ней реальные данные.

## 1. Результат работы

Система должна автоматически:

1. собрать список AI API-провайдеров из заданных каталогов;
2. перейти на сайт каждого найденного провайдера;
3. найти публичную страницу с моделями и ценами;
4. передать очищенный текст страницы AI-модели;
5. получить модели и цены в строгом JSON;
6. проверить и нормализовать данные обычным кодом;
7. сравнить цены с официальными ценами производителей;
8. проверить базовые признаки провайдера;
9. передать подходящие записи в готовую вёрстку;
10. повторять обновление автоматически один раз в сутки.

Итоговый пользовательский файл:

```text
public/data/providers.json
```

Спорные и ошибочные записи:

```text
exports/review_prices.csv
```

## 2. Где работает система

Парсер размещается на VPS `145.63.129.235` рядом с backend/сайтом и запускается отдельной командой. Отдельный сервер для AI-agent не нужен.

```text
/opt/bestai-parser/
  app/                  код парсера
  config/               источники, prompt, модели и official prices
  data/                 SQLite
  snapshots/            сохранённый текст страниц
  exports/              CSV для проверки
  logs/                 ошибки запусков
  public/data/          JSON для вёрстки
  .env                  ключ AI API и настройки
```

Почему так: для MVP один VPS быстрее развернуть и проще поддерживать. AI-agent является модулем parser-кода и обращается к внешнему AI API по ключу.

## 3. Общая схема

```text
каталоги провайдеров
        ↓
сбор названий, доменов и ссылок
        ↓
объединение дублей по домену
        ↓
поиск pricing/docs страницы провайдера
        ↓
скачивание и очистка страницы
        ↓
AI извлекает модели и сырые цены в JSON
        ↓
обычный код проверяет и нормализует JSON
        ↓
сравнение с official_prices.json
        ↓
проверка сайта, HTTPS и возраста домена
        ↓
providers.json + review_prices.csv
        ↓
готовая вёрстка BestAIPrice
```

Принцип разделения:

```text
обычный код отвечает за ссылки, загрузку, дедупликацию, математику и публикацию
AI отвечает только за понимание нестандартного текста и таблиц с ценами
```

Почему: AI удобно понимает разные форматы страниц и китайский текст, но ему нельзя доверять расчёты и решение о публикации.

## 4. Стартовые источники

Разработчик создаёт `config/sources.json`. Заказчик не передаёт файл со списком провайдеров: список собирает сам парсер.

Обязательные источники первого запуска:

| Источник | Прямая ссылка | Что брать |
|---|---|---|
| APIRank | https://apirank.vip/providers/ | название, домен, URL провайдера, рейтинг/метрики при наличии |
| AIAPIPK | https://www.aiapipk.com/ | название, домен, URL, указанные модели/коэффициенты |
| Veridrop Certified | https://veridrop.org/relays/certified | название, домен, URL, признак присутствия в certified list |

Дополнительные источники для сверки и расширения списка:

| Источник | Прямая ссылка |
|---|---|
| AI API Prices | https://aiapiprices.com/ |
| Inferras | https://www.inferras.org/compare/ai-api-pricing |
| Developers Digest | https://www.developersdigest.tech/tools/ai-api-pricing |

Пример `config/sources.json`:

```json
[
  {"id": "apirank", "url": "https://apirank.vip/providers/", "enabled": true},
  {"id": "aiapipk", "url": "https://www.aiapipk.com/", "enabled": true},
  {"id": "veridrop", "url": "https://veridrop.org/relays/certified", "enabled": true}
]
```

## 5. Как поднять parser с нуля

### 5.1. Зафиксированный стек

Чтобы не тратить время на выбор технологий, MVP реализовать на Python:

```text
Python 3.11+
httpx                 обычные HTTP-запросы
BeautifulSoup/lxml    извлечение ссылок и очистка HTML
Playwright Chromium   страницы, загружаемые JavaScript
Pydantic              проверка AI JSON
SQLAlchemy + SQLite   хранение данных
Typer/Click            команды parser CLI
AI SDK                вызов модели со Structured Output
```

Минимальный `requirements.txt`:

```text
httpx
beautifulsoup4
lxml
playwright
pydantic
pydantic-settings
sqlalchemy
typer
tenacity
tldextract
python-dateutil
```

К этому списку добавляется официальный SDK выбранного AI API.

Почему Python: для него есть готовые библиотеки для HTTP, браузера, HTML, AI API и SQLite; весь MVP остаётся одним приложением без отдельных сервисов.

### 5.2. Структура кода

Разработчик создаёт следующую структуру:

```text
app/
  cli.py                       команды init-db, crawl-sources, update-all
  settings.py                  чтение .env
  db.py                        подключение SQLite
  models.py                    таблицы БД
  sources/
    base.py                    общий интерфейс source-adapter
    apirank.py                 adapter APIRank
    aiapipk.py                 adapter AIAPIPK
    veridrop.py                adapter Veridrop
  crawler/
    fetcher.py                 HTTP + Playwright fallback
    page_finder.py             поиск pricing/docs ссылок
    cleaner.py                 HTML → чистый Markdown/text
  ai/
    extractor.py               вызов AI API
    schemas.py                 Pydantic/JSON Schema ответа
  services/
    provider_discovery.py      сбор и дедупликация провайдеров
    price_extraction.py        обработка pricing pages
    normalization.py           модели, валюты и token units
    trust_check.py             сайт, HTTPS, RDAP/WHOIS
    exporter.py                providers.json и review CSV
config/
  sources.json
  extraction_prompt.txt
  model_aliases.json
  official_prices.json
data/
snapshots/
exports/
logs/
tests/fixtures/
.env.example
requirements.txt
README.md
```

Почему разделено так: source-adapters меняются независимо от AI extractor; расчёты и публикация отделены от недетерминированного ответа AI.

### 5.3. Установка на VPS

Целевая система: Ubuntu на VPS `145.63.129.235`.

Последовательность развёртывания:

```bash
sudo mkdir -p /opt/bestai-parser
sudo chown -R $USER:$USER /opt/bestai-parser
cd /opt/bestai-parser

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env
```

После этого заполнить в `.env` AI API key, AI model и реальный путь к JSON, который читает готовая вёрстка.

Почему Playwright устанавливается на сервере: часть pricing-страниц отдаёт цены только после выполнения JavaScript. Обычные страницы всё равно загружаются через `httpx`.

### 5.4. Первый запуск

CLI должен поддерживать команды:

```bash
.venv/bin/python -m app.cli init-db
.venv/bin/python -m app.cli crawl-sources
.venv/bin/python -m app.cli update-all
```

Ожидаемая последовательность:

```text
init-db       создаёт SQLite и таблицы
crawl-sources собирает провайдеров из трёх каталогов
update-all    выполняет весь pipeline и создаёт frontend JSON
```

Команда должна печатать итог:

```text
sources_processed
providers_found
providers_unique
pricing_pages_found
prices_extracted
prices_published
records_needing_review
errors_count
duration_seconds
```

Почему нужна одна итоговая сводка: по ней разработчик и заказчик сразу видят, дошёл ли pipeline от каталогов до публикации.

### 5.5. Подключение AI API

`app/ai/extractor.py` создаёт один AI client при запуске. Для каждой изменившейся pricing-страницы он отправляет:

```text
system prompt из config/extraction_prompt.txt
source_url
очищенный текст snapshot
JSON Schema из app/ai/schemas.py
```

AI client должен иметь:

```text
timeout 60 секунд
не более двух повторных попыток
Structured Output/JSON Schema
логирование provider_id и source_url без записи AI API key
```

AI API key существует только в `.env` на сервере. Frontend никогда не вызывает AI API.

### 5.6. Подключение к готовой вёрстке

`FRONTEND_JSON_PATH` в `.env` указывает на фактический каталог статических файлов сайта, например:

```dotenv
FRONTEND_JSON_PATH=/var/www/bestaiprice/public/data/providers.json
```

Exporter выполняет:

1. создаёт `providers.json.tmp`;
2. валидирует временный файл по schema;
3. выставляет права на чтение web-server;
4. атомарно переименовывает временный файл в `providers.json`;
5. при ошибке не трогает предыдущий файл.

Почему: посетитель сайта не должен получить частично записанный или пустой JSON во время обновления.

### 5.7. Ежедневный запуск

После успешного ручного запуска разработчик добавляет cron с блокировкой повторного параллельного запуска:

```cron
15 3 * * * cd /opt/bestai-parser && flock -n /tmp/bestai-parser.lock .venv/bin/python -m app.cli update-all >> logs/cron.log 2>&1
```

Почему `flock`: если один обход завис или выполняется долго, второй экземпляр не должен одновременно менять БД и JSON.

### 5.8. Поведение при ошибках

Ошибка отдельного сайта записывается в лог и не останавливает остальные сайты. Команда завершается с ошибкой только если:

```text
не открылась БД
не удалось прочитать config
не удалось провалидировать итоговый JSON
невозможно записать frontend JSON
```

В логах для ошибки хранить:

```text
timestamp
pipeline_step
provider_id
source_url
error_type
error_message
```

AI API key, полный `.env` и чувствительные заголовки в лог не записывать.

### 5.9. Главный orchestration-код

`update-all` должен быть одним понятным orchestrator без скрытой логики:

```python
def update_all():
    source_rows = crawl_enabled_sources()
    providers = normalize_and_deduplicate(source_rows)

    for provider in providers:
        try:
            pricing_urls = find_pricing_pages(provider.website_url)
            snapshots = fetch_and_clean(pricing_urls)

            for snapshot in snapshots:
                if snapshot.content_hash == snapshot.previous_hash:
                    continue

                ai_result = extract_prices_with_ai(snapshot)
                validated = validate_ai_result(ai_result, snapshot)
                normalized = normalize_models_and_prices(validated)
                save_prices(provider, normalized)

            update_trust_signals(provider)
        except ProviderError as error:
            log_provider_error(provider, error)

    public_rows = select_publishable_prices()
    export_frontend_json_atomically(public_rows)
    export_review_csv()
```

Почему такой entrypoint: из него сразу видно порядок этапов, а ошибка одного провайдера локализована внутри цикла и не останавливает общий export.

## 6. Пошаговая логика parser pipeline

### Шаг 1. Собрать провайдеров из каталогов

Откуда:

```text
config/sources.json
```

Что делает разработчик:

1. Для каждого обязательного каталога создаёт небольшой source-adapter.
2. Adapter скачивает страницу каталога обычным HTTP-запросом.
3. Если содержимое загружается JavaScript, используется Playwright.
4. Parser извлекает карточки/строки провайдеров и проходит пагинацию, если она есть.
5. Для каждого провайдера сохраняет источник, где он найден.

Поля результата:

```text
provider_name
domain
website_url
catalog_source
catalog_page_url
catalog_rating
catalog_reviews_count
discovered_at
```

Где используется AI:

AI можно применять как fallback, если каталог нельзя стабильно разобрать DOM-селекторами. AI получает очищенный текст одной карточки или таблицы и возвращает `provider_name`, `domain`, `website_url`.

Почему основной сбор делается кодом: структура стартовых каталогов известна, поэтому обычный adapter быстрее, дешевле и стабильнее AI.

Выход шага:

```text
таблица provider_sources заполнена найденными записями
```

Проверка:

- у записи есть `provider_name`;
- `website_url` является валидным HTTP/HTTPS URL;
- сохранён `catalog_page_url`;
- пустые карточки не записываются.

### Шаг 2. Объединить одинаковых провайдеров

Откуда: записи `provider_sources`, полученные на шаге 1.

Что делает код:

1. приводит домен к нижнему регистру;
2. удаляет `www.`, путь, query и завершающий `/`;
3. следует максимум по двум HTTP redirect, чтобы определить конечный домен;
4. объединяет записи с одинаковым конечным доменом;
5. сохраняет все каталоги, где найден провайдер.

Почему: один провайдер может одновременно находиться в APIRank, AIAPIPK и Veridrop. На сайт нужно идти один раз, а наличие в нескольких каталогах использовать как сигнал доверия.

Выход шага:

```text
одна запись providers на один домен
несколько связанных записей provider_sources
```

Проверка: в `providers` нет двух записей с одинаковым нормализованным доменом.

### Шаг 3. Найти страницу цен провайдера

Откуда: `website_url` из таблицы `providers`.

Что делает код:

1. открывает главную страницу;
2. собирает внутренние ссылки;
3. ищет ссылки по словам `pricing`, `prices`, `models`, `billing`, `docs`, `价格`, `计费`, `模型`;
4. если ссылки не найдены, проверяет типовые пути;
5. выбирает до трёх наиболее вероятных страниц для анализа.

Типовые пути:

```text
/pricing
/prices
/models
/docs
/api
/billing
```

Где используется AI: если названия ссылок нестандартные, AI получает список `anchor text + URL` и ранжирует, какие ссылки вероятнее содержат API prices. AI не придумывает новый URL, а выбирает только из переданного списка.

Почему: сначала используется дешёвый и предсказуемый поиск ссылок, AI подключается только для неоднозначных случаев.

Выход шага:

```text
providers.pricing_url
providers.docs_url
```

Проверка: выбранный URL относится к домену провайдера и отвечает HTTP 200.

### Шаг 4. Скачать и подготовить страницу для AI

Откуда: `pricing_url`/`docs_url` шага 3.

Что делает код:

1. скачивает HTML обычным HTTP client;
2. при пустом контенте повторяет через Playwright;
3. удаляет scripts, styles, меню, footer и повторяющиеся блоки;
4. сохраняет заголовки, таблицы, списки и строки с моделями/валютами;
5. преобразует результат в чистый Markdown/text;
6. сохраняет snapshot и SHA-256 `page_content_hash`.

Почему AI не получает весь HTML: чистый текст дешевле обрабатывать, в нём меньше шума и ниже риск пропустить таблицу цен.

Выход шага:

```text
snapshots/{provider_id}.txt
source_snapshots в SQLite
```

Проверка: snapshot содержит URL, дату загрузки, HTTP status, язык и непустой текст.

### Шаг 5. Передать страницу AI-agent

Где находится agent: функция `extractPrices()` внутри backend-парсера. Отдельно устанавливать agent не нужно.

Что передаётся AI:

```text
source_url
очищенный текст страницы
JSON Schema ответа
инструкция config/extraction_prompt.txt
```

Настройки `.env`:

```dotenv
AI_API_KEY=
AI_BASE_URL=
AI_MODEL=
AI_TIMEOUT_SECONDS=60
AI_MAX_RETRIES=2
AI_MIN_CONFIDENCE=0.80
DATABASE_URL=sqlite:///data/bestai.db
SOURCES_FILE=config/sources.json
OFFICIAL_PRICES_FILE=config/official_prices.json
FRONTEND_JSON_PATH=/var/www/bestaiprice/public/data/providers.json
REVIEW_CSV_PATH=exports/review_prices.csv
```

Требование к AI API: модель должна поддерживать Structured Output/JSON Schema. Конкретная модель меняется через `.env` без изменения parser-кода.

Системный prompt:

```text
Извлеки только цены AI API из переданного текста.
Не используй знания из памяти и не угадывай отсутствующие значения.
Для каждой цены сохрани точный фрагмент страницы в raw_price_text.
Разделяй input и output price.
Не пересчитывай валюту и единицы.
Если значение неоднозначно, установи needs_review=true.
Верни только JSON по переданной JSON Schema.
```

Ответ AI:

```json
{
  "source_url": "https://provider.example/pricing",
  "page_language": "en",
  "prices": [
    {
      "source_model_name": "GPT-4o",
      "input_price": 1.25,
      "output_price": 5.0,
      "currency": "USD",
      "unit": "1M_tokens",
      "price_multiplier": null,
      "raw_price_text": "$1.25 input / $5 output per 1M tokens",
      "confidence": 0.94,
      "needs_review": false,
      "review_reason": null
    }
  ]
}
```

Если цена не найдена, AI возвращает:

```json
{"source_url": "https://provider.example/pricing", "prices": []}
```

Почему AI используется здесь: сайты имеют разные таблицы, языки, обозначения `0.3x`, `5折`, `官方倍率`; один prompt позволяет извлекать данные без отдельного XPath для каждого сайта.

Выход шага: сырой AI JSON, который ещё нельзя публиковать.

### Шаг 6. Проверить ответ AI обычным кодом

Что делает код:

1. валидирует JSON по schema;
2. проверяет, что `source_url` совпадает с анализируемой страницей;
3. проверяет, что `raw_price_text` действительно есть в snapshot;
4. отклоняет отрицательные, нулевые и нечисловые цены;
5. проверяет валюту и единицу;
6. помечает неизвестную модель как `needs_review`;
7. не допускает публикацию при `confidence < 0.80`;
8. при невалидном JSON повторяет AI-запрос максимум два раза;
9. после двух ошибок записывает причину и переходит к следующему провайдеру.

Почему: AI может ошибаться, поэтому факт наличия цены на странице и корректность структуры подтверждает код.

Причины ручной проверки:

```text
price_not_found
unknown_model
unclear_price_unit
unclear_multiplier
conflicting_prices
login_required
low_confidence
invalid_json
```

Выход шага: валидные сырые цены или запись для `review_prices.csv`.

### Шаг 7. Нормализовать модель

Откуда: `source_model_name` из подтверждённого AI JSON.

Что делает код: сравнивает название со словарём `config/model_aliases.json`.

```json
{
  "gpt-4o": "openai/gpt-4o",
  "claude-3.5-sonnet": "anthropic/claude-3-5-sonnet",
  "gemini-2.5-flash": "google/gemini-2-5-flash",
  "deepseek-v3": "deepseek/deepseek-v3",
  "qwen-max": "alibaba/qwen-max"
}
```

Почему: у разных провайдеров одна модель может называться по-разному. Для сравнения нужна единая запись `canonical_model_id`.

Выход шага: `canonical_model_id`. Неизвестный alias отправляется на ручную проверку.

### Шаг 8. Нормализовать цену

Целевой формат для текстовых моделей:

```text
USD за 1M input tokens
USD за 1M output tokens
```

Что делает только обычный код:

1. переводит цену за 1K токенов в цену за 1M;
2. конвертирует CNY и другие валюты в USD по сохранённому курсу;
3. рассчитывает цену по коэффициенту `0.3x` от official baseline;
4. сохраняет исходную валюту, единицу и `raw_price_text`;
5. сохраняет дату и источник валютного курса.

Почему расчёт не делает AI: одинаковые формулы должны всегда давать одинаковый проверяемый результат.

Выход шага:

```text
input_price_usd_per_1m
output_price_usd_per_1m
```

Если пересчёт неоднозначен, запись получает `needs_review=true`.

### Шаг 9. Сравнить с официальной ценой

Откуда: ручной файл `config/official_prices.json`.

Официальные источники:

| Производитель | Прямая ссылка |
|---|---|
| OpenAI | https://openai.com/api/pricing/ |
| Anthropic | https://www.anthropic.com/pricing |
| Google Gemini | https://ai.google.dev/gemini-api/docs/pricing |
| DeepSeek | https://api-docs.deepseek.com/quick_start/pricing |

Формат baseline:

```json
{
  "openai/gpt-4o": {
    "input_usd_per_1m": 2.5,
    "output_usd_per_1m": 10.0,
    "source_url": "https://openai.com/api/pricing/",
    "updated_at": "2026-08-03T00:00:00Z"
  }
}
```

Код рассчитывает:

```text
is_cheaper_than_official
input_discount_percent
output_discount_percent
```

Почему baseline хранится вручную: в пятидневном MVP это быстрее и надёжнее отдельного parser для каждого производителя.

### Шаг 10. Проверить провайдера

Откуда: домен провайдера и записи `provider_sources`.

Код проверяет:

```text
site_alive
https_ok
pricing_page_found
domain_created_at
domain_age_days
listed_on_apirank
listed_on_aiapipk
listed_on_veridrop
```

WHOIS/RDAP используется только для даты регистрации домена. Если дата скрыта или недоступна, записывается `unknown`, а pipeline продолжает работу.

Простой статус:

```text
green  = сайт работает, цена найдена, есть внешний каталог
yellow = сайт и цена есть, но внешних сигналов мало
red    = сайт не работает или публичная цена не подтверждена
```

Почему: это прозрачные проверяемые признаки, которые реально собрать за пять дней.

### Шаг 11. Решить, что публиковать

Запись попадает в публичный JSON только при выполнении всех условий:

```text
site_alive = true
pricing_page_found = true
canonical_model_id заполнен
is_cheaper_than_official = true
confidence >= 0.80
needs_review = false
source_url заполнен
raw_price_text подтверждён в snapshot
```

Все остальные записи сохраняются в `review_prices.csv` с конкретной причиной.

Почему: AI не должен напрямую управлять данными сайта; решение принимает код по фиксированным условиям.

### Шаг 12. Передать данные в готовую вёрстку

Parser формирует временный файл, проверяет его по JSON Schema и затем атомарно заменяет:

```text
public/data/providers.json
```

Пример элемента:

```json
{
  "provider_name": "Example API",
  "provider_domain": "example.com",
  "provider_url": "https://example.com",
  "model_name": "GPT-4o",
  "canonical_model_id": "openai/gpt-4o",
  "input_price_usd_per_1m": 1.25,
  "output_price_usd_per_1m": 5.0,
  "official_input_price_usd_per_1m": 2.5,
  "official_output_price_usd_per_1m": 10.0,
  "input_discount_percent": 50,
  "output_discount_percent": 50,
  "trust_status": "green",
  "source_url": "https://example.com/pricing",
  "last_checked_at": "2026-08-03T00:00:00Z"
}
```

Разработчик заменяет mock/static data в готовой вёрстке на чтение этого JSON. Существующий дизайн, компоненты и адаптивность сохраняются.

Почему используется JSON: для готовой вёрстки это самый быстрый способ подключения без разработки отдельного публичного API.

### Шаг 13. Ежедневно обновлять данные

Одна команда запускает полный цикл:

```text
update-all
```

Последовательность команды:

```text
crawl-sources
deduplicate-providers
find-pricing
fetch-pages
extract-prices
normalize-prices
check-providers
export-frontend
export-review
```

Cron запускает `update-all` один раз в сутки.

Если `page_content_hash` не изменился, AI повторно не вызывается. Если новая выгрузка не прошла проверку, сайт продолжает использовать предыдущий рабочий JSON.

Почему: это уменьшает число AI-запросов и защищает интерфейс от пустой/повреждённой выгрузки.

## 7. Минимальная схема SQLite

```sql
providers(
  id, name, domain, website_url, pricing_url, docs_url,
  site_alive, https_ok, domain_created_at, domain_age_days,
  trust_status, last_checked_at
)

provider_sources(
  id, provider_id, catalog_source, catalog_page_url,
  catalog_rating, catalog_reviews_count, discovered_at
)

source_snapshots(
  id, provider_id, source_url, http_status,
  content_hash, snapshot_path, fetched_at
)

provider_prices(
  id, provider_id, canonical_model_id, source_model_name,
  raw_price_text, raw_currency, raw_unit,
  input_price_usd_per_1m, output_price_usd_per_1m,
  confidence, needs_review, review_reason,
  source_url, last_checked_at
)

price_history(
  id, provider_price_id, old_value, new_value,
  source_url, changed_at
)
```

## 8. План реализации на 5 дней

### День 1. Сбор провайдеров

Сделать:

- структуру проекта и SQLite;
- `config/sources.json`;
- adapters APIRank, AIAPIPK и Veridrop;
- `crawl-sources`;
- нормализацию доменов и удаление дублей.

Результат дня: parser сам собрал провайдеров из каталогов, в БД нет дублей по домену.

### День 2. Поиск страниц и AI-agent

Сделать:

- поиск pricing/docs URL;
- HTTP fetch и Playwright fallback;
- очистку HTML и snapshots;
- `.env.example`;
- `config/extraction_prompt.txt`;
- вызов AI API со Structured Output;
- JSON Schema validation и две повторные попытки.

Результат дня: по найденным провайдерам AI возвращает сырые модели и цены с `source_url` и `raw_price_text`.

### День 3. Проверка и нормализация

Сделать:

- `model_aliases.json`;
- проверку AI JSON;
- нормализацию валют и token units;
- `official_prices.json`;
- сравнение с официальными ценами;
- `review_prices.csv`.

Результат дня: валидные цены рассчитаны обычным кодом, сомнительные записи имеют причину проверки.

### День 4. Проверка провайдеров и export

Сделать:

- site/HTTPS check;
- WHOIS/RDAP domain age;
- флаги APIRank/AIAPIPK/Veridrop;
- правила публикации;
- `providers.json` и его JSON Schema;
- атомарное обновление файла.

Результат дня: сформирован проверенный JSON для frontend.

### День 5. Вёрстка, сервер и приёмка

Сделать:

- заменить mock data в готовой вёрстке;
- проверить существующие фильтры и сортировку;
- проверить desktop/mobile;
- развернуть parser на VPS;
- настроить ежедневный cron;
- выполнить полный `update-all`;
- подготовить README с запуском и настройками.

Результат дня: сайт показывает реальные данные, ежедневное обновление работает на сервере.

## 9. Как принять работу

Разработчик демонстрирует на VPS один полный запуск:

```text
update-all
```

Приёмочные проверки:

1. APIRank, AIAPIPK и Veridrop обходятся автоматически.
2. Список провайдеров создан parser-кодом без входного `providers.csv`.
3. Дубли одного домена объединены.
4. Минимум 20 уникальных провайдеров обработаны.
5. Минимум для 10 провайдеров найдены публичные pricing/source страницы.
6. AI получает очищенный текст и возвращает JSON по schema.
7. У опубликованной цены есть `source_url` и подтверждённый `raw_price_text`.
8. Цена за 1K токенов правильно пересчитывается за 1M.
9. Неизвестная модель и непонятная цена попадают в CSV, а не на сайт.
10. Повторный запуск неизменённой страницы не вызывает AI повторно.
11. Ошибка одного провайдера не останавливает весь запуск.
12. `providers.json` проходит schema validation и открывается готовой вёрсткой.
13. В интерфейсе показаны только цены дешевле official baseline.
14. При ошибке обновления предыдущий рабочий JSON остаётся доступен.
15. Cron ежедневного обновления установлен и проверен.

Работа считается завершённой после демонстрации полного pipeline от каталогов до реальных данных в интерфейсе.
