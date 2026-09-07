"""Prompt construction and response parsing for generated form content."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from formharvester.llm.types import GeneratedFormContent, LlmError

_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)

SYSTEM_PROMPT = """You write concise, truthful contact-form messages.
Use the user's subject and message instructions as the primary guidance.
Use only the supplied structured context; do not invent facts, offers, prices,
relationships, or credentials. Return only one valid JSON object with exactly
two string fields: \"subject\" and \"message\". Do not include Markdown,
code fences, or commentary outside the JSON object."""


def build_form_prompt(
    subject_prompt: str,
    message_prompt: str,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    """Return the stable system and user prompts sent to an LLM provider.

    The context is intentionally supplied as JSON rather than page HTML. This
    keeps the provider boundary auditable and prevents cookies, scripts, and
    unrelated page content from being sent accidentally.
    """

    payload = {
        "subject_prompt": subject_prompt,
        "message_prompt": message_prompt,
        "context": dict(context),
    }
    user_prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return SYSTEM_PROMPT, user_prompt


def parse_generated_content(text: str, *, provider: str = "", model: str = "") -> GeneratedFormContent:
    """Parse and validate a provider's JSON response."""

    candidate = text.strip()
    fenced = _JSON_FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LlmError("The LLM returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise LlmError("The LLM response was not a JSON object.")

    subject = data.get("subject")
    message = data.get("message")
    if not isinstance(subject, str) or not subject.strip():
        raise LlmError("The LLM response did not contain a usable subject.")
    if not isinstance(message, str) or not message.strip():
        raise LlmError("The LLM response did not contain a usable message.")

    return GeneratedFormContent(
        subject=subject.strip(),
        message=message.strip(),
        provider=provider,
        model=model,
    )
