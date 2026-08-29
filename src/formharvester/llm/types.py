"""Public types shared by LLM prompt and provider modules."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class LlmError(RuntimeError):
    """A provider or response error that must prevent form submission."""


@dataclass(frozen=True)
class GeneratedFormContent:
    """Validated Subject and Message content returned by an LLM."""

    subject: str
    message: str
    provider: str = ""
    model: str = ""


class LlmClient(Protocol):
    provider: str
    model: str

    def generate(
        self,
        subject_prompt: str,
        message_prompt: str,
        context: Mapping[str, Any],
    ) -> GeneratedFormContent: ...


ReviewCallback = Callable[[str, GeneratedFormContent], GeneratedFormContent | None]
