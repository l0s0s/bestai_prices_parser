import json
import re
from typing import Dict, Any, Optional
import httpx
from app.settings import settings
from app.logging_setup import logger

# Some gateways/models ignore a forced tool_choice on long/complex schemas and
# answer in plain text instead — often as a ```json ... ``` fenced code block.
# Strip the fence (if any) so the JSON payload underneath can still be recovered.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    match = _JSON_FENCE_RE.match(text)
    return match.group(1).strip() if match else text

# Provider -> request protocol, per Jigji gateway integration guide.
# "openai_chat"      : OpenAI-compatible Chat Completions (/v1/chat/completions)
# "openai_responses" : OpenAI Responses API, streaming mandatory (/v1/responses)
# "anthropic"        : Anthropic Messages API (via official SDK)
PROVIDER_PROTOCOLS = {
    "glm": "openai_chat",
    "gemini": "openai_chat",
    "codex": "openai_responses",
    "claude": "anthropic",
}

TOOL_NAME = "extract_prices"
TOOL_DESCRIPTION = "Extract structured AI API models and prices from page text"
MAX_PAGE_CHARS = 12000


def _empty_result(source_url: str) -> str:
    return json.dumps({"source_url": source_url, "prices": []}, ensure_ascii=False)


def _user_content(source_url: str, page_text: str) -> str:
    return f"source_url: {source_url}\n\nPage Content:\n{page_text[:MAX_PAGE_CHARS]}"


class AiClient:
    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = None,
        provider: Optional[str] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.ai_api_key
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.model = model or settings.ai_model
        self.provider = (provider or settings.ai_provider or "claude").strip().lower()
        self.timeout = settings.ai_timeout_seconds

    def extract(self, system_prompt: str, source_url: str, page_text: str, schema: Dict[str, Any]) -> str:
        """Call the configured AI provider with a forced tool-call for Structured Output.

        Which HTTP protocol is spoken (OpenAI Chat Completions, OpenAI Responses,
        or Anthropic Messages) is decided purely by AI_PROVIDER/AI_MODEL/AI_BASE_URL
        in .env — no code changes are required to switch between the four
        Jigji-tested model routes (GLM, Gemini, Codex, Claude).
        """
        if not self.api_key:
            logger.info(
                f"No AI_API_KEY configured. Returning empty extraction result for {source_url}.",
                extra={"pipeline_step": "ai_extract", "source_url": source_url}
            )
            return _empty_result(source_url)

        protocol = PROVIDER_PROTOCOLS.get(self.provider)
        if protocol is None:
            logger.error(
                f"Unsupported AI_PROVIDER '{self.provider}'. Expected one of {sorted(PROVIDER_PROTOCOLS)}.",
                extra={"pipeline_step": "ai_extract", "source_url": source_url, "error_type": "unsupported_provider"}
            )
            return _empty_result(source_url)

        try:
            if protocol == "openai_chat":
                return self._extract_openai_chat(system_prompt, source_url, page_text, schema)
            if protocol == "openai_responses":
                return self._extract_openai_responses(system_prompt, source_url, page_text, schema)
            return self._extract_anthropic(system_prompt, source_url, page_text, schema)
        except Exception as e:
            logger.error(
                f"AI API call failed for {source_url} via provider={self.provider}: {e}",
                extra={"pipeline_step": "ai_extract", "source_url": source_url, "error_type": type(e).__name__}
            )
            return _empty_result(source_url)

    # ------------------------------------------------------------------
    # GLM / Gemini — OpenAI-compatible Chat Completions
    # ------------------------------------------------------------------
    def _extract_openai_chat(self, system_prompt: str, source_url: str, page_text: str, schema: Dict[str, Any]) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _user_content(source_url, page_text)},
            ],
            "max_tokens": 4096,
            "stream": False,
            "tools": [{
                "type": "function",
                "function": {
                    "name": TOOL_NAME,
                    "description": TOOL_DESCRIPTION,
                    "parameters": schema,
                },
            }],
            "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        message = data["choices"][0]["message"]
        for call in message.get("tool_calls") or []:
            if call.get("function", {}).get("name") == TOOL_NAME:
                return self._coerce_tool_json(call["function"].get("arguments"), source_url)

        # Some gateways fall back to plain-text (possibly ```json-fenced) JSON in
        # content when a forced tool_choice is ignored upstream.
        text_result = self._coerce_text_json(message.get("content"), source_url)
        if text_result is not None:
            return text_result

        return _empty_result(source_url)

    # ------------------------------------------------------------------
    # Codex — OpenAI Responses API (streaming mandatory, no max_output_tokens)
    # ------------------------------------------------------------------
    def _extract_openai_responses(self, system_prompt: str, source_url: str, page_text: str, schema: Dict[str, Any]) -> str:
        url = f"{self.base_url}/v1/responses"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": _user_content(source_url, page_text)}]},
            ],
            "tools": [{
                "type": "function",
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "parameters": schema,
            }],
            "tool_choice": {"type": "function", "name": TOOL_NAME},
            "stream": True,  # this deployment rejects non-streaming requests
            # Note: intentionally no "max_output_tokens" — rejected by this upstream.
        }

        # Per the documented contract, the terminal response.completed event
        # carries the full response.output array. This gateway (Jigji/yunwu)
        # does NOT follow that: its response.completed event is a near-empty
        # marker ({"id": "resp_completed"}) with no "output" field at all, and
        # sometimes fires *twice* — so trusting only the last completed event
        # silently discarded every real result. The actual content streams
        # through response.output_item.done events instead; collect those as
        # we go and prefer response.completed's own "output" only when a
        # (possibly other) deployment actually populates it.
        output_items: list = []
        completed_seen = False
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", url, headers=headers, json=body) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("type")
                    if event_type == "response.output_item.done":
                        item = event.get("item")
                        if item:
                            output_items.append(item)
                    elif event_type == "response.completed":
                        completed_seen = True
                        completed_output = (event.get("response") or {}).get("output")
                        if completed_output:
                            output_items = completed_output

        if not completed_seen:
            raise ValueError("Codex stream ended without a response.completed event")

        for item in output_items:
            if item.get("type") == "function_call" and item.get("name") == TOOL_NAME:
                return self._coerce_tool_json(item.get("arguments"), source_url)

        # Fallback: forced tool_choice ignored, model answered with a plain-text
        # (possibly ```json-fenced) message item instead.
        for item in output_items:
            if item.get("type") == "message":
                for part in item.get("content", []):
                    text = part.get("text") if isinstance(part, dict) else None
                    text_result = self._coerce_text_json(text, source_url)
                    if text_result is not None:
                        return text_result

        return _empty_result(source_url)

    # ------------------------------------------------------------------
    # Claude — Anthropic Messages API (official SDK)
    # ------------------------------------------------------------------
    def _extract_anthropic(self, system_prompt: str, source_url: str, page_text: str, schema: Dict[str, Any]) -> str:
        import anthropic
        client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self.base_url or None,
            timeout=self.timeout,
        )

        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            tools=[{
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "input_schema": schema,
            }],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": _user_content(source_url, page_text)}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                tool_input = block.input
                if isinstance(tool_input, dict):
                    tool_input.setdefault("source_url", source_url)
                    return json.dumps(tool_input, ensure_ascii=False)
                return str(tool_input)
            if block.type == "text":
                text_result = self._coerce_text_json(block.text, source_url)
                if text_result is not None:
                    return text_result

        return _empty_result(source_url)

    @staticmethod
    def _wrap_parsed_json(parsed: Any, source_url: str) -> Optional[str]:
        """Normalize a parsed JSON payload to the {"source_url", "prices": [...]}
        shape. Some deployments return a bare array of price objects instead of
        the full wrapper object — treat that as the "prices" list rather than
        discarding it. Some models (seen live on the codex/gpt-5.6-terra route)
        ignore the schema's "prices" key name entirely and answer with
        "entries" instead — same shape, different label."""
        if isinstance(parsed, dict):
            if "prices" not in parsed and "entries" in parsed:
                parsed["prices"] = parsed.pop("entries")
            parsed.setdefault("source_url", source_url)
            return json.dumps(parsed, ensure_ascii=False)
        if isinstance(parsed, list):
            return json.dumps({"source_url": source_url, "prices": parsed}, ensure_ascii=False)
        return None

    @classmethod
    def _coerce_tool_json(cls, arguments: Any, source_url: str) -> str:
        parsed = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return cls._wrap_parsed_json(parsed, source_url) or _empty_result(source_url)

    @classmethod
    def _coerce_text_json(cls, text: Optional[str], source_url: str) -> Optional[str]:
        """Recover a structured result from a plain-text model reply, unwrapping a
        ```json fence if present (and a bare JSON array, if that's all that's
        inside). Returns None rather than raising, so callers can keep trying
        other fallbacks before giving up."""
        if not isinstance(text, str) or not text.strip():
            return None
        candidate = _strip_json_fence(text)
        is_object = candidate.startswith("{") and candidate.endswith("}")
        is_array = candidate.startswith("[") and candidate.endswith("]")
        if not (is_object or is_array):
            return None
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return cls._wrap_parsed_json(parsed, source_url)
