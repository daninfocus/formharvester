"""Tests for deterministic lead scoring and autopilot policy checks."""

from __future__ import annotations

from typing import Any

from formharvester.leads import LeadRecord
from formharvester.qualification import evaluate_policy, qualify_site
from formharvester.settings import CampaignPolicy


def _lead(**overrides) -> LeadRecord:
    values: dict[str, Any] = {
        "id": "lead-1",
        "campaign": "campaign",
        "domain": "example.com",
        "url": "https://example.com",
        "score": 85,
        "form_found": True,
        "technologies": [{"name": "WordPress", "confidence": 0.98}],
        "emails": ["hello@example.com"],
    }
    values.update(overrides)
    return LeadRecord(**values)


def test_qualification_is_deterministic_and_explainable() -> None:
    result = qualify_site(
        technologies=[{"name": "WordPress", "confidence": 0.98}],
        emails=["hello@example.com"],
        form_found=True,
    )
    assert result.score == 85
    assert result.qualified is True
    assert any("Contact form" in reason for reason in result.reasons)


def test_policy_requires_explicit_autopilot_and_strict_signals() -> None:
    policy = CampaignPolicy(autopilot_enabled=True, include_technologies=["WordPress"])
    decision = evaluate_policy(
        _lead(),
        policy,
        cooldown_allowed=True,
        attempts_today=0,
        attempts_this_run=0,
        llm_enabled=True,
    )
    assert decision.allowed is True
    assert any("meets" in reason for reason in decision.reasons)

    blocked = evaluate_policy(
        _lead(score=40, technologies=[]),
        policy,
        cooldown_allowed=False,
        cooldown_reason="A submission attempt exists within the 30-day cooldown.",
        llm_enabled=True,
    )
    assert blocked.allowed is False
    assert any("below" in reason for reason in blocked.reasons)
    assert any("cooldown" in reason for reason in blocked.reasons)


def test_policy_dry_run_and_limits_never_allow_submission() -> None:
    policy = CampaignPolicy(autopilot_enabled=True, dry_run=True, max_submissions_per_run=1)
    decision = evaluate_policy(
        _lead(),
        policy,
        attempts_this_run=1,
        llm_enabled=True,
    )
    assert decision.allowed is False
    assert any("dry-run" in reason for reason in decision.reasons)
    assert any("limit" in reason for reason in decision.reasons)
