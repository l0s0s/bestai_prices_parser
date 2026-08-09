import json
import pytest
import anthropic

from app.ai.client import AiClient

DUMMY_SCHEMA = {"type": "object", "properties": {"prices": {"type": "array"}}}


# ---------------------------------------------------------------------------
# GLM / Gemini — OpenAI-compatible Chat Completions
# ---------------------------------------------------------------------------

class _FakeChatResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeChatHTTPXClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        _FakeChatHTTPXClient.calls.append({"url": url, "headers": headers, "json": json})
        tool_call = {
            "function": {
                "name": "extract_prices",
                "arguments": json_dumps_prices(),
            }
        }
        return _FakeChatResponse({
            "choices": [{"message": {"role": "assistant", "tool_calls": [tool_call]}}]
        })


def json_dumps_prices():
    return json.dumps({"prices": [{"source_model_name": "glm-4.7", "raw_price_text": "$1 / 1M"}]})


@pytest.mark.parametrize("provider,model", [("glm", "glm-4.7"), ("gemini", "gemini-2.5-flash")])
def test_openai_chat_providers_dispatch_and_parse(monkeypatch, provider, model):
    _FakeChatHTTPXClient.calls = []
    monkeypatch.setattr("app.ai.client.httpx.Client", _FakeChatHTTPXClient)

    client = AiClient(api_key="k", base_url="https://jigji.com", model=model, provider=provider)
    raw = client.extract("sys prompt", "https://example.com/pricing", "page text", DUMMY_SCHEMA)
    data = json.loads(raw)

    assert data["source_url"] == "https://example.com/pricing"
    assert data["prices"][0]["source_model_name"] == "glm-4.7"

    call = _FakeChatHTTPXClient.calls[0]
    assert call["url"] == "https://jigji.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["json"]["model"] == model
    assert call["json"]["stream"] is False
    assert call["json"]["tool_choice"]["function"]["name"] == "extract_prices"


class _FakeFencedTextHTTPXClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        # No tool_calls: the model ignored the forced tool_choice and replied
        # with a ```json-fenced code block instead (observed on the real gateway).
        body = (
            "```json\n"
            '{"prices": [{"source_model_name": "Sonnet 5", "raw_price_text": "$2 / MTok"}]}'
            "\n```"
        )
        return _FakeChatResponse({
            "choices": [{"message": {"role": "assistant", "content": body}, "finish_reason": "stop"}]
        })


def test_openai_chat_recovers_fenced_json_when_tool_choice_ignored(monkeypatch):
    monkeypatch.setattr("app.ai.client.httpx.Client", _FakeFencedTextHTTPXClient)

    client = AiClient(api_key="k", base_url="https://jigji.com", model="gemini-2.5-flash", provider="gemini")
    raw = client.extract("sys prompt", "https://example.com/pricing", "page text", DUMMY_SCHEMA)
    data = json.loads(raw)

    assert data["source_url"] == "https://example.com/pricing"
    assert data["prices"][0]["source_model_name"] == "Sonnet 5"


class _FakeFencedArrayHTTPXClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        # Observed on the real gateway: a bare JSON array of price objects,
        # not wrapped in {"source_url": ..., "prices": [...]}.
        body = (
            "```json\n"
            '[{"source_model_name": "Opus 5", "raw_price_text": "$5 / MTok"}]'
            "\n```"
        )
        return _FakeChatResponse({
            "choices": [{"message": {"role": "assistant", "content": body}, "finish_reason": "stop"}]
        })


def test_openai_chat_recovers_fenced_bare_array_when_tool_choice_ignored(monkeypatch):
    monkeypatch.setattr("app.ai.client.httpx.Client", _FakeFencedArrayHTTPXClient)

    client = AiClient(api_key="k", base_url="https://jigji.com", model="gemini-2.5-flash", provider="gemini")
    raw = client.extract("sys prompt", "https://example.com/pricing", "page text", DUMMY_SCHEMA)
    data = json.loads(raw)

    assert data["source_url"] == "https://example.com/pricing"
    assert data["prices"][0]["source_model_name"] == "Opus 5"


# ---------------------------------------------------------------------------
# Codex — OpenAI Responses API (streaming, no max_output_tokens)
# ---------------------------------------------------------------------------

class _FakeStreamResponse:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeStreamHTTPXClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, method, url, headers=None, json=None):
        _FakeStreamHTTPXClient.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        import json as json_mod
        completed_event = {
            "type": "response.completed",
            "response": {
                "output": [{
                    "type": "function_call",
                    "name": "extract_prices",
                    "arguments": json_mod.dumps({"prices": [{"source_model_name": "gpt-5.6-terra", "raw_price_text": "$2 / 1M"}]}),
                }]
            },
        }
        lines = [
            "data: " + json_mod.dumps({"type": "response.created"}),
            "data: " + json_mod.dumps(completed_event),
            "data: [DONE]",
        ]
        return _FakeStreamResponse(lines)


def test_codex_responses_api_dispatch_and_parse(monkeypatch):
    _FakeStreamHTTPXClient.calls = []
    monkeypatch.setattr("app.ai.client.httpx.Client", _FakeStreamHTTPXClient)

    client = AiClient(api_key="k", base_url="https://jigji.com", model="gpt-5.6-terra", provider="codex")
    raw = client.extract("sys prompt", "https://example.com/pricing", "page text", DUMMY_SCHEMA)
    data = json.loads(raw)

    assert data["prices"][0]["source_model_name"] == "gpt-5.6-terra"

    call = _FakeStreamHTTPXClient.calls[0]
    assert call["url"] == "https://jigji.com/v1/responses"
    assert call["json"]["stream"] is True
    assert "max_output_tokens" not in call["json"]


# ---------------------------------------------------------------------------
# Claude — Anthropic Messages API
# ---------------------------------------------------------------------------

class _FakeToolBlock:
    type = "tool_use"
    name = "extract_prices"

    def __init__(self, input_data):
        self.input = input_data


class _FakeAnthropicResponse:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def create(self, **kwargs):
        _FakeAnthropicClient.last_kwargs = kwargs
        return _FakeAnthropicResponse([
            _FakeToolBlock({"prices": [{"source_model_name": "claude-haiku-4-5-20251001", "raw_price_text": "$3 / 1M"}]})
        ])


class _FakeAnthropicClient:
    last_kwargs = None

    def __init__(self, api_key=None, base_url=None, timeout=None):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.messages = _FakeMessages()


def test_claude_anthropic_dispatch_and_parse(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropicClient)

    client = AiClient(api_key="k", base_url="https://jigji.com", model="claude-haiku-4-5-20251001", provider="claude")
    raw = client.extract("sys prompt", "https://example.com/pricing", "page text", DUMMY_SCHEMA)
    data = json.loads(raw)

    assert data["prices"][0]["source_model_name"] == "claude-haiku-4-5-20251001"
    assert _FakeAnthropicClient.last_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert _FakeAnthropicClient.last_kwargs["tool_choice"] == {"type": "tool", "name": "extract_prices"}


# ---------------------------------------------------------------------------
# Unsupported provider / no key
# ---------------------------------------------------------------------------

def test_unsupported_provider_returns_empty_without_raising():
    client = AiClient(api_key="k", base_url="https://jigji.com", model="whatever", provider="mystery-llm")
    raw = client.extract("sys", "https://example.com/pricing", "text", DUMMY_SCHEMA)
    data = json.loads(raw)
    assert data["prices"] == []


def test_no_api_key_returns_empty_for_any_provider():
    client = AiClient(api_key="", provider="glm")
    raw = client.extract("sys", "https://example.com/pricing", "text", DUMMY_SCHEMA)
    data = json.loads(raw)
    assert data["prices"] == []
