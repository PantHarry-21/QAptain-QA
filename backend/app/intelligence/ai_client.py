"""
AI Client Abstraction Layer
Supports: Anthropic Claude, OpenAI, Azure OpenAI
All intelligence passes through this single interface.
"""
from __future__ import annotations
import asyncio
import json
from typing import Any

import anthropic
from google import genai as google_genai
from google.genai import types as google_types
import openai
import structlog

from config import settings

log = structlog.get_logger()


class AIMessage:
    def __init__(self, content: str, model: str, input_tokens: int, output_tokens: int):
        self.content = content
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def json(self) -> dict[str, Any]:
        """Parse JSON from content, handling markdown fences and leading text."""
        text = self.content.strip()
        if not text:
            raise ValueError(f"AI returned empty content (model={self.model})")
        # Strip markdown fences (```json ... ``` or ``` ... ```)
        if text.startswith("```"):
            lines = text.split("\n")
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            text = "\n".join(inner).strip()
        # If still not starting with { or [, find the first JSON object/array
        if text and text[0] not in ("{", "["):
            import re
            m = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
            if m:
                text = m.group(1)
        return json.loads(text)


class AIClient:
    """
    Unified AI client. Instantiate once per service, reuse.

    Usage:
        client = AIClient()
        msg = await client.complete(system="...", user="...", json_mode=True)
        data = msg.json()
    """

    def __init__(self):
        self._provider = settings.AI_PROVIDER

        # Use provider-specific model names so Gemini never receives Anthropic model IDs
        if self._provider == "gemini":
            self._primary_model = settings.GEMINI_MODEL
            self._fast_model = settings.GEMINI_FAST_MODEL
        else:
            self._primary_model = settings.PRIMARY_MODEL
            self._fast_model = settings.FAST_MODEL

        self._anthropic_fallback: anthropic.AsyncAnthropic | None = None

        if self._provider == "anthropic":
            self._anthropic = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        elif self._provider == "azure_openai":
            self._openai = openai.AsyncAzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version=settings.AZURE_OPENAI_API_VERSION,
                max_retries=0,
            )
            # Initialize Anthropic as fallback for when Azure rate-limits are exhausted
            if settings.ANTHROPIC_API_KEY:
                try:
                    self._anthropic_fallback = anthropic.AsyncAnthropic(
                        api_key=settings.ANTHROPIC_API_KEY
                    )
                    log.info("Anthropic fallback client initialized for Azure OpenAI provider")
                except Exception as e:
                    log.warning("Failed to initialize Anthropic fallback client", error=str(e))
        elif self._provider == "gemini":
            self._gemini = google_genai.Client(api_key=settings.GEMINI_API_KEY)
        else:
            self._openai = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=0)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        fast: bool = False,
        json_mode: bool = False,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> AIMessage:
        # Azure OpenAI uses deployment names, not model names — always use the configured deployment
        if self._provider == "azure_openai":
            selected_model = settings.AZURE_OPENAI_DEPLOYMENT
        else:
            selected_model = model or (self._fast_model if fast else self._primary_model)

        try:
            if self._provider == "anthropic":
                return await self._call_anthropic(
                    system=system, user=user, model=selected_model,
                    max_tokens=max_tokens, temperature=temperature,
                )
            elif self._provider == "gemini":
                return await self._call_gemini(
                    system=system, user=user, model=selected_model,
                    max_tokens=max_tokens, json_mode=json_mode,
                )
            else:
                return await self._call_openai(
                    system=system, user=user, model=selected_model,
                    max_tokens=max_tokens, temperature=temperature, json_mode=json_mode,
                )
        except Exception as e:
            log.error("AI completion failed", provider=self._provider, error=str(e))
            raise

    async def _call_anthropic(
        self, system: str, user: str, model: str,
        max_tokens: int, temperature: float,
    ) -> AIMessage:
        response = await self._anthropic.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return AIMessage(
            content=response.content[0].text,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    async def _call_gemini(
        self, system: str, user: str, model: str,
        max_tokens: int, json_mode: bool,
    ) -> AIMessage:
        config = google_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        resp = await self._gemini.aio.models.generate_content(
            model=model,
            contents=user,
            config=config,
        )
        text = resp.text or ""
        usage = resp.usage_metadata
        return AIMessage(
            content=text,
            model=model,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
        )

    async def _call_openai(
        self, system: str, user: str, model: str,
        max_tokens: int, temperature: float, json_mode: bool,
    ) -> AIMessage:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # Azure deployments (e.g. gpt-5-mini) only support the default temperature (1)
        # and reject any other value — omit the parameter entirely for Azure.
        if self._provider != "azure_openai":
            kwargs["temperature"] = temperature
        # json_object format not universally supported on Azure — rely on system prompt instead
        if json_mode and self._provider != "azure_openai":
            kwargs["response_format"] = {"type": "json_object"}

        # Retry on 429 Rate Limit with exponential backoff (Azure TPM/RPM limits)
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                response = await self._openai.chat.completions.create(**kwargs)
                break
            except openai.RateLimitError as exc:
                last_exc = exc
                wait = min(20 * (2 ** attempt), 120)  # 20s, 40s, 80s, 120s, 120s
                log.warning("Azure 429 rate limit — backing off",
                            provider=self._provider, model=model,
                            attempt=attempt + 1, wait_seconds=wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                log.error("OpenAI API call failed", provider=self._provider, model=model,
                          error=str(exc), kwargs_keys=list(kwargs.keys()))
                raise
        else:
            log.error("OpenAI API call failed after rate-limit retries",
                      provider=self._provider, model=model, error=str(last_exc))
            if self._anthropic_fallback is not None:
                log.warning(
                    "Azure OpenAI exhausted all retries — falling back to Anthropic Claude",
                    original_model=model,
                    fallback_model="claude-haiku-4-5-20251001",
                )
                fallback_response = await self._anthropic_fallback.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=max_tokens,
                    temperature=0.1,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return AIMessage(
                    content=fallback_response.content[0].text,
                    model="claude-haiku-4-5-20251001",
                    input_tokens=fallback_response.usage.input_tokens,
                    output_tokens=fallback_response.usage.output_tokens,
                )
            raise last_exc  # type: ignore[misc]

        if not response.choices:
            log.error("AI response has no choices", provider=self._provider, model=model,
                      usage=str(response.usage))
            raise ValueError(f"AI returned no choices (model={model})")

        choice = response.choices[0]
        msg = choice.message.content or ""
        refusal = getattr(choice.message, "refusal", None)

        log.info("AI response",
            provider=self._provider, model=model,
            finish_reason=choice.finish_reason,
            content_len=len(msg),
            refusal=refusal,
            usage=f"in={response.usage.prompt_tokens} out={response.usage.completion_tokens}" if response.usage else None,
        )

        if not msg:
            if refusal:
                raise ValueError(f"AI refused: {refusal}")
            raise ValueError(
                f"AI returned empty content (model={model}, finish_reason={choice.finish_reason})"
            )

        return AIMessage(
            content=msg,
            model=model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )


# Module-level singleton
_client: AIClient | None = None


def get_ai_client() -> AIClient:
    global _client
    if _client is None:
        _client = AIClient()
    return _client
