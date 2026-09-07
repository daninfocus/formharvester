"""Network-free tests for LLM prompts and provider adapters."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

import formharvester.form_handler.forms as forms_module
from formharvester.form_handler import FormHandlerMixin
from formharvester.llm import build_form_prompt, parse_generated_content
from formharvester.llm.providers import AnthropicClient, DeepSeekClient, OpenAIClient, create_llm_client
from formharvester.llm.types import GeneratedFormContent, LlmError


class _Response:
    def __init__(self, body: dict[str, Any], status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(response=self)

    def json(self) -> dict[str, Any]:
        return self._body


def test_prompt_is_structured_and_does_not_add_page_html() -> None:
    system, user = build_form_prompt(
        "Ask about a website rebuild",
        "Be brief and mention our frontend experience",
        {"target_url": "https://acme.test", "form_fields": [{"name": "message"}]},
    )

    assert "Return only one valid JSON object" in system
    payload = json.loads(user)
    assert payload["subject_prompt"] == "Ask about a website rebuild"
    assert "<html>" not in user
    assert "cookie" not in user.lower()


def test_parser_accepts_fenced_json_and_requires_both_fields() -> None:
    result = parse_generated_content(
        '```json\n{"subject":"Hello","message":"A short note"}\n```',
        provider="openai",
        model="gpt-5",
    )
    assert result.subject == "Hello"
    assert result.message == "A short note"
    assert result.provider == "openai"

    with pytest.raises(LlmError, match="usable message"):
        parse_generated_content('{"subject":"Hello","message":""}')


@pytest.mark.parametrize(
    ("client_type", "expected_url", "response"),
    [
        (
            OpenAIClient,
            "https://api.openai.com/v1/responses",
            {"output_text": '{"subject":"OpenAI subject","message":"OpenAI message"}'},
        ),
        (
            AnthropicClient,
            "https://api.anthropic.com/v1/messages",
            {"content": [{"type": "text", "text": '{"subject":"Claude subject","message":"Claude message"}'}]},
        ),
        (
            DeepSeekClient,
            "https://api.deepseek.com/chat/completions",
            {"choices": [{"message": {"content": '{"subject":"DeepSeek subject","message":"DeepSeek message"}'}}]},
        ),
    ],
)
def test_provider_adapters_normalize_responses(
    monkeypatch: pytest.MonkeyPatch, client_type, expected_url, response
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        calls.append((url, kwargs))
        return _Response(response)

    monkeypatch.setattr("formharvester.llm.providers.requests.post", fake_post)
    client = client_type(api_key="secret", model="model-x")
    result = client.generate("subject prompt", "message prompt", {"target_url": "https://acme.test"})

    assert calls[0][0] == expected_url
    assert calls[0][1]["timeout"] == 60
    assert result.provider == client.provider
    assert result.model == "model-x"
    assert result.subject.endswith("subject")


def test_deepseek_requests_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> _Response:
        captured.update(kwargs)
        return _Response({"choices": [{"message": {"content": '{"subject":"S","message":"M"}'}}]})

    monkeypatch.setattr("formharvester.llm.providers.requests.post", fake_post)
    DeepSeekClient(api_key="secret", model="deepseek-v4-flash").generate("S", "M", {})

    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_provider_factory_validates_configuration() -> None:
    assert create_llm_client("openai", "secret", "gpt-5").provider == "openai"
    with pytest.raises(ValueError, match="requires an API key"):
        create_llm_client("openai", "", "gpt-5")
    with pytest.raises(ValueError, match="unknown LLM provider"):
        create_llm_client("unknown", "secret", "model")


class _Field:
    def __init__(self, tag: str, **attributes: str) -> None:
        self.tag_name = tag
        self.attributes = attributes
        self.value = ""

    def get_attribute(self, name: str) -> str:
        if name == "outerHTML":
            return f"<{self.tag_name} " + " ".join(f'{k}="{v}"' for k, v in self.attributes.items()) + ">"
        return self.attributes.get(name, "")

    def clear(self) -> None:
        self.value = ""

    def send_keys(self, value: str) -> None:
        self.value = value


class _FormHarness(FormHandlerMixin):
    def __init__(self, client) -> None:
        self.details = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
            "subject": "Subject prompt",
            "message": "Message prompt",
            "phone": "",
            "location": "",
            "city": "",
            "state": "",
        }
        self.send_form = True
        self.DEBUG = False
        self.llm_enabled = True
        self.llm_client = client
        self.review_before_submit = False
        self.review_callback = None
        self.technologies = []
        self.scraped_emails = set()
        self.visited_links = []
        self.crawl = True
        self.threads = []
        self.name_filled = False
        self.last_status = None
        self.generated_content = None
        self.llm_error = None
        self.subject = _Field("input", type="text", name="subject")
        self.textarea = _Field("textarea", name="message")
        self.submitted = False
        switch = type("Switch", (), {"window": lambda _self, _handle: None})()
        self.driver = cast(Any, type("Driver", (), {"switch_to": switch, "window_handles": ["main"]})())

    def get(self, *_args, **_kwargs):
        return True

    def bot_print(self, *_args, **_kwargs):
        return None

    def _note_visited(self, url):
        return None

    def _scan_technologies(self):
        return []

    def check_time(self):
        return None

    def scrape_emails(self):
        return None

    def cms_check(self):
        return None

    def wait_show_element(self, *_args, **_kwargs):
        return None

    def css(self, selector, node=None, getall=False, attr=None, wait=None, wait_for=None):
        if selector == "input":
            return [self.subject] if getall else self.subject
        if selector == "textarea":
            return [self.textarea] if getall else self.textarea
        return []

    def xpath(self, *_args, **_kwargs):
        return ""

    def click(self, *_args, **_kwargs):
        return None

    def write(
        self, field, text, css=False, xpath=False, name=False, wait=False, clear=False, human=False, submit=False
    ):
        field.value = text

    def press_key(self, *_args, **_kwargs):
        return None

    def check_solve_captchas(self, recaptcha=False, image=False):
        return True

    def find_submit_button(self):
        return "submit"

    def submit_button(self, btn):
        self.submitted = True

    def _set_status(self, url, status):
        self.last_status = status


class _FakeLlm:
    provider = "test"
    model = "test-model"

    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.context = None

    def generate(self, subject_prompt, message_prompt, context):
        self.context = (subject_prompt, message_prompt, context)
        if self.failure:
            raise self.failure
        return GeneratedFormContent("Generated subject", "Generated message", self.provider, self.model)


def test_generated_content_replaces_subject_and_message_before_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forms_module.time, "sleep", lambda _seconds: None)
    client = _FakeLlm()
    harness = _FormHarness(client)

    assert harness.process_url("https://acme.test") is True
    assert harness.subject.value == "Generated subject"
    assert harness.textarea.value == "Generated message"
    assert harness.submitted is True
    assert client.context is not None
    assert client.context[2]["target_url"] == "https://acme.test"
    assert "outerHTML" not in json.dumps(client.context[2])


def test_generation_failure_sets_status_and_never_submits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forms_module.time, "sleep", lambda _seconds: None)
    harness = _FormHarness(_FakeLlm(LlmError("provider unavailable")))

    assert harness.process_url("https://acme.test") is False
    assert harness.last_status == "LLM_ERROR"
    assert harness.submitted is False
    assert harness.llm_error == "provider unavailable"


def test_review_skip_prevents_form_fill_and_submission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forms_module.time, "sleep", lambda _seconds: None)
    harness = _FormHarness(_FakeLlm())
    harness.review_before_submit = True
    harness.review_callback = lambda _url, _content: None

    assert harness.process_url("https://acme.test") is True
    assert harness.last_status == "REVIEW_SKIPPED"
    assert harness.subject.value == ""
    assert harness.textarea.value == ""
    assert harness.submitted is False
