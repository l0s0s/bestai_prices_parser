import json
from typing import Dict, Any
from app.settings import settings
from app.logging_setup import logger


class AiClient:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or settings.ai_api_key
        self.base_url = base_url or settings.ai_base_url
        self.model = model or settings.ai_model
        self.timeout = settings.ai_timeout_seconds

    def extract(self, system_prompt: str, source_url: str, page_text: str, schema: Dict[str, Any]) -> str:
        """Call Anthropic AI API with guaranteed Structured Output tool schema."""
        if not self.api_key:
            logger.info(
                f"No AI_API_KEY configured. Returning empty extraction result for {source_url}.",
                extra={"pipeline_step": "ai_extract", "source_url": source_url}
            )
            return json.dumps({"source_url": source_url, "prices": []}, ensure_ascii=False)

        try:
            import anthropic
            client = anthropic.Anthropic(
                api_key=self.api_key,
                base_url=self.base_url if self.base_url and self.base_url != "https://api.anthropic.com" else None,
                timeout=self.timeout,
            )

            prompt_content = f"source_url: {source_url}\n\nPage Content:\n{page_text[:12000]}"

            tool_definition = {
                "name": "extract_prices",
                "description": "Extract structured AI API models and prices from page text",
                "input_schema": schema,
            }

            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                tools=[tool_definition],
                tool_choice={"type": "tool", "name": "extract_prices"},
                messages=[{"role": "user", "content": prompt_content}],
            )

            # Look for tool_use block
            for block in response.content:
                if block.type == "tool_use" and block.name == "extract_prices":
                    tool_input = block.input
                    if isinstance(tool_input, dict):
                        # Ensure source_url is populated
                        tool_input.setdefault("source_url", source_url)
                        return json.dumps(tool_input, ensure_ascii=False)
                    return str(tool_input)
                elif block.type == "text":
                    text_content = block.text.strip()
                    if text_content.startswith("{") and text_content.endswith("}"):
                        return text_content

            # Fallback if text output is returned
            text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            if text_blocks:
                return text_blocks[0].strip()

            return json.dumps({"source_url": source_url, "prices": []}, ensure_ascii=False)

        except Exception as e:
            logger.error(
                f"Anthropic API call failed for {source_url}: {e}",
                extra={"pipeline_step": "ai_extract", "source_url": source_url, "error_type": type(e).__name__}
            )
            return json.dumps({"source_url": source_url, "prices": []}, ensure_ascii=False)
