# AI-парсер цен AI API-провайдеров для BestAIPrice

Автоматизированная система сбора, извлечения, нормализации, проверки надежности и экспорта цен AI API провайдеров в формате JSON для готовой вёрстки сайта BestAIPrice.

## Результаты работы
1. **Публичный JSON для фронтенда**: `public/data/providers.json` (содержит только подтвержденные цены дешевле официального базлайна производителей с уровнем доверия $\ge 0.80$).
2. **CSV для ручной проверки**: `exports/review_prices.csv` (содержит записи, не прошедшие автофильтр с указанием причины `review_reason`).
3. **Логи работы**: `logs/app.log` (структурированный JSON-lines лог без утечек API ключей).
4. **Снапшоты страниц**: `snapshots/` (сохраненный очищенный текст страниц с SHA-256 хэшем).

---

## Требования к окружению
- Python 3.11+
- Playwright (Chromium headless)
- SQLite3

---

## Быстрый старт

### 1. Установка зависимостей
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
```

### 2. Конфигурация `.env`
Скопируйте `.env.example` в `.env`:
```bash
cp .env.example .env
```
Заполните ключ `AI_API_KEY` и модель `AI_MODEL` (например `claude-3-5-sonnet-20241022`).
По умолчанию для локальной разработки `FRONTEND_JSON_PATH` установлен в `public/data/providers.json`. На продуктовом VPS установите путь к сайту:
```dotenv
FRONTEND_JSON_PATH=/var/www/bestaiprice/public/data/providers.json
```

---

## Использование CLI

 CLI основан на Typer и поддерживает 3 основные команды:

### Инициализация базы данных
Создаёт таблицы в SQLite (`data/bestai.db`):
```bash
python -m app.cli init-db
```

### Сбор провайдеров из каталогов
Скачивает каталоги (APIRank, AIAPIPK, Veridrop Certified), выполняет резолвинг редиректов домена и сохраняет уникальные записи в БД:
```bash
python -m app.cli crawl-sources
```

### Полный цикл обновления (`update-all`)
Выполняет полный пайплайн: сбор источников $\rightarrow$ поиск страниц цен $\rightarrow$ загрузку и очистку HTML $\rightarrow$ AI-извлечение $\rightarrow$ нормализацию $\rightarrow$ проверку доступности и RDAP $\rightarrow$ атомарный экспорт JSON и CSV:
```bash
python -m app.cli update-all
```

Пример итогового вывода `update-all`:
```text
=================== RUN SUMMARY ===================
sources_processed       : 3
providers_found         : 24
providers_unique        : 18
pricing_pages_found     : 18
prices_extracted        : 35
prices_published        : 22
records_needing_review  : 13
errors_count            : 0
duration_seconds        : 14.52s
===================================================

Pipeline completed successfully.
```

---

## Запуск тестов

Запуск полного пакета юнит-тестов:
```bash
pytest -v
```

---

## Настройка Cron на VPS

Для ежедневного автоматического запуска в 03:15 ночи с защитой от параллельных запусков (`flock`):

```cron
15 3 * * * cd /opt/bestai-parser && flock -n /tmp/bestai-parser.lock .venv/bin/python -m app.cli update-all >> logs/cron.log 2>&1
```
