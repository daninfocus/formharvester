"""Tests for the local lead repository."""

from __future__ import annotations

import csv

from formharvester.leads import LeadRepository, lead_id


def test_lead_id_is_stable_and_campaign_scoped() -> None:
    assert lead_id("Roofing", "https://example.com") == lead_id("roofing", "HTTPS://EXAMPLE.COM")
    assert lead_id("roofing", "example.com") != lead_id("solar", "example.com")


def test_repository_persists_enrichment_and_audit(tmp_path) -> None:
    with LeadRepository(tmp_path / "data") as repository:
        record = repository.upsert_discovered("roofing", "example.com", url="https://example.com", query="roofers")
        enriched = repository.update_enrichment(
            "roofing",
            "example.com",
            status="QUALIFIED",
            score=82,
            reasons=["Contact form available", "WordPress detected"],
            technologies=[{"name": "WordPress", "confidence": 0.98}],
            emails=["hello@example.com"],
            form_found=True,
        )

        assert repository.path.exists()
        assert enriched.id == record.id
        assert enriched.score == 82
        assert enriched.emails == ["hello@example.com"]
        assert repository.audit(record.id)[-1]["event_type"] == "DISCOVERED"
        assert {event["event_type"] for event in repository.audit(record.id)} == {"DISCOVERED", "ENRICHED"}


def test_repository_attempts_suppression_metrics_and_export(tmp_path) -> None:
    with LeadRepository(tmp_path / "data") as repository:
        record = repository.upsert_discovered("campaign", "example.com")
        repository.update_enrichment(
            "campaign",
            "example.com",
            status="QUALIFIED",
            score=90,
            reasons=["Form found"],
            technologies=[],
            emails=[],
            form_found=True,
        )
        assert repository.is_eligible_for_attempt(record.id, cooldown_days=30)[0] is True
        repository.record_attempt(record.id, "SUBMITTED", detail={"policy": "passed"})
        eligible, reason = repository.is_eligible_for_attempt(record.id, cooldown_days=30)
        assert eligible is False
        assert "cooldown" in reason
        assert repository.metrics("campaign")["submitted"] == 1

        suppressed = repository.suppress(record.id)
        assert suppressed.suppressed is True
        assert repository.is_eligible_for_attempt(record.id, cooldown_days=0)[0] is False

        destination = repository.export_csv(tmp_path / "export.csv", campaign="campaign")
        with destination.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["domain"] == "example.com"
        assert rows[0]["status"] == "SUPPRESSED"
