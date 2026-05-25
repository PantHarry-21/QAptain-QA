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
        """Parse JSON from content, handling markdown fences."""
        text = self.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
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

        if self._provider == "anthropic":
            self._anthropic = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        elif self._provider == "azure_openai":
            self._openai = openai.AsyncAzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )
        elif self._provider == "gemini":
            self._gemini = google_genai.Client(api_key=settings.GEMINI_API_KEY)
        else:
            self._openai = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

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
        # response_format=json_object is not supported by all Azure deployments.
        # The system prompt already instructs the model to return only JSON,
        # and AIMessage.json() strips markdown fences — so this is safe to skip.
        if json_mode and self._provider != "azure_openai":
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self._openai.chat.completions.create(**kwargs)
        except Exception as exc:
            log.error("OpenAI API call failed", provider=self._provider, model=model,
                      error=str(exc), kwargs_keys=list(kwargs.keys()))
            raise
        msg = response.choices[0].message.content or ""
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
