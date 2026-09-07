"""The ``formharvester leads`` commands."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from formharvester.cli import cli
from formharvester.leads import LeadRepository
from formharvester.settings import CampaignProfile, Settings, save_profile, save_settings

runner = CliRunner()


def test_leads_commands_list_metrics_and_export(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    save_settings(Settings(active_profile="campaign"))
    save_profile(CampaignProfile(name="campaign"))
    with LeadRepository(tmp_path / "data") as leads:
        record = leads.upsert_discovered("campaign", "example.com")
        leads.update_enrichment(
            "campaign",
            "example.com",
            status="QUALIFIED",
            score=75,
            reasons=["Contact form available"],
            technologies=[],
            emails=[],
            form_found=True,
        )
        leads.record_attempt(record.id, "SUBMITTED")

    listed = runner.invoke(cli, ["leads", "list"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)["domain"] == "example.com"

    metrics = runner.invoke(cli, ["leads", "metrics"])
    assert metrics.exit_code == 0
    assert json.loads(metrics.stdout)["submitted"] == 1

    output = tmp_path / "out.csv"
    exported = runner.invoke(cli, ["leads", "export", "--output", str(output)])
    assert exported.exit_code == 0
    assert output.exists()
