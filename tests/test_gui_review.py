"""Network-free tests for the GUI manual-review handshake."""

from __future__ import annotations

import threading
import time

from formharvester.gui.api import Api
from formharvester.leads import LeadRepository
from formharvester.llm import GeneratedFormContent
from formharvester.settings import (
    CampaignProfile,
    EngineSettings,
    LlmSettings,
    Settings,
    list_profiles,
    load_profile,
    load_settings,
    save_profile,
    save_settings,
)


def _wait_for_review(api: Api) -> dict[str, str]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        review = api.poll()["review"]
        if review is not None:
            return review
        time.sleep(0.01)
    raise AssertionError("review was not published")


def test_gui_review_approval_returns_edited_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    api = Api()
    result: list[GeneratedFormContent | None] = []
    thread = threading.Thread(
        target=lambda: result.append(
            api._request_review(
                "https://acme.test",
                GeneratedFormContent("Generated subject", "Generated message", "openai", "gpt-5"),
                threading.Event(),
            )
        )
    )
    thread.start()
    review = _wait_for_review(api)

    assert api.approve_review(review["id"], "Edited subject", "Edited message") == {"ok": True}
    thread.join(timeout=2)
    assert result == [GeneratedFormContent("Edited subject", "Edited message", "openai", "gpt-5")]
    assert api.poll()["review"] is None


def test_gui_review_skip_returns_none_and_clears_pending_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    api = Api()
    result: list[GeneratedFormContent | None] = []
    thread = threading.Thread(
        target=lambda: result.append(
            api._request_review(
                "https://acme.test",
                GeneratedFormContent("Subject", "Message", "deepseek", "deepseek-v4-flash"),
                threading.Event(),
            )
        )
    )
    thread.start()
    review = _wait_for_review(api)

    assert api.skip_review(review["id"]) == {"ok": True}
    thread.join(timeout=2)
    assert result == [None]
    assert api.poll()["review"] is None


def test_campaign_rename_preserves_data_and_updates_active_campaign(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    save_settings(Settings(active_profile="old-name"))
    save_profile(CampaignProfile(name="old-name", queries=["roofing"], keywords=["contact"]))
    save_profile(CampaignProfile(name="other"))

    assert Api().rename_profile("old-name", "new-name") == {"ok": True}

    assert list_profiles() == ["new-name", "other"]
    assert load_profile("new-name").queries == ["roofing"]
    assert load_profile("new-name").keywords == ["contact"]
    assert load_settings().active_profile == "new-name"


def test_campaign_delete_switches_active_campaign_and_keeps_one(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    save_settings(Settings(active_profile="first"))
    save_profile(CampaignProfile(name="first"))
    save_profile(CampaignProfile(name="second"))
    api = Api()

    assert api.delete_profile("first") == {"ok": True}
    assert list_profiles() == ["second"]
    assert load_settings().active_profile == "second"
    assert not (tmp_path / "profiles" / "first.json").exists()
    assert api.delete_profile("second") == {
        "ok": False,
        "error": "Keep at least one campaign configured.",
    }


def test_gui_start_warns_when_llm_has_no_provider_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    save_settings(
        Settings(
            active_profile="campaign",
            engine=EngineSettings(send_form=True),
            llm=LlmSettings(enabled=True, provider="openai"),
        )
    )
    save_profile(CampaignProfile(name="campaign", queries=["roofing"]))

    result = Api().start()

    assert result == {
        "ok": False,
        "error": "LLM is enabled, but no openai API key is configured in Settings.",
    }


def test_gui_lead_queue_lists_suppresses_and_exports(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    save_settings(Settings(active_profile="campaign"))
    save_profile(CampaignProfile(name="campaign"))
    with LeadRepository(tmp_path / "data") as leads:
        record = leads.upsert_discovered("campaign", "example.com", url="https://example.com")
        leads.update_enrichment(
            "campaign",
            "example.com",
            status="QUALIFIED",
            score=85,
            reasons=["Contact form available"],
            technologies=[{"name": "WordPress", "confidence": 0.98}],
            emails=["hello@example.com"],
            form_found=True,
        )

    api = Api()
    payload = api.get_leads()
    assert payload["metrics"]["qualified"] == 1
    assert payload["leads"][0]["domain"] == "example.com"
    assert api.suppress_lead(record.id)["ok"] is True
    assert api.get_leads("SUPPRESSED")["leads"][0]["suppressed"] is True
    assert api.export_leads()["ok"] is True


def test_gui_health_refreshes_in_background_and_caches_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    calls: list[str] = []

    def llm_health(_settings) -> dict[str, str]:
        calls.append("llm")
        return {"name": "LLM", "state": "ok", "detail": "openai: ready"}

    def captcha_health(_settings) -> dict[str, str]:
        calls.append("captcha")
        return {"name": "CAPTCHA", "state": "disabled", "detail": "not configured"}

    monkeypatch.setattr("formharvester.gui.api.check_llm_health", llm_health)
    monkeypatch.setattr("formharvester.gui.api.check_captcha_health", captcha_health)
    api = Api()

    initial = api.get_health()
    assert initial["llm"]["state"] == "checking"
    assert initial["captcha"]["state"] == "checking"

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        refreshed = api.get_health()
        if refreshed["llm"]["state"] != "checking":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("health check did not finish")

    assert refreshed == {
        "llm": {"name": "LLM", "state": "ok", "detail": "openai: ready"},
        "captcha": {"name": "CAPTCHA", "state": "disabled", "detail": "not configured"},
    }
    assert calls == ["llm", "captcha"]
    assert api.get_health() == refreshed


def test_gui_poll_survives_a_transiently_empty_settings_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    (tmp_path / "formharvester.json").write_text("", encoding="utf-8")

    payload = Api().poll()

    assert payload["lead_metrics"] == {}
    assert payload["lines"] == []
