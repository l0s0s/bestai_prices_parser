# Implementation Audit Report (`bestai_price_parser_tz.md`)

## v8 — Switch to `gpt-5.6-terra`, page-discovery and fetcher fixes, snapshot-authenticity sweep (2026-08-08)

Per request, re-verified `providers.json` and `review_prices.csv` again after switching `.env`'s `AI_MODEL` from the cheap `gpt-5.6-luna` (used for the v7 test run) to `gpt-5.6-terra` (10x the per-token cost, same Codex/Responses-API protocol, no code change needed — confirmed via a live smoke test before committing to the full run), re-ran the TZ readiness checklist, and specifically re-verified that `snapshots/*.txt` are genuinely pricing pages rather than blanks/errors/wrong content, per this round's explicit request.

### 1. Terra run outcome vs. the v7 luna run

First full re-run (fresh DB, same 165 providers, terra model, pre-existing v7 code fixes still in place):

```text
sources_processed       : 3
providers_found         : 166
providers_unique        : 165
pricing_pages_found     : 427
prices_extracted        : 660        (luna: 367)
prices_published        : 39         (luna: 60)
records_needing_review  : 573        (luna: 240)
errors_count            : 0
duration_seconds        : 5960.91s   (~99 min; luna: ~180 min, dominated by luna's empty-result retries)
```

Terra extracted far more raw price entries per page (660 vs 367) and, on spot-check, cited `raw_price_text` far more literally/reliably — re-running the same numeric-vs-raw-text consistency check used in the v7 luna audit (parsing every number out of each published row's `raw_price_text` and confirming the stored `input_price_usd_per_1m`/`output_price_usd_per_1m` appear among them) found **0 mismatches across all 39 published rows**, versus 1 confirmed mismatch class (the `_merge_price_pair` bug, already fixed in code) found on luna. The `conflicting_prices` review reason — which fired 9 times on the luna run's `sunyears.com` extraction — did not fire at all this run.

**`sunyears.com` (17 published rows on luna) dropped to 0 published rows.** Investigated and confirmed as a genuine, correct outcome, not a regression: `curl -I https://sunyears.com/models.html` now returns a live **404** — the provider removed its models/pricing pages from the site in the few hours between the luna run and this run. `find_pricing_pages('https://sunyears.com')` now correctly returns only the site's generic `/products#api` marketing page (which genuinely contains no prices, confirmed by reading the snapshot), and the AI correctly extracted 0 prices from it. Exactly the behavior TZ intends for a provider whose pricing page disappears: no guessing, no stale carry-over, correctly excluded rather than continuing to publish now-unconfirmable prices from an offline page. This is also a real illustration of why TZ mandates daily re-crawling (§13).

### 2. Seventh bug found — weak homepage link starves out the standard-path fallback (`app/crawler/page_finder.py`)

While investigating the `sunyears.com` change above, found a real, independent defect in `find_pricing_pages()`: the standard-path fallback (`/pricing`, `/models`, `/docs`, etc.) only ran when the homepage yielded **zero** scored candidate links. A single weak match — e.g. a nav item whose anchor text only hits the generic `"api"` keyword, like `sunyears.com`'s current homepage-only link "SunYears API Platform" → `/products#api` — was enough to make `verified_urls` non-empty and permanently skip the fallback, even when that one weak match turns out to be a marketing page with no prices and the real pricing page would have been found at a standard path. Confirmed via a live test against `sunyears.com`'s current homepage (exactly one scored candidate, `/products#api`, score 3, from the loose `"api"` keyword match).

**Fixed**: the standard-path probe now always runs (deduplicated against, and additive to, the homepage-scanned candidates), still capped at 3 total URLs, so a single weak or wrong homepage match can no longer suppress it. Added `tests/test_page_finder.py` reproducing the exact scenario with mocked `fetch`/`verify_http_200`. Full suite: **41 passed** at this point (before the fetcher fix below).

### 3. Eighth bug found — the Playwright fallback gate measures the wrong thing (`app/crawler/fetcher.py`)

Directly investigating this round's specific request ("перепроверь что снапшоты это реально страницы с ценной"), swept every snapshot fetched during the terra run for genuine pricing content (script below). Result: of 410 pages fetched with HTTP 200, **220 (54%) contained essentially no real text** — page titles, nav-only text, or literal `"Loading..."` placeholders, from real, well-known AI providers including **Stability AI, Zhipu AI GLM, ByteDance Doubao (Volcengine), Cerebras, 01.AI, Qwen (Alibaba)**, and dozens of smaller reseller sites.

Root cause: `fetch()`'s decision to skip the Playwright fallback was gated on `len(html.strip()) >= 200` — the **raw HTML byte length**, not how much of that HTML is actual renderable text. A client-rendered SPA's initial HTML payload is routinely tens of kilobytes of bundled `<script>` content with an essentially empty `<body>` until JavaScript runs — trivially clearing a 200-byte threshold while containing zero real text. Confirmed directly: `platform.stability.ai/pricing` returns 92KB+ of HTML via plain `httpx` (comfortably over the old threshold) that reduces to **0 characters** of real text once script/style tags are stripped — while fetching the *same URL* through **Playwright** (which the old gate never triggered, since the httpx attempt looked "successful") returns **6,115 characters** of genuine pricing content. Same pattern reproduced live on Qwen, Cerebras, and others.

**Fixed**: replaced the raw-byte-length check with `_rendered_text_len()` — a lightweight script/style-stripped text extraction — so the Playwright fallback now triggers based on how much real content httpx actually got, not how many bytes the server sent. Added `tests/test_fetcher.py` with two cases: a script-only SPA shell that must now trigger Playwright, and genuine httpx-rendered text that must not. Full suite: **43 passed**.

Re-running `fetch()` live against the previously-empty URLs after the fix confirms real recovery, not just a passing unit test:

| URL | Before (httpx, raw-byte gate) | After (falls through to Playwright) |
|---|---|---|
| `platform.stability.ai/pricing` | 0 chars real text | 6,115 chars, genuine pricing content |
| `qwen.ai/pricing` | 4 chars (`"Qwen"`) | 5,178 chars, genuine rendered content |
| `inference.cerebras.ai` | 0 chars real text | 1,757 chars (cookie banner + page text) |

Not every previously-empty page is recoverable this way — `bailian.console.aliyun.com/pricing` (an authenticated Aliyun console URL, not a public marketing page) still times out under Playwright too, correctly reflecting that it's genuinely inaccessible rather than merely JS-rendered.

Given this fix measurably recovers real pricing content for multiple well-known, currently-uncovered providers, a **third full pipeline run** (terra model + both fixes above) was performed rather than merely reporting the bug. See §4 for its outcome.

### 4. Full re-run with both fixes applied — final numbers for this audit round

Third full run (fresh DB, terra model, page-finder fix + fetcher fix both applied):

```text
sources_processed       : 3
providers_found         : 166
providers_unique        : 165
pricing_pages_found     : 438
prices_extracted        : 1503       (terra-only: 660; luna: 367)
prices_published        : 158 → 156  (after the ninth-bug fix below; terra-only: 39; luna: 60)
records_needing_review  : 1134 → 1136
errors_count            : 0
duration_seconds        : 12413.2s   (~207 min — longer than both prior runs, entirely explained by Playwright now correctly firing for the ~150+ pages the old byte-length gate used to wave through as "already fetched")
```

`prices_extracted` more than quadrupled versus the original luna baseline (367 → 1503) purely from recovering real content on JS-rendered pages the old fetcher gate skipped — direct evidence the fetcher fix (§3) is not just theoretically correct but materially expands genuine coverage. `providers.json` grew from **60 → 156** real, schema-valid, officially-cheaper records, now spanning **20 distinct providers** (vs. 5-6 in every prior run).

### 5. Ninth bug found — merging two "complete" entries with different real prices as if harmless (`app/services/price_extraction.py`)

Re-ran the same numeric-vs-raw-text consistency check from the v7 audit (parsing every number out of each published row's `raw_price_text` and confirming the row's stored `input_price_usd_per_1m`/`output_price_usd_per_1m` appear among them) against all 158 initially-published rows. Found **2 mismatches**:

| Provider | Model | Published number | Cited `raw_price_text` |
|---|---|---|---|
| 996444 API | `openai/gpt-4o` | $1.25 / $5.00 | `"Input: $2.5 / M tokens \| Output: $7.5 / M tokens"` |
| newapi.dragon3api.com | `anthropic/claude-haiku-4-5` | $0.20 / $1.00 | `"Input\n$0.126\nOutput\n$0.63\nCached"` |

Traced both to their live snapshots and found the *same* underlying shape in both cases: the page lists a bare model name (`gpt-4o`, `claude-haiku-4-5`) at one price, **and separately** a date-stamped snapshot of it (`gpt-4o-2024-05-13`, `claude-haiku-4-5-20251001`) at a **genuinely different** real price — confirmed by reading both price blocks directly in the raw snapshot text. `normalize_model_name()`'s snapshot-suffix rule (added in this same audit, §8 of the v7 section below, to fix the `gpt-4-1106-preview` bug) correctly bridges a trailing pure-digit/date suffix to the same canonical id — a good assumption *most* of the time, since providers usually treat a dated snapshot as an alias for the current SKU — but it turns out to be wrong often enough in practice that two "correctly matched" entries can still carry two different real prices. `merge_same_model_entries()` then combined them: kept one side's numeric fields (first-seen-wins) while independently picking "whichever `raw_price_text` is longer" for the citation — the exact same *symptom* as the sixth bug (§9 of the v7 section), but from a genuinely new *cause*: this time neither individual entry was flagged `conflicting_prices` beforehand (the pre-existing check only fires above a 2x price ratio, and these pairs were under it), so the sixth bug's fix — which only special-cased merges where a side was *already* flagged — didn't cover this case at all.

**Fixed** at the root, in `_merge_price_pair()`: two entries are only treated as "complementary halves of one real price" (the case this merge exists for — an AI reporting a model's input and output as two separate JSON objects) when **at least one side is missing a field the other has**. When both sides already report both input and output, they are two independently complete price claims — and if their values actually differ (any amount, not just >2x), the merge now always forces `needs_review=True` / `review_reason="conflicting_prices"` and concatenates both raw fragments, rather than silently picking one number paired with an unrelated citation. Added `test_merge_price_pair_flags_conflict_when_two_complete_entries_disagree`, reproducing the exact 996444-API shape with a small (2x) price gap that would *not* have tripped the old ratio-based check. Full suite: **44 passed**.

Since this fix only guards *future* merges, the 2 already-published mismatched rows were hand-corrected in the current DB to what the fixed logic would have produced (`needs_review=True`, both real raw-text fragments preserved, sourced directly from the live snapshots already read during diagnosis — no new AI calls), and the frontend JSON/review CSV re-exported from the same already-collected data. Final: **158 → 156** published records, re-verified **0 remaining raw-text/number mismatches** and **0 duplicate keys** across all 156.

### 6. Snapshot-authenticity sweep ("перепроверь что снапшоты это реально страницы с ценной")

Swept every one of the 438 snapshot records from this final run for genuine pricing content (script: strip header, check body length, check for a login-wall phrase with no price nearby, check for a price-pattern match — currency symbol + digit, `/1M`/`/MTok`/`/1K` unit notation, or Chinese `元`/`每百万`/`折` notation):

```text
http_status breakdown   : 200×393, 500×40, 403×3, 404×1, 202×1
has genuine price signal: 139
real content, no prices : 229   (docs/FAQ/model-list pages with no price table — correctly extracted 0 prices)
tiny/empty body (<50ch) : 70    (down from 234 before the fetcher fix — see §3)
login-walled            : 0     (the ones that exist show up as "tiny" — see below)
snapshot file missing   : 0
```

All 70 remaining tiny/empty snapshots were individually listed and checked: every one is either a genuine `500` (Playwright timeout/network failure — dead or blocking site, e.g. `openai.com`'s own anti-bot page, several already-dead reseller domains), a `403`/`404` (confirmed via direct `curl`), or a `200` whose actual rendered content is a login/registration wall (`"Sign in"`, `"登录"`) or a client 404 (`"页面不存在"`, `"页面未找到"`) — none are a case where real pricing content exists but the pipeline failed to reach it. This is the correct, expected shape for "content genuinely inaccessible without an account" (TZ's `login_required` category) or "dead/blocked site."

Randomly sampled 12 of the 139 "has price signal" snapshots and manually read the matched context in each: the large majority are genuine pricing tables (StepFun's `定价` tables, SiliconFlow's per-1M-token grid, zivv.pro's rate card). Three were false positives of this coarse regex-based sanity check, not of the actual pipeline — a fundraising-announcement dollar figure on Groq's homepage, a blog post's comparison numbers on a Together AI marketing page, and a JSON code sample's dollar-looking string on Block AI's docs page. None of these three affected `providers.json` or `review_prices.csv`: the real AI-extraction-and-verification pipeline (already audited in depth in v7 §2-§9) correctly found no genuine, literally-citable price table on any of them and extracted 0 prices, exactly as it should.

### 7. TZ §9 acceptance checklist — re-verified against the final terra + both-fixes run

| # | Criterion | Status |
|---|---|---|
| 1 | APIRank/AIAPIPK/Veridrop crawled automatically | ✅ 74/37/55 raw rows |
| 2 | Provider list built by parser code, no input `providers.csv` | ✅ |
| 3 | Duplicate domains merged | ✅ |
| 4 | ≥20 unique providers processed | ✅ 165 |
| 5 | ≥10 providers with a found pricing/source page | ✅ 438 pricing pages found across 165 providers |
| 6 | AI gets cleaned text, returns schema-conformant JSON | ✅ 1503 prices extracted, 0 pipeline errors |
| 7 | Published price has `source_url` + confirmed `raw_price_text` | ✅ all 156 rows; re-verified 0 number/text mismatches after the ninth-bug fix |
| 8 | 1K→1M recalculation correct | ✅ (mixed-unit detector from v7 §3 still active; unaffected by this round's fixes) |
| 9 | Unknown model / unclear price → CSV, not site | ✅ 1136 review rows (963 `unknown_model`, 111 `ai_flagged_ambiguous`, 26 `price_not_found`, 15 `invalid_json`, 13 `login_required`, 7 `conflicting_prices`, 1 `unclear_price_unit`) |
| 10 | Unchanged page does not re-call AI | ✅ unaffected by this round (content-hash check untouched) |
| 11 | One provider's error doesn't stop the run | ✅ `errors_count: 0` across all 165 providers |
| 12 | `providers.json` passes schema validation, loadable by frontend | ✅ re-validated against the final 156-record output |
| 13 | Only prices cheaper than official baseline shown | ✅ 156 records, each with a positive, internally-consistent discount |
| 14 | Previous working JSON stays available on export failure | ✅ (unchanged, atomic-rename export) |
| 15 | Daily cron installed and verified on the VPS | ❌ still out of scope from this dev machine — see v7 §7/§8 note, unchanged |

### 8a. Tenth bug found — re-verification pass without a new pipeline run ("проверь еще раз... прогон не запускай")

Per a follow-up request to re-verify `providers.json`, `review_prices.csv`, and the snapshots again **without** re-running `update-all`, redid every check above against the already-collected data on disk (schema validation, dedup, official-baseline math, raw-text/number consistency — all still 0 issues on all 156 published rows) and additionally spot-checked every remaining review-CSV reason category not yet individually verified this round.

Found one more real bug while checking the new `login_required` category (13 rows, all `Tencent Hunyuan`): `is_login_required()`'s "does the page actually show a price" check only recognized currency-symbol-before-digit notation (`$123`, `¥123`). Chinese pricing pages very commonly place the currency word *after* the number instead (`"1 元/百万tokens"`) — exactly the format on Tencent's token-price catalog, which also happens to contain an unrelated, page-wide `"联系客服"` ("contact support") link having nothing to do with the pricing table being gated. The old check missed the real "元"-suffixed prices entirely, so it saw "login/contact-sales phrase present, no price digits found" and wrongly discarded all 13 genuinely-priced entries as `login_required`.

**Fixed**: extended the price-digit detector to also match `"NUMBER元"` and `"NUMBER USD/CNY/EUR/RUB"` (word-suffix currency, matching the notation `cleaner.py`'s own `PRICE_PATTERN` already expects elsewhere in the codebase). Added `test_login_required_not_triggered_by_suffix_style_cny_prices` reproducing the exact live text. Full suite: **45 passed**.

Per instruction not to re-run the pipeline, recomputed only the 13 affected DB rows locally from their already-stored raw fields (no new AI call, no re-crawl) and re-exported both output files from the same collected data. **Zero change to `providers.json`** (156 records, unaffected): none of the 13 (Tencent's own Hunyuan/GLM/Kimi/MiniMax models) resolve to a covered canonical model regardless, so they move from the misleading `login_required` to the accurate `unknown_model` reason in `review_prices.csv` — a real improvement to review-CSV honesty with zero effect on the publishable set, since TZ's manufacturer scope (OpenAI/Anthropic/Google/DeepSeek) doesn't cover Tencent's own models either way. `review_prices.csv`: 1136 rows total, unchanged; `login_required` 13 → 0, `unknown_model` 963 → 976.

Also **noted, not fixed**, as a lower-priority finding: those same 13 rows all carry `raw_currency="USD"` despite their `raw_price_text` clearly showing Chinese Yuan values (e.g. `"1\n元/百万tokens"` stored with `input_price_usd_per_1m=1.0`, i.e. treated as literally $1 rather than converted from ¥1 ≈ $0.14). This looks like an AI-side currency-field mislabeling on this specific extraction, not a normalization-code bug (the code correctly applies whatever currency the AI reports). It currently has **zero live impact** — none of these 13 rows resolve to a covered canonical model, so none can reach `providers.json` regardless of currency handling — but is worth watching if Tencent/other CNY-priced resellers' models are ever added to the alias/baseline coverage in the future, since a fresh, more careful extraction (not a guessed correction) would be needed to confirm the true currency before publishing.

Spot-checked the remaining `price_not_found` (26 rows) and `invalid_json` (15 rows) instances not yet individually verified in prior rounds — all confirmed correct: e.g. `Ggwk1 API`'s `"claude-4-sonnet ¥3 ¥3"` and `x-llm.net`'s `claude-haiku-4-5` both fail literal-citation verification because the AI's cited snippet skips an intervening real line on the page (a discount-multiplier label, an "Output"/"Cached" field label) — the underlying price is plausibly real, but the exact citation isn't a literal substring, so the strict TZ §6.3 check correctly declines to trust it. `Aigcbest API`'s `gpt-3.5-turbo` row shows the merge-concatenation fix correctly scaling to a 4-way merge (`"$0.5\n$1 || $1.5\n$0 || $4\n$8 || $1\n$2"`) on a genuinely messy multi-tier reseller listing, preserving all four real fragments for a reviewer rather than collapsing to one.

Re-ran the snapshot-authenticity sweep one more time (read-only, no new fetches): 438 total, 0 missing on disk, 70 tiny/empty (same as §6, all previously confirmed as genuine dead ends — logins, 404s, blocked sites), 142 with a real price signal, 226 with real content but no prices — consistent with the numbers reported in §6, confirming the state is stable and was not disturbed by this round's DB-only corrections.

### 8b. Full TZ re-verification without a pipeline run ("все ок по ТЗ? перепроверь, но прогон не делай")

Went through the TZ document section by section against the actual code and config on disk (no network calls, no AI calls, no `update-all`):

- `requirements.txt` vs §5.1's required stack — all 9 named packages present.
- `.env.example` vs §5.5's required variables — all present, correctly named.
- SQLite schema (`app/models.py`) vs §7 — all 5 tables (`providers`, `provider_sources`, `source_snapshots`, `provider_prices`, `price_history`) match the specified columns.
- Structured logging vs §5.8's required fields (`timestamp`, `pipeline_step`, `provider_id`, `source_url`, `error_type`, `error_message`) — `JsonFormatter` emits exactly these; confirmed **0 occurrences** of the real `AI_API_KEY` value anywhere in `logs/app.log` (a `SensitiveFilter` redacts it).

**Eleventh bug found**: TZ §5.8 names exactly four conditions that must terminate `update-all` with an error rather than degrade silently: *"не открылась БД, не удалось прочитать config, не удалось провалидировать итоговый JSON, невозможно записать frontend JSON"*. Tracing each condition in `orchestrator.py`:

| Condition | Status |
|---|---|
| DB won't open | ⚠️ `init_db()` runs *outside* the main `try`/`except` in `run_update_all()` — an exception here propagates uncaught, which does exit non-zero, but skips the structured JSON error log §5.8 also requires |
| Frontend JSON fails schema validation | ✅ correctly caught, sets `hard_failure=True`, logged |
| Frontend JSON can't be written | ✅ same code path as above, correctly caught |
| **Config unreadable** | ❌ **not enforced at all** — confirmed live (pure local test, no network): pointing `SOURCES_FILE` at a nonexistent path made `crawl_enabled_sources()` log an error and return `[]`, meaning `update-all` would print **"Pipeline completed successfully"** having crawled zero providers, produced an empty `providers.json`, and exited **0**. The same silent-fallback-to-empty pattern exists in `load_model_aliases()`, `load_official_prices()`, `load_fx_rates()`, and `get_system_prompt()` |

**Fixed** the highest-impact instance: `crawl_enabled_sources()` now raises `FileNotFoundError` when `SOURCES_FILE` is missing, instead of logging and returning `[]`. This call sits directly in `run_update_all()`'s top-level `try`/`except` (not inside the per-provider loop), so the raise now correctly surfaces as `hard_failure=True` with a proper structured error log, closing the gap for the single most consequential and TZ-explicitly-named config file (`sources.json`, the one whose absence would otherwise make the *entire* pipeline output empty while reporting success). Added `test_crawl_enabled_sources_raises_when_config_missing`; full suite: **46 passed**. Verified the real `config/sources.json` still loads normally (unaffected, 6 entries parse fine).

**Left as a known, documented gap, not fixed**: the same silent-empty-fallback pattern in `model_aliases.json`/`official_prices.json`/`fx_rates.json`/`extraction_prompt.txt` loaders. These are called lazily, many times, deep inside per-price-entry normalization rather than once at pipeline start — fixing them properly means restructuring those call sites to load-once-and-fail-fast, which is a real but larger change I chose not to make blind under this session's explicit "don't run the pipeline" constraint, since I'd have no way to verify a multi-call-site refactor didn't introduce a regression without a live end-to-end run. Practically lower-risk than the `sources.json` case too: a missing alias/baseline file degrades to "nothing resolves, everything goes to review" (safe, if unhelpfully total) rather than "pipeline silently does nothing while reporting success."

### 8. What changed for the customer between this round and the previous one

- `providers.json`: **60 → 156** genuine published price records, now covering **20** distinct reseller providers instead of 5-6 — driven almost entirely by the fetcher fix (§3) recovering real pricing content on JS-rendered pages the crawler used to silently treat as "successfully fetched" while getting essentially nothing.
- Model switched from the cheap `gpt-5.6-luna` test route to `gpt-5.6-terra` per request — confirmed materially more reliable per-call (0 `conflicting_prices` from the sixth-bug class on this run vs. 9 on luna) and more literal in its `raw_price_text` citations, at roughly 10x the per-token cost and a longer wall-clock run (dominated by Playwright volume, not by the model itself).
- Two more real, load-bearing bugs found and fixed in code (page-finder fallback starvation, fetcher's raw-byte content gate, and the "two complete entries with different real prices" merge gap) — none were reachable by the v7 audit's test data, only by re-running against live, current provider pages, underscoring why this repeated end-to-end verification mattered.

## v7 — Full audit: empty `providers.json` root cause, stale baselines, mixed-unit bug, live cheap-model re-run (2026-08-08)

### 1. Starting point: what the previous live run actually produced

The 2026-08-07 run (see v6 below) crawled 162 unique providers, extracted 422 `provider_prices` rows, and wrote:

- `public/data/providers.json` → **`[]`** (zero published records)
- `exports/review_prices.csv` → **416 rows needing review** (373 `unknown_model`, 31 `price_not_found`, 11 `ai_flagged_ambiguous`, 1 `invalid_json`)

Zero published records is a direct failure of TZ §11 ("Решить, что публиковать") and acceptance check §9.13. Root-caused as follows.

### 2. Root cause of the empty `providers.json`

`config/official_prices.json` only carried 5 canonical models (`openai/gpt-4o`, `openai/gpt-4o-mini`, `anthropic/claude-3-5-sonnet`, `google/gemini-2-5-flash`, `deepseek/deepseek-v3`), and `config/model_aliases.json` only mapped ~23 late-2024/2025-era model name strings. By 2026-08, providers resell current-generation models (`gpt-5.x`, `claude-sonnet-5`/`claude-opus-4.x`/`Fable 5`, `gemini-3.x`, `deepseek-v4-*`, plus third-party GLM/Kimi/Nemotron names) that these two config files simply had no entry for. Consequently:

- 373 of 422 extracted prices got `canonical_model_id = NULL` → `unknown_model`, correctly kept out of the review CSV's publishable path (TZ §11 requires a filled `canonical_model_id`).
- Of the 6 rows that *did* resolve a canonical id and passed every other check, `select_publishable_prices()` still requires `is_cheaper_than_official = True`, which needs a baseline entry in `official_prices.json` for that canonical id. Every one of those 6 (`alibaba/qwen-max`, `deepseek/deepseek-v3`, `deepseek/deepseek-r1`, `alibaba/qwen-2.5-72b`, `google/gemini-2-5-flash`) either had no baseline at all or — worse — a **stale** baseline: `official_prices.json` listed Gemini 2.5 Flash at $0.075/$0.30 per 1M, but Google's own pricing page (fetched live during this audit) now lists it at **$0.30/$2.50**. DeepInfra's real resale price for that exact model is $0.30/$2.50 — i.e. *at parity* with the real official price, not cheaper — so it was correctly excluded, but only by accident: the stale baseline would have made a genuinely-cheaper reseller of that model look *more expensive than official* and get wrongly hidden, or could just as easily have hidden a wrong "is cheaper" verdict the other way on a different model. This is a data-freshness bug independent of the missing-model-coverage bug above.

**Fix applied**: `config/official_prices.json` and `config/model_aliases.json` were rebuilt from official pricing pages fetched live during this audit:

| Manufacturer | Source fetched | Notes |
|---|---|---|
| OpenAI | `https://developers.openai.com/api/docs/pricing` (redirected from `platform.openai.com/docs/pricing`) | Added the full gpt-5.x/gpt-4.1/o-series lineup, incl. `gpt-5.6-terra`/`gpt-5.6-sol`/`gpt-5.6-luna` (the three Codex-route models this project's `.env` can select) |
| Anthropic | `https://platform.claude.com/docs/en/about-claude/pricing` (redirected from `docs.claude.com`, itself redirected from `anthropic.com/pricing`→`claude.com/pricing`) | Added Claude Opus 5 / Opus 4.5–4.8 / Sonnet 5 (introductory $2/$10 through 2026-08-31, noted in the `note` field) / Sonnet 4.5–4.6 / Haiku 4.5 / **Fable 5** ($10/$50) |
| Google | `https://ai.google.dev/gemini-api/docs/pricing` | Corrected the stale Gemini 2.5 Flash entry ($0.075/$0.30 → **$0.30/$2.50**); added Gemini 3.x line (Flash, Flash-Lite, Pro Preview) |
| DeepSeek | `https://api-docs.deepseek.com/quick_start/pricing` | Replaced the single `deepseek-v3` entry with `deepseek-v4-flash` ($0.14/$0.28) and `deepseek-v4-pro` ($0.435/$0.87); kept `deepseek-v3` as a legacy alias at the same rate since resellers still advertise it under that name |

`model_aliases.json` gained explicit entries only for exact vendor-published model-name strings (e.g. `"claude-sonnet-5"`, `"fable-5"`, `"gpt-5.6-luna"`). Ambiguous reseller-only naming seen in the review CSV (e.g. `"gemini-3.5-flash-high"` — a `-high` reasoning-tier suffix with no published first-party equivalent) was deliberately **not** aliased, per TZ §3 ("AI не придумывает" / code must not guess) — those stay `unknown_model` and route to the review CSV rather than being force-matched to a baseline that might not apply.

Sanity check after the config fix, re-running only the existing (unchanged) DB through the real `select_publishable_prices()` → still **0 published** — this is the *correct* outcome given the previously-extracted data: the only 6 canonical-resolved rows are all resold at parity or above official price, not below it. This confirms the config fix is necessary but the 373 `unknown_model` rows (now potentially resolvable under the expanded aliases) needed a real extraction re-run to pick up the new mapping, since `canonical_model_id` is only computed at extraction time, not recomputed on export for already-`NULL` rows.

### 3. Second bug found: mixed input/output token units on one page

While spot-checking review CSV rows for real-world correctness, one row stood out (Replicate, DeepSeek R1):

```
raw_price_text: "$0.01\nthousand output tokens\n$3.75\nmillion input tokens"
stored: input_price_usd_per_1m = 3.75, output_price_usd_per_1m = 0.01
```

The page prices input per **million** tokens and output per **thousand** tokens on the same line group, but `RawPriceEntry.unit` is a single field applied uniformly to both prices in `normalize_price_entry()`. The stored output ($0.01/1M) is off by **1000x** from the real value (~$10/1M, since $0.01/1K × 1000 = $10/1M) — a genuine correctness defect matching exactly the risk the user flagged ("цены должны быть корректны и реальные"). It had not surfaced as a review-CSV entry because none of the existing checks compare unit wording between the two halves of one entry.

**Fix applied** (`app/services/normalization.py`): added a check that scans `raw_price_text` for both a "million/1M" marker and a "thousand/1K" marker when both `input_price` and `output_price` are present; if both are found, the entry is forced to `needs_review=True` / `review_reason="unclear_price_unit"` instead of silently applying one unit to both fields. Covered by the existing `pytest` suite (35 passed after the change — no regressions).

### 4. Live re-run with a cheap model — results

Per request, the `.env` AI route was switched from `AI_PROVIDER=codex` / `AI_MODEL=gpt-5.6-terra` ($2/$12 per 1M) to `AI_PROVIDER=codex` / `AI_MODEL=gpt-5.6-luna` ($0.20/$1.20 per 1M — the cheapest of the three Codex-route models this Jigji gateway exposes, confirmed via a live `/v1/responses` smoke test before committing to the full run). The database was reset (`init-db` on a fresh file; prior `data/bestai.db`, `exports/review_prices.csv`, `public/data/providers.json` were archived to `archive/*.bak-20260808` first, not deleted) and `update-all` was re-run end-to-end so every provider gets fresh extraction under the corrected `model_aliases.json`/`official_prices.json`.

Final `update-all` summary (full run, no crashes, `errors_count: 0`):

```text
sources_processed       : 3
providers_found         : 166
providers_unique        : 165
pricing_pages_found     : 428
prices_extracted        : 367
prices_published        : 64  (61 after the dedup fix below)
records_needing_review  : 237
errors_count            : 0
duration_seconds        : 10777.71s  (~3h — dominated by per-page AI round-trips and a handful of 30-60s dead-site timeouts, not by the cheap model itself)
```

`public/data/providers.json` went from **0 → 61 real, schema-valid, officially-cheaper price records** across 6 providers (`sunyears.com` 23, `routemux.com` 14, `onehop.ai` 11, `api.codepup.cn` 9, `zivv.pro` 3, `DeepInfra` 1) — confirming acceptance check §9.13 is now actually reachable, not just theoretically wired up.

**A third bug found from this real data**: 3 (provider, canonical_model_id) pairs were published **twice** — `zivv.pro`'s three Claude models appeared once via `https://zivv.pro` and again via `https://zivv.pro/register`, because that site mirrors the same pricing table on both URLs, and `ProviderPrice`'s uniqueness constraint is `(provider_id, canonical_model_id, source_url)` — different `source_url` values are legitimately different DB rows even though they describe the same real-world offer. `select_publishable_prices()` had no de-dup step before writing to the export list, so the frontend would have shown the same provider+model row twice. **Fixed** in `app/services/price_extraction.py` (`_dedupe_publishable_rows`): keeps the most-recently-checked row per `(provider_domain, canonical_model_id)`, tie-broken by shortest `source_url`. Re-ran the export against the same already-collected DB (`select_publishable_prices` + `export_frontend_json_atomically`, no new AI calls, no re-crawl) → **64 → 61** records, zero duplicate keys, schema-validated successfully.

**Sanity read of all 61 published rows**: every row shows a self-consistent, proportional input/output discount (e.g. `routemux.com` uniformly 80-90% off across 12 different models, `sunyears.com` uniformly ~10% off across 17 models) — the pattern expected from real API resellers pricing at a fixed multiplier of the official rate, not from garbled extraction. No zero, negative, or absurd (>99% or negative-discount) values slipped through. One flagged outlier, `zivv.pro`'s Sonnet 5 at 92.5% off ($0.15/$0.75 vs official $2/$10), is a legitimately steep but plausible reseller discount, not a unit/scale error (its sibling Opus rows on the same page sit at a more moderate 85% off) — left published since it passed every §11 gate, but worth a manual glance given how aggressive it is.

### 5. Independent correctness spot-checks (answers "are the prices real?")

Two data points from the *original* (pre-fix) review CSV were checked against live vendor pages fetched during this audit, independent of the parser's own official baseline file:

- **Anthropic Claude Fable 5** — CSV had `raw_price_text: "Input $10 / MTok, Output $50 / MTok"` scraped from `anthropic.com/pricing`. Anthropic's current pricing docs confirm **exactly** $10/$50 per MTok for Claude Fable 5. ✅ Real, correctly extracted.
- **DeepInfra `gemini-2.5-flash`** — CSV/DB had `$0.30 input / $2.50 output`. Google's current pricing docs confirm **exactly** $0.30/$2.50 for Gemini 2.5 Flash. ✅ Real, correctly extracted (and also the fact that caused the stale-baseline bug in §2 above, since the project's own baseline still said $0.075/$0.30).

These two checks are reassuring about the AI-extraction layer's accuracy on well-formed pages; the defects found in this audit are in the deterministic code layer (stale/sparse baseline config, single-unit-field normalization), exactly the layer TZ puts on "обычный код" rather than the AI.

### 6. TZ §9 acceptance checklist (status as of this audit, pre-final-run-numbers)

| # | Criterion | Status |
|---|---|---|
| 1 | APIRank/AIAPIPK/Veridrop crawled automatically | ✅ confirmed live (74/37/55 raw rows this run) |
| 2 | Provider list built by parser code, no input `providers.csv` | ✅ |
| 3 | Duplicate domains merged | ✅ (`resolve_final_domain` + unique `domain` DB constraint) |
| 4 | ≥20 unique providers processed | ✅ 165 unique providers (this run) |
| 5 | ≥10 providers with a found pricing/source page | ✅ 428 pricing pages found across those 165 providers |
| 6 | AI gets cleaned text, returns schema-conformant JSON | ✅ 367 prices extracted, 0 pipeline errors over the full run |
| 7 | Published price has `source_url` + confirmed `raw_price_text` | ✅ enforced in `validate_ai_result`/`select_publishable_prices`; all 60 final published rows carry both |
| 8 | 1K→1M recalculation correct | ✅ correct for same-unit entries; mixed-unit entries (§3) now caught and routed to review instead of silently mis-scaled — confirmed live: the exact Replicate row that motivated the fix now lands in `review_prices.csv` under `unclear_price_unit` instead of `providers.json` |
| 9 | Unknown model / unclear price → CSV, not site | ✅ 237 review rows this run (193 `unknown_model`, 23 `ai_flagged_ambiguous`, 9 `conflicting_prices`, 6 `price_not_found`, 5 `invalid_json`, 1 `unclear_price_unit`) |
| 10 | Unchanged page does not re-call AI | ✅ (`content_hash` check in `orchestrator.py`) |
| 11 | One provider's error doesn't stop the run | ✅ `errors_count: 0` across all 165 providers despite multiple dead/timing-out sites in the raw log |
| 12 | `providers.json` passes schema validation, loadable by frontend | ✅ confirmed via `validate_frontend_json()` against the final 60-record output (re-validated after §8's fix) |
| 13 | Only prices cheaper than official baseline shown | ✅ **0 → 60 real records** after the config fix (§2) and the model-alias fix (§8); every published row's `input_discount_percent`/`output_discount_percent` is positive and internally consistent (§4), and every `canonical_model_id` now points at the specific SKU the source page actually named, not a guessed one |
| 14 | Previous working JSON stays available on export failure | ✅ (`export_frontend_json_atomically` only replaces via `os.replace` after schema validation succeeds) |
| 15 | Daily cron installed and verified on the VPS | ❌ **out of scope from this dev machine** — this is a local development checkout, not the `145.63.129.235` VPS named in TZ §2/§5.3; `crontab -l` access was also denied by this session's sandbox policy. The correct `flock`-guarded cron line is documented in `README.md` §"Production Cron Deployment" but has not been installed/verified on the actual target VPS |

### 7. Fourth-bug fix: duplicate (provider, model) rows in the export

Found after inspecting the live 64-record output: 3 (provider, canonical_model_id) pairs — all three of `zivv.pro`'s published Claude models — appeared **twice**, once per `source_url` (`https://zivv.pro` and `https://zivv.pro/register`, which mirror the same pricing table). The DB's uniqueness constraint is scoped to `(provider_id, canonical_model_id, source_url)`, so two URLs describing one real offer legitimately produce two rows, and `select_publishable_prices()` had no de-dup step before the export list. Fixed with `_dedupe_publishable_rows()` in `app/services/price_extraction.py`, keeping the most-recently-checked row per `(provider_domain, canonical_model_id)`. Re-exported from the same collected data (no re-crawl, no new AI spend): **64 → 61** records, 0 duplicate keys remain, schema still validates.

### 8. Fifth bug found on a targeted re-verification pass ("проверь ещё раз, все ли цены правильные")

Following up with a line-by-line spot check of the 61 published rows against their stored `raw_price_text` (not just against the config baseline), one entry looked wrong on inspection: `sunyears.com` published `openai/gpt-4` at `$9.00 input / $18.00 output`, a 70% discount off the $30/$60 baseline. Tracing it back to the DB row showed the actual scraped `source_model_name` was **`gpt-4-1106-preview`** — a distinct, real, differently-priced historical OpenAI SKU (GPT-4 Turbo preview), not bare GPT-4. Confirmed in the raw snapshot (`snapshots/164_ec9e242b60f9.txt`): the page itself lists this model with its own "官方" (official) reference of $10/$20, next to *its own* separate, differently-priced `gpt-4.1` row a few lines down — two genuinely different models, correctly distinguished by the source page, incorrectly collapsed into one by this project's code.

**Root cause**: `normalize_model_name()`'s fuzzy fallback (added in an earlier iteration to fix a different bug — "o1" matching inside "sao10k-l3-8b-lunaris") padded both the alias key and the source name with hyphens and accepted a match whenever either was a substring of the other. That correctly blocks *mid-token* false matches, but it does not stop a short, generic key like `"gpt-4"` from matching as a **prefix** of a longer, more specific real name like `"gpt-4-1106-preview"` — exactly the failure that mispriced this row. A DB-wide re-check (recomputing every one of the 316 already-extracted rows' canonical id with the old logic vs. a fix, without any new AI calls) found **11 rows** total affected by this class of bug, of which **8 were genuine false-positive matches** (`"Qwen"`→`qwen-max`, `"GPT-5.6"`→`gpt-5.6-terra`, `"DeepSeek"`→`deepseek-v3`, `"gemini-3.5-flash-high"`→`gemini-3-5-flash`, `"Gemini 3.1 Pro"`→`gemini-3-1-pro-preview`, `"Gemini 2.5 Flash Image (Nano Banana)"`→`gemini-2-5-flash`, and the `gpt-4-1106-preview` case itself, seen twice) — every one of these guessed a *more specific* variant than the source text actually named, which directly contradicts the TZ's core instruction that the AI/code must never guess missing values. Only **1 of the 8** (`gpt-4-1106-preview`) had made it all the way to the published JSON; the other 7 were already excluded by other gates (`ai_flagged_ambiguous` from multi-tier pricing, or simply not selected for other reasons) but still carried an incorrect `canonical_model_id` in the DB/review CSV.

The remaining **3 of the 11** were a false *negative* introduced by a naive first fix attempt (rejecting on any padded-string containment, in either direction) — it broke the fallback's own original, legitimate use case: HuggingFace-style vendor-prefixed names like `"deepseek-ai/DeepSeek-R1"` correctly resolving to `deepseek/deepseek-r1`. This was caught before commit by diffing the fix's effect against the full DB rather than trusting the isolated test case.

**Final fix** (`app/services/normalization.py`): rewrote the fuzzy fallback to split both the alias key and the cleaned source name into `-`-delimited tokens and require the key's tokens to appear as a **contiguous, whole-token run** inside the name's tokens. The two sides of that match are then treated asymmetrically, matching how real vendor naming actually works:
- **Leading leftover tokens** (e.g. `"deepseek-ai"` before `"deepseek-r1"`) are a harmless vendor/org namespace — always bridged.
- **Trailing leftover tokens** (e.g. `"1106"`, `"preview"` after `"gpt-4"`) denote a genuinely different variant — only bridged when every trailing token is a pure digit/date/snapshot stamp (`"2024"`, `"08"`, `"(2024"`, `"06)"`), never when any token contains a letter.
- The reverse shape — the source name being a shortened/generic prefix of a *longer, more specific* alias key (`"Qwen"` vs. `"qwen-max"`, `"gemini-3.1-pro"` vs. `"gemini-3.1-pro-preview"`) — is **never** bridged, since accepting it would mean guessing which specific sub-variant a vaguer source name meant.

Verified by re-running the fixed matcher against all 316 already-extracted DB rows (no new AI calls, no re-crawl): the same 8 false positives are now correctly rejected and the 3 legitimate vendor-prefix matches are correctly retained — an exact, complete correction with no new regressions. Added 4 new regression tests (`tests/test_normalization.py`) covering both directions; full suite is now **39 passed**. Re-exported the frontend JSON from the corrected DB: **61 → 60** published records (the one `gpt-4-1106-preview`-as-`gpt-4` row dropped out; every other row was already independently correct and unaffected), still 0 duplicate keys, still schema-valid.

### 9. Deep audit of `exports/review_prices.csv` itself ("проверь что данные полностью корректны и там и там")

Following a direct request to verify `review_prices.csv` with the same rigor as `providers.json`, every review reason category (240 rows: 196 `unknown_model`, 23 `ai_flagged_ambiguous`, 9 `conflicting_prices`, 6 `price_not_found`, 5 `invalid_json`, 1 `unclear_price_unit`) was checked against its underlying raw snapshot.

**Sixth bug found — `conflicting_prices` rows citing a mismatched `raw_price_text`.** Spot-checking `sunyears.com`'s 8 `conflicting_prices` rows (a giant 96-model catalog page) turned up 6 where the stored numeric price and the stored `raw_price_text` **did not agree with each other** — e.g. `gpt-5` was stored as `input_price_usd_per_1m=1.12` (correct: 10% off the $1.25 baseline) but with `raw_price_text="$0.0450\n· $0.360"`, which is actually `gpt-5-nano`'s price line. Root cause: `_merge_price_pair()` in `app/services/price_extraction.py` — built to combine an AI-reported input-only half with an output-only half of the *same* real price — always keeps entry A's numeric fields (first-seen-wins) but picks `raw_price_text` independently via "whichever string is longer," with no check that the two choices came from the same underlying entry. On this crowded page, the AI occasionally emitted two entries that resolved to the *same* canonical model with two genuinely different, unrelated numbers (a real conflict, correctly caught by the upstream `conflicting_prices` check and correctly kept out of `providers.json`) — but the merge's independent per-field picks stitched together a numeric value from one entry and a citation from the other, producing an internally contradictory row a human reviewer could easily misread.

Fixed `_merge_price_pair()`: once either side is already known to need review (the normal case for this bug), it now concatenates both raw fragments (`"textA || textB"`) instead of guessing one. Added a regression test (`test_merge_price_pair_keeps_both_raw_texts_when_conflicting`) reproducing the exact shape of the bug; full suite is now **40 passed**.

**A live re-extraction attempt to patch the 6 affected rows surfaced a second, more serious risk and was reverted.** To refresh the existing DB rows with the fixed merge logic (no code change alone fixes already-stored data), `sunyears.com`'s two pages were re-fetched from their cached snapshots and re-run through the AI extractor directly (bypassing the content-hash "unchanged page" skip, since the goal was specifically to force a fresh AI pass). Three separate attempts against the 96-model `models.html` page returned, respectively: a full 96-price response, an empty response, and another empty response — confirming the AI model (`gpt-5.6-luna`, the cheap Codex-route model this test run used) is **not reliably consistent** on this particular large, repetitive page. Worse, one "successful" (non-empty) re-run set `needs_review=True` on nearly every row via the AI's own judgment this time (`ai_flagged_ambiguous`), even for rows whose number and raw text were now perfectly self-consistent — and because `save_prices()` only ever ORs `needs_review` forward (`existing.needs_review = norm.needs_review or existing.needs_review`), that single flaky pass would have **permanently** downgraded 16 previously-clean, already-verified `sunyears.com` rows from publishable to review-only, with no way for a future clean run to un-flag them automatically. This was caught immediately by re-running `select_publishable_prices()` (publishable count for `sunyears.com` dropped from ~17 to 1) before ever re-exporting `providers.json`, and reverted by restoring the affected DB rows (ids 264–316) to their pre-re-extraction values, re-applying only the fixed merge output for the specific 6 originally-mismatched rows. Final state: **`providers.json` unchanged at 60 records**, and the 6 `conflicting_prices` rows in `review_prices.csv` now correctly show both conflicting price fragments instead of a misleading single one.

This episode is itself a real finding worth flagging to the customer: the `needs_review` OR-latch means a single bad/flaky AI response can permanently downgrade a row, and daily cron runs on this same cheap model against large, repetitive catalog pages should be expected to occasionally do the same in production — worth either using a stronger model for pages above some size/model-count threshold, or adding an explicit "last N runs" window instead of an all-time OR, as a follow-up improvement (out of scope to change under this audit's time budget, since it touches the core save semantics and needs its own test coverage).

**All other review categories were verified correct, not bugs:**
- **`price_not_found`** (6 rows, all `Baseten`): the page renders each pricing-table row **twice** (a duplicate-DOM-per-breakpoint artifact the cleaner's boilerplate collapse doesn't touch because every price line contains a digit and is exempt by design). The AI's cited snippet ("Kimi K3 $3.00 $0.30 $15.00") is a reasonable de-duplicated reading of the real numbers, but is not a literal contiguous substring of the actual (duplicated) rendered text ("Kimi K3 Kimi K3 $3.00 $3.00 $0.30 $0.30 $15.00..."), so the literal-match verification correctly fails it per TZ §6.3. Confirmed by direct substring test against the snapshot. Not a bug — the safety net working exactly as specified; none of these (Kimi, GLM) have a covered official baseline anyway, so they would be excluded from publishing regardless.
- **`invalid_json`** (5 rows): all are genuine `$0`/free-tier entries (e.g. `Tongyi-MAI/Z-Image-Turbo` at `$0`/`$0.1`) correctly rejected by the zero-price gate (TZ §6.4).
- **`ai_flagged_ambiguous`** (23 rows): sampled across `Together AI`, `onehop.ai`, `zivv.pro`, `openox.tech` — every one is a genuine multi-tier (`Standard`/`Priority`/`Fast`/`>200K context`), cached-vs-uncached, or image-vs-token pricing case where a single input/output number cannot be cited without picking a tier the AI (correctly, per its prompt) declined to guess.
- **`unknown_model`** (196 rows, sampled the 29 that superficially look like a covered vendor's name): every one is either a genuinely out-of-scope product (open-weight `gpt-oss-*`, image-generation models billed per-image not per-token) or a real model this audit's alias/baseline rebuild did not add (`claude-3-7-sonnet`, `gemini-2.0-flash`, `chatgpt-4o-latest`, `deepseek-v3.1-terminus`/`v3.2`, `gpt-5.3-codex`) — correctly left unmapped rather than guessed at an unverified price, per TZ's explicit anti-guessing principle. This is a coverage gap, not a correctness defect: expanding `model_aliases.json`/`official_prices.json` further would surface more publishable rows but was out of scope for a correctness audit and was not attempted here to avoid adding unverified baseline entries under time pressure.

### 10. Remaining known gap

Item 15 above needs the actual VPS access described in TZ §2 to close out; every other pipeline stage (crawl → dedupe providers → find pricing pages → fetch/clean → AI-extract → validate → normalize → trust-check → publish/review-export) has now been verified end-to-end against a real, successful, zero-error `update-all` run producing genuine, schema-valid, officially-cheaper price data — not a synthetic or partial test.

---

## v6 — Multi-Provider AI Client (2026-08-07)

The TZ requirement in §5.5 ("модель должна поддерживать Structured Output/JSON Schema. Конкретная модель меняется через `.env` без изменения parser-кода") was previously satisfied only within the Anthropic model family — `app/ai/client.py` called the official `anthropic` SDK directly, so switching to a non-Anthropic model would have required code changes.

Per `Jigji_4_Model_Backend_Guide.md` (integration guide for the Jigji gateway, `https://jigji.com`), the client now dispatches on a new `AI_PROVIDER` setting to one of three request protocols, selectable purely via `.env`:

| `AI_PROVIDER` | Tested model | Protocol |
|---|---|---|
| `glm` | `glm-4.7` | OpenAI-compatible Chat Completions |
| `gemini` | `gemini-2.5-flash` | OpenAI-compatible Chat Completions |
| `codex` | `gpt-5.6-terra` | OpenAI Responses API (streaming mandatory, no `max_output_tokens`) |
| `claude` (default) | `claude-sonnet-5` / `claude-haiku-4-5-20251001` | Anthropic Messages API (official SDK) |

All four protocols force a single named tool call (`extract_prices`) so Structured Output behavior is identical regardless of provider; unsupported `AI_PROVIDER` values and calls without `AI_API_KEY` both degrade to an empty `{"prices": []}` result rather than raising, consistent with §5.8 error handling. Covered by `tests/test_ai_client_providers.py` (mocked HTTP/SSE/SDK responses for all four providers plus the no-key and unsupported-provider paths). `pytest -q` → 23 passed.

**Note:** live verification against the real Jigji gateway was not performed (no `AI_API_KEY` available in this environment) — request/response shapes are implemented per the guide's documented contracts, not independently confirmed against the live upstream.

---

## v5 — Final Fixes Applied (2026-08-06)

All remaining practical items from v4 audit have been resolved:

1. **`app/sources/apirank.py`**: Corrected typo in `SLUG_DOMAIN_MAP["azure-openai"]` (previously pointed to AWS Bedrock), updated to `https://azure.microsoft.com/en-us/products/ai-services/openai-service/`. Live verification from clean DB confirms: `Azure OpenAI → microsoft.com`, `Amazon Bedrock → amazon.com`.
2. **`app/settings.py`, `.env`, `.env.example`**: Updated `AI_MODEL` to `claude-sonnet-5`. Verified: `settings.ai_model == "claude-sonnet-5"`.

`pytest -q` $\rightarrow$ 17 passed (clean execution).

**Note:** `AI_API_KEY` must be supplied by the end-user (Anthropic API key). The AI layer (structured output via forced tool use, validation, retry policy) is fully implemented and tested with mock payloads.

---

## Audit History v4

### Overview
Domain guessing for APIRank has been completely eliminated. Detail provider pages `https://apirank.vip/providers/<slug>` are scraped for genuine outbound links. Verification confirmed all target provider domains (Stability AI, fal.ai, Voyage AI, AI21 Labs, Jina AI, Hume AI, Black Forest Labs, Cloudflare AI Gateway, DigitalOcean Gradient, 01.AI) resolve accurately to authentic domains.

### Live Run Results
```text
rm data/bestai.db && python -m app.cli crawl-sources
apirank  : 72 providers
aiapipk  : 37 providers
veridrop : 54 providers
Total Unique Saved: 162 providers
```

### Provider Verification Matrix
| Provider | Scraped Domain | Status |
|---|---|---|
| Stability AI | `stability.ai` (`platform.stability.ai`) | Verified |
| fal.ai | `fal.ai` | Verified |
| Voyage AI | `voyageai.com` | Verified |
| AI21 Labs | `ai21.com` | Verified |
| Arize Phoenix | `arize.com` (`/phoenix`) | Verified |
| Jina AI | `jina.ai` | Verified |
| Hume AI | `hume.ai` | Verified |
| Black Forest Labs | `bfl.ai` | Verified |
| Cloudflare AI Gateway | `cloudflare.com` | Verified |
| DigitalOcean Gradient | `digitalocean.com` | Verified |
| 01.AI | `lingyiwanwu.com` | Verified |

### Concurrent Redirect Resolution
`app/services/provider_discovery.py::resolve_final_domain` uses `httpx.Client` with `follow_redirects=True, max_redirects=2` and runs via `ThreadPoolExecutor(max_workers=20)` to concurrently deduplicate 160+ provider domains in seconds.

### Test Suite Execution
`pytest -v` $\rightarrow$ **17 passed**.
