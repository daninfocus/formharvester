"""Small HTTP adapters for the supported text-generation providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import requests

from formharvester.llm.prompts import build_form_prompt, parse_generated_content
from formharvester.llm.types import GeneratedFormContent, LlmClient, LlmError


@dataclass
class _HttpClient:
    api_key: str
    model: str
    timeout: int = 60

    provider: str = ""

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            detail = ""
            response = getattr(exc, "response", None)
            if response is not None:
                detail = f" (HTTP {response.status_code})"
            raise LlmError(f"{self.provider} request failed{detail}.") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise LlmError(f"{self.provider} returned a non-JSON response.") from exc
        if not isinstance(body, dict):
            raise LlmError(f"{self.provider} returned an unexpected response.")
        return body

    def _parse(self, text: str) -> GeneratedFormContent:
        return parse_generated_content(text, provider=self.provider, model=self.model)


@dataclass
class OpenAIClient(_HttpClient):
    provider: str = "openai"

    def generate(self, subject_prompt: str, message_prompt: str, context: Mapping[str, Any]) -> GeneratedFormContent:
        system, user = build_form_prompt(subject_prompt, message_prompt, context)
        body = self._post(
            "https://api.openai.com/v1/responses",
            {
                "model": self.model,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": system}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user}]},
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "form_content",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {"subject": {"type": "string"}, "message": {"type": "string"}},
                            "required": ["subject", "message"],
                            "additionalProperties": False,
                        },
                    }
                },
            },
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        text = body.get("output_text")
        if not isinstance(text, str) or not text.strip():
            text = _extract_text(body.get("output"))
        if not text:
            raise LlmError("OpenAI returned no generated text.")
        return self._parse(text)


@dataclass
class AnthropicClient(_HttpClient):
    provider: str = "anthropic"

    def generate(self, subject_prompt: str, message_prompt: str, context: Mapping[str, Any]) -> GeneratedFormContent:
        system, user = build_form_prompt(subject_prompt, message_prompt, context)
        body = self._post(
            "https://api.anthropic.com/v1/messages",
            {
                "model": self.model,
                "max_tokens": 800,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        text = _extract_text(body.get("content"))
        if not text:
            raise LlmError("Anthropic returned no generated text.")
        return self._parse(text)


@dataclass
class DeepSeekClient(_HttpClient):
    provider: str = "deepseek"

    def generate(self, subject_prompt: str, message_prompt: str, context: Mapping[str, Any]) -> GeneratedFormContent:
        system, user = build_form_prompt(subject_prompt, message_prompt, context)
        body = self._post(
            "https://api.deepseek.com/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "temperature": 0.2,
                "max_tokens": 800,
            },
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        text = _extract_text(body.get("choices"))
        if not text:
            raise LlmError("DeepSeek returned no generated text.")
        return self._parse(text)


def create_llm_client(provider: str, api_key: str, model: str, *, timeout: int = 60) -> LlmClient:
    """Create a configured provider client, rejecting incomplete settings."""

    name = provider.strip().lower()
    if name not in {"openai", "anthropic", "deepseek"}:
        raise ValueError(f"unknown LLM provider: {provider!r}")
    if not api_key.strip():
        raise ValueError(f"{name} requires an API key")
    if not model.strip():
        raise ValueError(f"{name} requires a model")

    client_type = {
        "openai": OpenAIClient,
        "anthropic": AnthropicClient,
        "deepseek": DeepSeekClient,
    }[name]
    return client_type(api_key=api_key.strip(), model=model.strip(), timeout=timeout)


def _extract_text(value: Any) -> str:
    """Extract text from the small provider-specific response shapes."""

    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        return "".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if key in value:
                text = _extract_text(value[key])
                if text:
                    return text
    return ""
