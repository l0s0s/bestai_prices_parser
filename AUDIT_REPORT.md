# Implementation Audit Report (`bestai_price_parser_tz.md`)

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
