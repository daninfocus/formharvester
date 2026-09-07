"""Runtime output goes beside the config, not into the working directory.

The executable is launched from wherever the user keeps it, so anything written
relative to the process's working directory either lands somewhere unexpected
or fails outright.
"""

from __future__ import annotations

import json
import os

from formharvester.cli.progress import ProgressMixin
from formharvester.settings import config_home, data_dir, log_dir
from formharvester.technology import TechnologyEvidence, TechnologyMatch


class _Harness(ProgressMixin):
    """ProgressMixin needs only these two attributes to resolve its paths."""

    def __init__(self, directory):
        self.data_dir = directory
        self.mode = "roofing"
        self.visited_websites = []
        self.scraped_emails = set()
        self.generate_email_sources = True
        self.detect_technologies = True
        self.technologies = []


def test_directories_sit_under_the_config_home(tmp_path):
    assert data_dir(tmp_path) == tmp_path / "data"
    assert log_dir(tmp_path) == tmp_path / "log"


def test_directories_follow_formharvester_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    assert config_home() == tmp_path
    assert data_dir() == tmp_path / "data"


def test_progress_files_land_in_the_data_dir(tmp_path):
    bot = _Harness(tmp_path / "data")

    assert bot.get_progress_file(google=False) == str(tmp_path / "data" / "roofing_progress.txt")
    assert bot.get_progress_file(google=True) == str(tmp_path / "data" / "roofing_progress_google.txt")
    assert bot.website_log_file == tmp_path / "data" / "website_log.txt"
    assert bot.remaining_pages_file == tmp_path / "data" / "remaining_google_pages.json"


def test_load_txt_creates_a_missing_directory(tmp_path):
    """Reproduces the crash: reading the site log before data/ exists."""
    missing = tmp_path / "data" / "website_log.txt"
    assert not missing.parent.exists()

    assert ProgressMixin.load_txt(missing) == []
    assert missing.exists()


def test_writing_outputs_does_not_touch_the_working_directory(tmp_path, monkeypatch):
    work = tmp_path / "elsewhere"
    work.mkdir()
    monkeypatch.chdir(work)

    bot = _Harness(tmp_path / "data")
    bot.log_website("https://acme.com/contact")
    bot.scraped_emails = {("hi@acme.com", "https://acme.com")}
    bot.export_emails(filename="roofing")
    bot.write_progress(["https://acme.com"], google=False)

    assert (tmp_path / "data" / "website_log.txt").read_text().strip() == "https://acme.com"
    assert "hi@acme.com" in (tmp_path / "data" / "roofing_emails.txt").read_text()
    assert (tmp_path / "data" / "roofing_progress.txt").exists()

    # nothing leaked into the process's working directory
    assert os.listdir(work) == []


def test_technology_export_is_jsonl_and_stays_in_data_dir(tmp_path):
    bot = _Harness(tmp_path / "data")
    bot.technologies = [
        TechnologyMatch(
            name="Next.js",
            category="Web framework",
            confidence=0.98,
            evidence=[TechnologyEvidence("resource_url", "/_next/static/app.js", "Next.js runtime marker")],
        )
    ]

    bot.export_technologies("https://acme.com", filename="roofing")
    record = json.loads((tmp_path / "data" / "roofing_technologies.jsonl").read_text().strip())

    assert record["url"] == "https://acme.com"
    assert record["technologies"][0]["name"] == "Next.js"
    assert record["technologies"][0]["evidence"][0]["source"] == "resource_url"
