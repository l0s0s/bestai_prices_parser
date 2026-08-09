# BestAIPrice AI Price Parser

An automated system for discovering, extracting, normalizing, verifying, and exporting AI API provider pricing data in JSON format for the BestAIPrice platform.

## Output Files
1. **Public Frontend JSON**: `public/data/providers.json` (contains verified price entries cheaper than standard provider baselines with confidence level $\ge 0.80$).
2. **Review CSV**: `exports/review_prices.csv` (contains entries that require manual verification along with the `review_reason`).
3. **Structured Logs**: `logs/app.log` (JSON-lines format without sensitive API key leaks).
4. **Page Snapshots**: `snapshots/` (cleansed Markdown/text snapshots keyed by SHA-256 content hashes).

---

## Prerequisites & Requirements
- Python 3.11+
- Playwright (Chromium headless)
- SQLite3

---

## Quick Start

### 1. Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
```

### 2. Configure Environment (`.env`)
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Set your `AI_API_KEY` and `AI_MODEL` (e.g. `claude-sonnet-5`).

### Supported AI providers

`AI_PROVIDER` selects which HTTP protocol is spoken against `AI_BASE_URL` — switching model family is a `.env` change only, no code changes required:

| `AI_PROVIDER` | Example `AI_MODEL` | Protocol |
|---|---|---|
| `glm` | `glm-4.7` | OpenAI-compatible Chat Completions |
| `gemini` | `gemini-2.5-flash` | OpenAI-compatible Chat Completions |
| `codex` | `gpt-5.6-terra` | OpenAI Responses API (streaming) |
| `claude` (default) | `claude-sonnet-5` / `claude-haiku-4-5-20251001` | Anthropic Messages API |

To route all four through the Jigji multi-model gateway, set `AI_BASE_URL=https://jigji.com` and pick the matching `AI_PROVIDER`/`AI_MODEL` pair (see `.env.example` for ready-to-uncomment examples). Direct Anthropic API access (`AI_BASE_URL=https://api.anthropic.com`, `AI_PROVIDER=claude`) remains the default.

For local development, `FRONTEND_JSON_PATH` defaults to `public/data/providers.json`. On production VPS, set it to the target web root:
```dotenv
FRONTEND_JSON_PATH=/var/www/bestaiprice/public/data/providers.json
```

---

## CLI Usage

The CLI is built with Typer and provides 3 core commands:

### Initialize Database
Creates SQLite database schema (`data/bestai.db`):
```bash
python -m app.cli init-db
```

### Crawl Catalogs (`crawl-sources`)
Crawls external source catalogs (APIRank, AIAPIPK, Veridrop Certified), resolves canonical domain redirect chains, and upserts unique providers to the database:
```bash
python -m app.cli crawl-sources
```

### Full Execution Pipeline (`update-all`)
Executes the end-to-end pipeline: source discovery $\rightarrow$ pricing page location $\rightarrow$ HTML fetch & clean $\rightarrow$ AI structured extraction $\rightarrow$ normalization $\rightarrow$ HTTP/RDAP trust check $\rightarrow$ atomic JSON & CSV export:
```bash
python -m app.cli update-all
```

Example `update-all` summary:
```text
=================== RUN SUMMARY ===================
sources_processed       : 3
providers_found         : 165
providers_unique        : 162
pricing_pages_found     : 98
prices_extracted        : 35
prices_published        : 22
records_needing_review  : 13
errors_count            : 0
duration_seconds        : 45.12s
===================================================

Pipeline completed successfully.
```

---

## Running Tests

Run the full pytest suite:
```bash
pytest -v
```

---

## Production Cron Deployment

To run daily automated updates at 03:15 AM with non-blocking file locking (`flock`):

```cron
15 3 * * * cd /opt/bestai-parser && flock -n /tmp/bestai-parser.lock .venv/bin/python -m app.cli update-all >> logs/cron.log 2>&1
```
