# Implementation Plan: AI Price Parser for BestAIPrice

Based on `bestai_price_parser_tz.md`. This document outlines technical decisions, repository architecture, schemas, and implementation milestones.

---

## 0. Key Technical Architecture

| Dimension | Technical Decision |
|---|---|
| AI SDK | `app/ai/client.py` dispatches on `AI_PROVIDER` to one of three protocols: OpenAI-compatible Chat Completions (`glm`, `gemini`), OpenAI Responses API with mandatory streaming (`codex`), or the official `anthropic` SDK / Messages API (`claude`, default). `AI_BASE_URL`, `AI_PROVIDER` and `AI_MODEL` in `.env` remain fully configurable — no code change needed to switch between the four Jigji-tested model routes. All four force a single-tool call (`extract_prices`) for Structured Output. |
| Default Model | `claude-sonnet-5` via `AI_PROVIDER=claude` — optimal cost/performance ratio for structured extraction across ~20-160 providers/day. Configurable via `.env`; see README for the GLM/Gemini/Codex/Claude routing table. |
| Prompt Caching | `extraction_prompt.txt` + JSON Schema prefix cached using `cache_control: {"type": "ephemeral"}` for cost efficiency. |
| ORM | SQLAlchemy 2.0 (declarative typed) with SQLite database (`data/bestai.db`). |
| HTTP Client | `httpx.Client` with timeouts and fallback to Playwright Chromium headless for JS-rendered pages. |
| Browser Engine | Playwright Chromium (headless) used as fallback for SPA pages or Cloudflare/bot challenges. |
| CLI Framework | `Typer` CLI supporting `init-db`, `crawl-sources`, and `update-all`. |
| Testing | `pytest` unit test suite covering adapters, normalizers, trust signals, and exporters. |

---

## 1. Repository Structure

```text
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
      dom_utils.py
    crawler/
      __init__.py
      fetcher.py
      page_finder.py
      cleaner.py
    ai/
      __init__.py
      client.py            # Wrapper over Anthropic SDK / AI_BASE_URL
      extractor.py
      schemas.py
    services/
      __init__.py
      provider_discovery.py
      price_extraction.py
      normalization.py
      trust_check.py
      exporter.py
      frontend_schema.py    # JSON Schema for providers.json
  config/
    sources.json
    extraction_prompt.txt
    model_aliases.json
    official_prices.json
  data/                      # SQLite DB (gitignored)
  snapshots/                 # Cleaned HTML page snapshots (gitignored)
  exports/                   # review_prices.csv (gitignored)
  logs/                      # Application logs (gitignored)
  public/data/               # providers.json local export
  tests/
    test_sources.py
    test_cleaner.py
    test_normalization.py
    test_exporter.py
    test_ai_validation.py
  .env.example
  .gitignore
  requirements.txt
  pyproject.toml
  README.md
```

---

## 2. Configuration & Environment (`.env.example`)

```dotenv
AI_API_KEY=
AI_BASE_URL=https://api.anthropic.com
AI_MODEL=claude-sonnet-5
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

---

## 3. Data Models (`app/models.py`)

- `Provider`: id, name, domain (unique), website_url, pricing_url, trust_status (`green`/`yellow`/`red`), last_checked_at.
- `ProviderSource`: provider_id, catalog_source (`apirank`/`aiapipk`/`veridrop`), catalog_page_url, discovered_at.
- `SourceSnapshot`: provider_id, source_url, http_status, content_hash (SHA-256), snapshot_path, fetched_at.
- `ProviderPrice`: provider_id, canonical_model_id, source_model_name, raw_price_text, raw_currency, raw_unit, input_price_usd_per_1m, output_price_usd_per_1m, confidence, needs_review, review_reason, source_url, last_checked_at.
- `PriceHistory`: provider_price_id, old_value, new_value, source_url, changed_at.

---

## 4. Verification & Review Reasons
Review reasons (`review_reason`):
- `login_required`: Pricing hidden behind authentication or paywall.
- `unclear_multiplier`: Multiplier notation ambiguous.
- `conflicting_prices`: Contradictory prices (>2x divergence for same model).
- `price_not_found`: raw_price_text not verifiable in page snapshot.
- `unknown_model`: Model unmapped in `model_aliases.json`.
- `unclear_price_unit`: Currency or token unit missing or unrecognized.
- `low_confidence`: AI confidence rating $< 0.80$.
- `invalid_json`: Response validation failure.

---

## 5. Verification Commands
```bash
python -m app.cli init-db
python -m app.cli crawl-sources
python -m app.cli update-all
pytest -v
```
