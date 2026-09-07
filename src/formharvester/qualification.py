"""Deterministic lead qualification and submission policy checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from formharvester.leads import LeadRecord

if TYPE_CHECKING:
    from formharvester.settings import CampaignPolicy

__all__ = ["QualificationResult", "PolicyDecision", "qualify_site", "evaluate_policy"]


@dataclass(frozen=True, slots=True)
class QualificationResult:
    """A reproducible score with the reasons a site received it."""

    score: float
    reasons: list[str]

    @property
    def qualified(self) -> bool:
        return self.score >= 60


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The explainable result of evaluating one submission policy."""

    allowed: bool
    reasons: list[str]


def qualify_site(
    *,
    technologies: list[dict[str, object]],
    emails: list[str],
    form_found: bool,
) -> QualificationResult:
    """Score only observable site signals; no LLM call is involved."""
    score = 0.0
    reasons: list[str] = []

    if form_found:
        score += 45
        reasons.append("Contact form available (+45)")
    else:
        reasons.append("No contact form found (+0)")

    if emails:
        score += 20
        reasons.append(f"Public contact email found (+20; {len(emails)} found)")
    else:
        reasons.append("No public contact email found (+0)")

    if technologies:

        def confidence(item: dict[str, object]) -> float:
            try:
                return float(str(item.get("confidence", 0) or 0))
            except ValueError:
                return 0.0

        best_confidence = max(confidence(item) for item in technologies)
        technology_names = ", ".join(str(item.get("name", "unknown")) for item in technologies[:3])
        if best_confidence >= 0.9:
            score += 20
            reasons.append(f"Strong technology signals: {technology_names} (+20)")
        elif best_confidence >= 0.7:
            score += 12
            reasons.append(f"Moderate technology signals: {technology_names} (+12)")
        else:
            score += 5
            reasons.append(f"Weak technology signals: {technology_names} (+5)")
    else:
        reasons.append("No technology signals found (+0)")

    return QualificationResult(score=min(100.0, score), reasons=reasons)


def evaluate_policy(
    record: LeadRecord,
    policy: CampaignPolicy,
    *,
    cooldown_allowed: bool = True,
    cooldown_reason: str = "No previous submission attempt.",
    attempts_today: int = 0,
    attempts_this_run: int = 0,
    llm_enabled: bool = True,
) -> PolicyDecision:
    """Evaluate the strict, selective-autopilot gate for a lead."""
    reasons: list[str] = []
    failures: list[str] = []

    if not policy.autopilot_enabled:
        return PolicyDecision(True, ["Selective autopilot is disabled; normal campaign behavior applies."])

    if policy.dry_run:
        failures.append("Campaign is in dry-run mode; no submission is permitted.")
    if not llm_enabled:
        failures.append("Selective autopilot requires LLM-generated content.")
    if record.score < policy.minimum_score:
        failures.append(f"Lead score {record.score:.1f} is below the {policy.minimum_score:.1f} minimum.")
    else:
        reasons.append(f"Lead score {record.score:.1f} meets the {policy.minimum_score:.1f} minimum.")
    if policy.require_contact_form and not record.form_found:
        failures.append("No contact form was found.")
    if policy.include_technologies:
        detected = {str(item.get("name", "")).casefold() for item in record.technologies}
        required = {value.casefold() for value in policy.include_technologies}
        if not detected.intersection(required):
            failures.append("None of the required technologies were detected.")
        else:
            reasons.append("Required technology detected.")
    if policy.exclude_technologies:
        detected = {str(item.get("name", "")).casefold() for item in record.technologies}
        excluded = {value.casefold() for value in policy.exclude_technologies}
        matches = sorted(detected.intersection(excluded))
        if matches:
            failures.append(f"Excluded technology detected: {', '.join(matches)}.")
    if not cooldown_allowed:
        failures.append(cooldown_reason)
    else:
        reasons.append(cooldown_reason)
    if attempts_this_run >= policy.max_submissions_per_run:
        failures.append("The campaign run submission limit has been reached.")
    if attempts_today >= policy.max_submissions_per_day:
        failures.append("The campaign daily submission limit has been reached.")

    return PolicyDecision(not failures, reasons + failures)
