"""The ``formharvester discover`` command."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import formharvester.api as api_module
from formharvester.api import CaptchaError
from formharvester.cli import cli
from formharvester.settings import Settings, save_settings

runner = CliRunner()


class _FakeHarvester:
    """Stands in for FormHarvester so no browser is started."""

    last_options = None

    def __init__(self, details, options=None):
        _FakeHarvester.last_options = options
        self.closed = False

    def discover_many(self, queries):
        return [f"https://{q.replace(' ', '-')}.com" for q in queries]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_harvester(monkeypatch):
    _FakeHarvester.last_options = None
    monkeypatch.setattr(api_module, "FormHarvester", _FakeHarvester)
    return _FakeHarvester


def test_prints_one_url_per_line(fake_harvester):
    result = runner.invoke(cli, ["discover", "roofing austin"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "https://roofing-austin.com"


def test_accepts_several_queries(fake_harvester):
    result = runner.invoke(cli, ["discover", "roofing austin", "solar dallas"])

    assert result.exit_code == 0
    assert result.stdout.split() == ["https://roofing-austin.com", "https://solar-dallas.com"]


def test_flags_override_saved_settings(fake_harvester, isolated_home):
    settings = Settings()
    settings.google.max_pages = 2
    save_settings(settings, isolated_home)

    runner.invoke(cli, ["discover", "q", "--max-pages", "7", "--keyword", "roof", "-k", "solar"])

    options = fake_harvester.last_options
    assert options.max_pages == 7
    assert options.keywords == ["roof", "solar"]


def test_falls_back_to_saved_settings(fake_harvester, isolated_home):
    settings = Settings()
    settings.google.max_pages = 4
    settings.google.min_delay = 3
    settings.google.max_delay = 11
    save_settings(settings, isolated_home)

    runner.invoke(cli, ["discover", "q"])

    options = fake_harvester.last_options
    assert options.max_pages == 4
    assert options.min_delay == 3
    assert options.max_delay == 11


def test_never_submits_forms(fake_harvester):
    runner.invoke(cli, ["discover", "q"])
    assert fake_harvester.last_options.send_form is False


def test_writes_no_files(fake_harvester, isolated_home):
    runner.invoke(cli, ["discover", "q"])
    assert list(isolated_home.iterdir()) == []


def test_captcha_exits_nonzero_with_a_message(monkeypatch):
    class _Blocked(_FakeHarvester):
        def discover_many(self, queries):
            raise CaptchaError("The search engine served a captcha.")

    monkeypatch.setattr(api_module, "FormHarvester", _Blocked)
    result = runner.invoke(cli, ["discover", "q"])

    assert result.exit_code == 1
    assert "captcha" in result.output.lower()
