"""Settings and campaign profiles."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from formharvester.settings import (
    CampaignPolicy,
    CampaignProfile,
    FormFill,
    GoogleSettings,
    Settings,
    list_profiles,
    load_profile,
    load_settings,
    save_profile,
    save_settings,
)


def test_defaults_round_trip(tmp_path):
    save_settings(Settings(), tmp_path)
    assert load_settings(tmp_path) == Settings()


def test_settings_round_trip(tmp_path):
    settings = Settings(active_profile="solar")
    settings.engine.headless = True
    settings.google.max_pages = 9
    settings.captcha.provider = "2captcha"
    settings.llm.enabled = True
    settings.llm.provider = "deepseek"
    settings.llm.model = "deepseek-v4-flash"
    settings.llm.deepseek_api_key = "secret"
    save_settings(settings, tmp_path)

    loaded = load_settings(tmp_path)
    assert loaded.active_profile == "solar"
    assert loaded.engine.headless is True
    assert loaded.google.max_pages == 9
    assert loaded.captcha.provider == "2captcha"
    assert loaded.llm.enabled is True
    assert loaded.llm.provider == "deepseek"
    assert loaded.llm.model == "deepseek-v4-flash"
    assert loaded.llm.api_key_for_provider() == "secret"


def test_missing_settings_file_yields_defaults(tmp_path):
    assert load_settings(tmp_path) == Settings()


def test_profile_round_trip(tmp_path):
    profile = CampaignProfile(
        name="solar",
        form_fill=FormFill(email="a@b.com", message="hello"),
        queries=["solar panels austin"],
    )
    save_profile(profile, tmp_path)

    assert list_profiles(tmp_path) == ["solar"]
    assert load_profile("solar", tmp_path) == profile


def test_missing_profile_returns_empty_named_profile(tmp_path):
    profile = load_profile("nope", tmp_path)
    assert profile.name == "nope"
    assert profile.queries == []


def test_legacy_campaign_text_is_seeded_as_llm_prompt():
    profile = CampaignProfile.model_validate(
        {
            "name": "legacy",
            "form_fill": {
                "subject": "Submitted subject",
                "message": "Submitted message",
            },
        }
    )

    assert profile.form_fill.subject == "Submitted subject"
    assert profile.form_fill.message == "Submitted message"
    assert profile.form_fill.subject_prompt == "Submitted subject"
    assert profile.form_fill.message_prompt == "Submitted message"


def test_campaign_can_keep_direct_text_and_llm_prompt_separately():
    form_fill = FormFill(
        subject="Submitted subject",
        message="Submitted message",
        subject_prompt="Ask about their services",
        message_prompt="Write a concise introduction.",
    )

    assert form_fill.as_engine_details()["subject"] == "Submitted subject"
    assert form_fill.as_engine_details()["subject_prompt"] == "Ask about their services"
    assert form_fill.as_engine_details()["message_prompt"] == "Write a concise introduction."
    assert form_fill.as_engine_details(llm_enabled=True)["subject"] == "Ask about their services"
    assert form_fill.as_engine_details(llm_enabled=True)["message"] == "Write a concise introduction."


def test_list_profiles_is_empty_before_anything_is_saved(tmp_path):
    assert list_profiles(tmp_path) == []


def test_max_delay_cannot_be_below_min_delay():
    with pytest.raises(ValidationError, match="max_delay"):
        GoogleSettings(min_delay=30, max_delay=5)


@pytest.mark.parametrize("field", ["max_pages", "start_page"])
def test_google_bounds(field):
    with pytest.raises(ValidationError):
        GoogleSettings(**{field: 0})


def test_max_time_must_be_positive():
    with pytest.raises(ValidationError):
        Settings.model_validate({"engine": {"max_time": 0}})


def test_campaign_policy_defaults_are_safe():
    policy = CampaignPolicy()
    assert policy.autopilot_enabled is False
    assert policy.require_review is True
    assert policy.cooldown_days == 30
    assert policy.minimum_score == 60
